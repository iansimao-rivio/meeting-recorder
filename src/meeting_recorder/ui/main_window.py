"""
Minimal floating overlay UI for Meeting Recorder.
Collapsed: small pill with icon + status dot + elapsed time.
Expanded (click): action buttons, title entry, settings/explorer, jobs.
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
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from ..config import settings
from ..utils.glib_bridge import assert_main_thread, idle_call
from .recording_controls import RecordingControlsMixin
from .job_manager import JobManagerMixin

logger = logging.getLogger(__name__)

from ..utils.api_keys import LITELLM_KEY_MAP as _LITELLM_KEY_MAP

try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell as _LayerShell
    _HAS_LAYER_SHELL = True
except (ValueError, ImportError, AttributeError):
    _HAS_LAYER_SHELL = False


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
    source_path: Path | None = None
    status: str = "processing"
    error_msg: str | None = None
    cancelled: bool = False
    created_at: datetime = field(default_factory=datetime.now)


def _format_time(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


_CSS = b"""
window, box, eventbox, revealer { background-color: transparent; }

.pill {
    background-color: rgba(18, 18, 18, 0.90);
    border-radius: 999px;
    padding: 6px 14px;
}
.pill-expanded {
    background-color: rgba(18, 18, 18, 0.92);
    border-radius: 14px;
    padding: 8px 12px;
}
.expanded-panel {
    background-color: rgba(18, 18, 18, 0.92);
    border-radius: 0 0 14px 14px;
    padding: 6px 12px 10px;
}

.dot      { font-size: 9px; }
.dot-idle { color: rgba(140,140,140,0.45); }
.dot-recording  { color: #e53935; }
.dot-paused     { color: #fb8c00; }
.dot-processing { color: #fdd835; }

.pill-timer { color: rgba(255,255,255,0.88); font-size: 12px; font-weight: bold; }

.icon-btn {
    background: none; border: none;
    color: rgba(255,255,255,0.35);
    font-size: 15px; padding: 2px 5px;
    min-height: 0; min-width: 0;
}
.icon-btn:hover { color: rgba(255,255,255,0.85); }

entry {
    background-color: rgba(255,255,255,0.08);
    color: rgba(255,255,255,0.85);
    border: none; border-radius: 6px;
    padding: 3px 6px; font-size: 12px;
    min-height: 0;
}
entry:focus { background-color: rgba(255,255,255,0.13); }

.ctrl-btn {
    background-color: rgba(255,255,255,0.07);
    border: none; border-radius: 8px;
    color: rgba(255,255,255,0.85); font-size: 12px;
    padding: 5px 10px; min-height: 0;
}
.ctrl-btn:hover { background-color: rgba(255,255,255,0.14); }
.ctrl-btn.suggested-action { color: #69f0ae; }
.ctrl-btn.destructive-action { color: #ef9a9a; }

.error-lbl { color: #ef9a9a; font-size: 11px; }
.output-lbl { color: rgba(255,255,255,0.55); font-size: 11px; }

separator { background-color: rgba(255,255,255,0.1); min-height: 1px; }

.job-row { font-size: 11px; color: rgba(255,255,255,0.7); }
"""


class MainWindow(RecordingControlsMixin, JobManagerMixin, Gtk.ApplicationWindow):
    def __init__(self, audio_backend=None, screen_recorder=None,
                 nightlight_inhibitor=None, **kwargs) -> None:
        super().__init__(title="Meeting Recorder", **kwargs)

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
        self._expanded = False

        # Enable RGBA compositing for transparency
        screen = Gdk.Screen.get_default()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.connect("draw", self._on_draw)

        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_resizable(False)

        # Layer shell must be configured before show_all()
        if _HAS_LAYER_SHELL:
            _LayerShell.init_for_window(self)
            _LayerShell.set_layer(self, _LayerShell.Layer.OVERLAY)
            _LayerShell.set_anchor(self, _LayerShell.Edge.TOP, True)
            _LayerShell.set_anchor(self, _LayerShell.Edge.RIGHT, True)
            _LayerShell.set_margin(self, _LayerShell.Edge.TOP, 12)
            _LayerShell.set_margin(self, _LayerShell.Edge.RIGHT, 20)

        self._apply_css()
        self._build_ui()

        self.connect("realize", self._on_realize)
        self.connect("delete-event", self._on_delete)

        self._transition(State.IDLE)

    def _on_draw(self, widget, cr) -> bool:
        # Clear entire window to transparent, then let children paint on top.
        # CAIRO_OPERATOR_SOURCE=1 with rgba(0,0,0,0) replaces destination alpha.
        cr.set_source_rgba(0, 0, 0, 0)
        cr.set_operator(1)  # CAIRO_OPERATOR_SOURCE
        cr.paint()
        cr.set_operator(2)  # CAIRO_OPERATOR_OVER
        return False

    def _apply_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(_CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _on_realize(self, *_) -> None:
        if not _HAS_LAYER_SHELL:
            w = self.get_screen().get_width()
            self.move(w - 250, 20)

    # ── Build UI ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Root event box — left click toggles expand, right click = tray action
        root_eb = Gtk.EventBox()
        root_eb.connect("button-press-event", self._on_pill_click)
        self.add(root_eb)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root_eb.add(outer)

        # ── Collapsed pill row ─────────────────────────────────────────
        self._pill_bg = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._pill_bg.get_style_context().add_class("pill")
        outer.pack_start(self._pill_bg, False, False, 0)

        mic = Gtk.Label(label="🎙")
        self._pill_bg.pack_start(mic, False, False, 0)

        self._dot = Gtk.Label(label="●")
        self._dot.get_style_context().add_class("dot")
        self._dot.get_style_context().add_class("dot-idle")
        self._pill_bg.pack_start(self._dot, False, False, 0)

        self._timer_label = Gtk.Label(label="")
        self._timer_label.get_style_context().add_class("pill-timer")
        self._timer_label.set_no_show_all(True)
        self._pill_bg.pack_start(self._timer_label, False, False, 0)

        # ── Expanded panel (Revealer) ──────────────────────────────────
        self._revealer = Gtk.Revealer()
        self._revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._revealer.set_transition_duration(150)
        self._revealer.set_reveal_child(False)
        outer.pack_start(self._revealer, False, False, 0)

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        panel.get_style_context().add_class("expanded-panel")
        self._revealer.add(panel)

        # Header: title entry + icon buttons
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        panel.pack_start(hdr, False, False, 0)

        self._title_entry = Gtk.Entry()
        self._title_entry.set_placeholder_text("Title (optional)")
        self._title_entry.set_hexpand(True)
        hdr.pack_start(self._title_entry, True, True, 0)

        for lbl, tip, cb in [
            ("⚙", "Settings", self._on_settings_clicked),
            ("📋", "Meetings", self._on_explorer_clicked),
            ("×", "Close panel", lambda *_: self._set_expanded(False)),
        ]:
            b = Gtk.Button(label=lbl)
            b.get_style_context().add_class("icon-btn")
            b.set_tooltip_text(tip)
            b.connect("clicked", cb)
            hdr.pack_start(b, False, False, 0)

        # Error label (click to dismiss)
        self._info_bar_label = Gtk.Label(label="")
        self._info_bar_label.get_style_context().add_class("error-lbl")
        self._info_bar_label.set_line_wrap(True)
        self._info_bar_label.set_xalign(0)
        self._info_bar_label.set_no_show_all(True)
        err_eb = Gtk.EventBox()
        err_eb.add(self._info_bar_label)
        err_eb.connect("button-press-event",
                       lambda *_: self._info_bar_label.hide())
        panel.pack_start(err_eb, False, False, 0)

        # Fake InfoBar shim (recording_controls calls self._info_bar.hide())
        self._info_bar = _InfoBarShim(self._info_bar_label)

        # Action buttons (vertical stack)
        self._button_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        panel.pack_start(self._button_box, False, False, 0)

        # Output paths (shown after cancel+save)
        self._output_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._output_box.set_no_show_all(True)
        self._output_label = Gtk.Label(label="")
        self._output_label.get_style_context().add_class("output-lbl")
        self._output_label.set_line_wrap(True)
        self._output_label.set_xalign(0)
        self._open_folder_btn = Gtk.Button(label="Open Folder")
        self._open_folder_btn.get_style_context().add_class("ctrl-btn")
        self._open_folder_btn.connect("clicked", self._on_open_folder)
        self._output_box.pack_start(self._output_label, False, False, 0)
        self._output_box.pack_start(self._open_folder_btn, False, False, 0)
        panel.pack_start(self._output_box, False, False, 0)

        # Jobs section
        self._jobs_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._jobs_section.set_no_show_all(True)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._jobs_section.pack_start(sep, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(120)
        scroll.set_propagate_natural_height(True)
        self._jobs_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        scroll.add(self._jobs_list)
        self._jobs_section.pack_start(scroll, False, False, 0)
        sep.show()
        scroll.show()
        self._jobs_list.show()

        panel.pack_start(self._jobs_section, False, False, 0)

        # Status label kept as hidden for mixin compatibility
        self._status_label = Gtk.Label()
        self._status_label.set_no_show_all(True)

    # ── Expand / collapse ─────────────────────────────────────────────────

    def _on_pill_click(self, widget, event) -> bool:
        if event.button == 1:
            self._set_expanded(not self._expanded)
        elif event.button == 3:
            self._on_tray_activate()
        return True

    def _set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._revealer.set_reveal_child(expanded)
        ctx = self._pill_bg.get_style_context()
        if expanded:
            ctx.remove_class("pill")
            ctx.add_class("pill-expanded")
        else:
            ctx.remove_class("pill-expanded")
            ctx.add_class("pill")

    # ── State machine ─────────────────────────────────────────────────────

    def _transition(self, new_state: State, **kwargs) -> None:
        assert_main_thread()
        self._state = new_state
        self._update_ui(**kwargs)
        self._notify_tray()

    def _update_ui(self, status: str = "", **kwargs) -> None:
        assert_main_thread()
        for child in self._button_box.get_children():
            self._button_box.remove(child)

        dot_ctx = self._dot.get_style_context()
        for cls in ("dot-idle", "dot-recording", "dot-paused", "dot-processing"):
            dot_ctx.remove_class(cls)

        state = self._state

        def _btn(label, callback, css_class=None):
            b = Gtk.Button(label=label)
            b.get_style_context().add_class("ctrl-btn")
            b.connect("clicked", lambda *_: callback())
            if css_class:
                b.get_style_context().add_class(css_class)
            return b

        if state == State.IDLE:
            dot_ctx.add_class("dot-idle")
            self._timer_label.hide()
            self._output_box.hide()
            self._info_bar_label.hide()
            self._title_entry.set_sensitive(True)

            self._button_box.pack_start(
                _btn("Record (Headphones)", self.on_record_headphones_clicked,
                     "suggested-action"), False, False, 0)
            self._button_box.pack_start(
                _btn("Record (Speaker)", self.on_record_speaker_clicked),
                False, False, 0)
            self._button_box.pack_start(
                _btn("Transcribe File", self.on_transcribe_file_clicked),
                False, False, 0)

        elif state == State.RECORDING:
            dot_ctx.add_class("dot-recording")
            self._timer_label.show()
            self._output_box.hide()
            self._info_bar_label.hide()
            self._title_entry.set_sensitive(False)

            self._button_box.pack_start(
                _btn("Pause", self.on_pause_clicked), False, False, 0)
            self._button_box.pack_start(
                _btn("Stop", self.on_stop_clicked, "destructive-action"),
                False, False, 0)
            self._button_box.pack_start(
                _btn("Cancel + Save", self.on_cancel_save_clicked),
                False, False, 0)
            self._button_box.pack_start(
                _btn("Cancel", self.on_cancel_clicked), False, False, 0)

        elif state == State.PAUSED:
            dot_ctx.add_class("dot-paused")
            self._timer_label.show()
            self._title_entry.set_sensitive(False)

            self._button_box.pack_start(
                _btn("Resume", self.on_resume_clicked, "suggested-action"),
                False, False, 0)
            self._button_box.pack_start(
                _btn("Stop", self.on_stop_clicked, "destructive-action"),
                False, False, 0)
            self._button_box.pack_start(
                _btn("Cancel + Save", self.on_cancel_save_clicked),
                False, False, 0)
            self._button_box.pack_start(
                _btn("Cancel", self.on_cancel_clicked), False, False, 0)

        self._button_box.show_all()

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

    # ── Timer / recording callbacks ────────────────────────────────────────

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

    # ── Error display ─────────────────────────────────────────────────────

    def _show_error(self, msg: str) -> None:
        assert_main_thread()
        logger.error("UI error shown: %s", msg)
        self._info_bar_label.set_text(msg)
        self._info_bar_label.set_selectable(True)
        self._info_bar_label.show()
        self._set_expanded(True)

    def _on_info_bar_response(self, bar, response_id: int) -> None:
        self._info_bar_label.hide()

    # ── Settings / Explorer ────────────────────────────────────────────────

    def _on_settings_clicked(self, *_) -> None:
        from .settings_dialog import SettingsDialog
        nl_available = (hasattr(self, "_nightlight_inhibitor") and
                        self._nightlight_inhibitor.is_available())
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

    def _on_explorer_clicked(self, *_) -> None:
        from .meeting_explorer import MeetingExplorer
        win = Gtk.Window(title="Meetings")
        win.set_default_size(520, 420)
        explorer = MeetingExplorer()
        win.add(explorer)
        win.show_all()
        explorer.refresh()

    # ── Helpers ────────────────────────────────────────────────────────────

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

    def _on_tray_activate(self) -> None:
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
        action = cfg.get("tray_default_action", "record_headphones")
        actions = {
            "record_headphones": self.on_record_headphones_clicked,
            "record_speaker": self.on_record_speaker_clicked,
            "transcribe_file": self.on_transcribe_file_clicked,
        }
        actions.get(action, self.on_record_headphones_clicked)()

    @staticmethod
    def _make_timer_attrs():
        gi.require_version("Pango", "1.0")
        from gi.repository import Pango
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_size_new_absolute(48 * Pango.SCALE))
        return attrs


class _InfoBarShim:
    """Thin shim so mixin code can call self._info_bar.hide()/show()."""

    def __init__(self, label: Gtk.Label) -> None:
        self._label = label

    def hide(self) -> None:
        self._label.hide()

    def show(self) -> None:
        self._label.show()
