"""
Primary UI and state coordinator for Meeting Recorder.  Manages the recording
lifecycle (IDLE, RECORDING, PAUSED), user interactions, and
background processing jobs for transcription and summarization.
"""
from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from ..config import settings
from ..utils.glib_bridge import assert_main_thread, idle_call
from .recording_controls import RecordingControlsMixin
from .job_manager import JobManagerMixin

logger = logging.getLogger(__name__)

from ..utils.api_keys import LITELLM_KEY_MAP as _LITELLM_KEY_MAP


class State(Enum):
    IDLE = auto()
    RECORDING = auto()
    PAUSED = auto()


@dataclass
class _Job:
    job_id: int
    audio_path: Path | None
    transcript_path: Path | None
    notes_path: Path | None
    label: str
    source_path: Path | None = None  # for Transcribe File retry
    status: str = "processing"   # "processing" | "done" | "error"
    error_msg: str | None = None
    cancelled: bool = False
    created_at: datetime = field(default_factory=datetime.now)


def _format_time(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class MainWindow(RecordingControlsMixin, JobManagerMixin, Gtk.ApplicationWindow):
    def __init__(self, audio_backend=None, screen_recorder=None, nightlight_inhibitor=None, **kwargs) -> None:
        super().__init__(title="Meeting Recorder", **kwargs)
        self.set_default_size(425, 450)
        self.set_resizable(True)

        self._audio_backend = audio_backend
        self._screen_recorder = screen_recorder
        self._nightlight_inhibitor = nightlight_inhibitor
        self._state = State.IDLE
        self._recorder = None
        self._recording_mode: str = "headphones"
        self._audio_path: Path | None = None
        self._transcript_path: Path | None = None
        self._notes_path: Path | None = None
        self._jobs: list[_Job] = []
        self._next_job_id: int = 0
        self._job_widgets: dict[int, dict] = {}
        self._expiry_timer_id: int | None = None

        self._build_ui()
        self._transition(State.IDLE)
        self.connect("delete-event", self._on_delete)

    # ---- UI construction -------------------------------------------------

    def _build_ui(self) -> None:
        from .meeting_explorer import MeetingExplorer

        # -- Stack for Recorder / Explorer views --
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.add(self._stack)

        # -- Recorder page --
        recorder_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Error info bar
        self._info_bar = Gtk.InfoBar()
        self._info_bar.set_message_type(Gtk.MessageType.ERROR)
        self._info_bar_label = Gtk.Label(label="")
        self._info_bar_label.set_line_wrap(True)
        self._info_bar.get_content_area().add(self._info_bar_label)
        self._info_bar.add_button("Dismiss", Gtk.ResponseType.CLOSE)
        self._info_bar.connect("response", self._on_info_bar_response)
        self._info_bar.set_no_show_all(True)
        recorder_page.pack_start(self._info_bar, False, False, 0)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(vbox, f"set_margin_{side}")(24)
        recorder_page.pack_start(vbox, False, False, 0)

        self._timer_label = Gtk.Label(label="00:00")
        self._timer_label.get_style_context().add_class("timer-label")
        self._timer_label.set_attributes(self._make_timer_attrs())
        vbox.pack_start(self._timer_label, False, False, 0)

        self._status_label = Gtk.Label(label="")
        self._status_label.set_line_wrap(True)
        self._status_label.set_xalign(0.5)
        vbox.pack_start(self._status_label, False, False, 0)

        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl = Gtk.Label(label="Title (optional):")
        lbl.set_xalign(0)
        self._title_entry = Gtk.Entry()
        self._title_entry.set_placeholder_text("e.g. Standup, Sprint Planning\u2026")
        self._title_entry.set_hexpand(True)
        title_box.pack_start(lbl, False, False, 0)
        title_box.pack_start(self._title_entry, True, True, 0)
        vbox.pack_start(title_box, False, False, 0)

        self._button_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8, homogeneous=False)
        self._button_box.set_halign(Gtk.Align.CENTER)
        vbox.pack_start(self._button_box, False, False, 0)

        # Output paths (shown after "cancel and save")
        self._output_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._output_box.set_no_show_all(True)
        self._output_label = Gtk.Label(label="")
        self._output_label.set_line_wrap(True)
        self._output_label.set_xalign(0)
        self._open_folder_btn = Gtk.Button(label="Open Output Folder")
        self._open_folder_btn.connect("clicked", self._on_open_folder)
        self._output_box.pack_start(self._output_label, False, False, 0)
        self._output_box.pack_start(self._open_folder_btn, False, False, 0)
        vbox.pack_start(self._output_box, False, False, 0)

        # Jobs section
        self._jobs_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._jobs_section.set_no_show_all(True)
        for side in ("start", "end"):
            getattr(self._jobs_section, f"set_margin_{side}")(24)
        self._jobs_section.set_margin_bottom(12)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._jobs_section.pack_start(sep, False, False, 0)
        jobs_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        jobs_hdr.set_margin_top(8)
        hdr_label = Gtk.Label()
        hdr_label.set_markup("<b>Background Jobs</b>")
        hdr_label.set_xalign(0)
        jobs_hdr.pack_start(hdr_label, True, True, 0)
        self._jobs_section.pack_start(jobs_hdr, False, False, 0)

        self._jobs_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._jobs_list.set_margin_top(4)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(180)
        scroll.set_propagate_natural_height(True)
        scroll.add(self._jobs_list)
        self._jobs_section.pack_start(scroll, False, False, 0)

        sep.show(); jobs_hdr.show_all(); scroll.show(); self._jobs_list.show()
        recorder_page.pack_start(self._jobs_section, False, False, 0)

        self._stack.add_titled(recorder_page, "recorder", "Recorder")

        # -- Explorer page --
        self._explorer = MeetingExplorer()
        self._stack.add_titled(self._explorer, "explorer", "Explorer")

        # Auto-refresh when switching to explorer
        self._stack.connect("notify::visible-child", self._on_stack_switch)

        # -- HeaderBar with StackSwitcher --
        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)

        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self._stack)
        hb.set_custom_title(switcher)

        settings_btn = Gtk.Button()
        settings_btn.set_image(
            Gtk.Image.new_from_icon_name("preferences-system", Gtk.IconSize.BUTTON))
        settings_btn.set_tooltip_text("Settings")
        settings_btn.connect("clicked", self._on_settings_clicked)
        hb.pack_end(settings_btn)
        self.set_titlebar(hb)

    def _on_stack_switch(self, stack, *_) -> None:
        if stack.get_visible_child_name() == "explorer":
            self._explorer.refresh()

    @staticmethod
    def _make_timer_attrs():
        gi.require_version("Pango", "1.0")
        from gi.repository import Pango
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_size_new_absolute(48 * Pango.SCALE))
        return attrs

    # ---- State machine ---------------------------------------------------

    def _transition(self, new_state: State, **kwargs) -> None:
        assert_main_thread()
        self._state = new_state
        self._update_ui(**kwargs)
        self._notify_tray()

    def _update_ui(self, status: str = "", **kwargs) -> None:
        assert_main_thread()
        for child in self._button_box.get_children():
            self._button_box.remove(child)

        bb = self._button_box
        state = self._state

        def _btn(label, icon, callback, css_class=None):
            b = Gtk.Button(label=label)
            if icon:
                b.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
            b.connect("clicked", lambda *_: callback())
            if css_class:
                b.get_style_context().add_class(css_class)
            return b

        if state == State.IDLE:
            self._timer_label.set_text("00:00")
            self._status_label.set_text(status or "Ready to record")
            self._title_entry.set_sensitive(True)
            self._output_box.hide()

            idle_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            record_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            record_row.set_homogeneous(True)

            hb = _btn("Record (Headphones)", "media-record",
                       self.on_record_headphones_clicked, "suggested-action")
            hb.set_tooltip_text("Record mic + system audio. Use when wearing headphones.")
            record_row.pack_start(hb, True, True, 0)

            sb = _btn("Record (Speaker)", "audio-volume-high",
                       self.on_record_speaker_clicked)
            sb.set_tooltip_text("Record mic only. Use when on speaker to avoid echo.")
            record_row.pack_start(sb, True, True, 0)

            idle_vbox.pack_start(record_row, False, False, 0)
            eb = _btn(" Transcribe File", "document-open",
                       self.on_transcribe_file_clicked)
            idle_vbox.pack_start(eb, False, False, 0)
            bb.pack_start(idle_vbox, False, False, 0)

        elif state in (State.RECORDING, State.PAUSED):
            self._title_entry.set_sensitive(False)
            if state == State.RECORDING:
                self._status_label.set_text(status or "Recording\u2026")
                self._output_box.hide()
                self._info_bar.hide()
                bb.pack_start(_btn(" Pause", "media-playback-pause",
                                   self.on_pause_clicked), False, False, 0)
            else:
                self._status_label.set_text(status or "Paused")
                bb.pack_start(_btn(" Resume", "media-playback-start",
                                   self.on_resume_clicked, "suggested-action"),
                              False, False, 0)
            bb.pack_start(_btn(" Stop", "media-playback-stop",
                               self.on_stop_clicked, "destructive-action"),
                          False, False, 0)
            bb.pack_start(_btn("Cancel (save recording)", None,
                               self.on_cancel_save_clicked), False, False, 0)
            bb.pack_start(_btn("Cancel", None,
                               self.on_cancel_clicked), False, False, 0)

        bb.show_all()

    def _notify_tray(self) -> None:
        app = self.get_application()
        if not (app and hasattr(app, "_tray") and app._tray):
            return
        state_names = {State.IDLE: "idle", State.RECORDING: "recording",
                       State.PAUSED: "paused"}
        tray_jobs = [
            (j.label, lambda j=j: idle_call(self._on_cancel_job, j))
            for j in self._jobs if j.status == "processing" and not j.cancelled
        ]
        try:
            app._tray.update(state_names.get(self._state, "idle"), tray_jobs)
        except Exception:
            pass

    # ---- Recorder / pipeline callbacks -----------------------------------

    def _on_tick(self, elapsed: int) -> None:
        idle_call(self._update_timer, elapsed)

    def _update_timer(self, elapsed: int) -> None:
        assert_main_thread()
        self._timer_label.set_text(_format_time(elapsed))

    def _on_recording_error(self, msg: str) -> None:
        idle_call(self._transition, State.IDLE)
        idle_call(self._show_error, msg)

    def _send_job_complete_notification(self, job: _Job) -> None:
        from .notifications import notify
        parts = [str(p) for p in (job.transcript_path, job.notes_path) if p]
        notify(summary="Meeting Recorded",
               body="\n".join(parts) if parts else "Processing complete.")

    # ---- Error display ---------------------------------------------------

    def _show_error(self, msg: str) -> None:
        assert_main_thread()
        logger.error("UI error shown: %s", msg)
        self._info_bar_label.set_text(msg)
        self._info_bar_label.set_selectable(True)
        self._info_bar.show()
        self._info_bar_label.show()

    def _on_info_bar_response(self, bar: Gtk.InfoBar, response_id: int) -> None:
        bar.hide()

    # ---- Settings --------------------------------------------------------

    def _on_settings_clicked(self, *_) -> None:
        from .settings_dialog import SettingsDialog
        nl_available = hasattr(self, '_nightlight_inhibitor') and self._nightlight_inhibitor.is_available()
        dialog = SettingsDialog(parent=self, nightlight_available=nl_available)
        dialog.run()
        dialog.destroy()
        app = self.get_application()
        if app:
            cfg = settings.load()
            if cfg.get("call_detection_enabled") and not app._call_detector:
                app._start_call_detector()
            elif not cfg.get("call_detection_enabled") and app._call_detector:
                app._call_detector.stop()
                app._call_detector = None

    # ---- Helpers ---------------------------------------------------------

    def _on_open_folder(self, *_) -> None:
        folder = os.path.expanduser(settings.load().get("output_folder", "~/meetings"))
        try:
            subprocess.Popen(["xdg-open", folder])
        except Exception:
            pass

    def present(self) -> None:
        self.set_skip_taskbar_hint(False)
        super().present()

    def hide_to_tray(self) -> None:
        self.set_skip_taskbar_hint(True)
        self.hide()

    def _on_delete(self, *_) -> bool:
        self.hide_to_tray()
        return True

    # ---- Tray activation -------------------------------------------------

    def _on_tray_activate(self) -> None:
        """Handle tray single-click — dispatch based on state and config."""
        cfg = settings.load()

        if self._state == State.PAUSED:
            self.on_resume_clicked()
            return

        if self._state == State.RECORDING:
            action = cfg.get("tray_recording_action", "stop")
            actions = {
                "stop": self.on_stop_clicked,
                "pause": self.on_pause_clicked,
                "cancel_save": self.on_cancel_save_clicked,
                "cancel_discard": self.on_cancel_clicked,
            }
            actions.get(action, self.on_stop_clicked)()
            return

        # IDLE
        action = cfg.get("tray_default_action", "record_headphones")
        actions = {
            "record_headphones": self.on_record_headphones_clicked,
            "record_speaker": self.on_record_speaker_clicked,
            "transcribe_file": self.on_transcribe_file_clicked,
        }
        actions.get(action, self.on_record_headphones_clicked)()
