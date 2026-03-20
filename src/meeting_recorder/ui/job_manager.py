"""
Mixin for MainWindow that provides background job management:
running the pipeline, tracking job status, and the jobs panel UI.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from ..config import settings
from ..utils.glib_bridge import assert_main_thread, idle_call

if TYPE_CHECKING:
    from .main_window import MainWindow, _Job

logger = logging.getLogger(__name__)

_JOB_EXPIRY = timedelta(hours=24)


class JobManagerMixin:
    """Job pipeline and UI methods. Expects `self` to be a MainWindow."""

    # -- Job lifecycle callbacks -------------------------------------------

    @staticmethod
    def _remove_recording_lock(job: _Job) -> None:
        """Remove .recording lock file so the meeting appears in the explorer."""
        if job.audio_path:
            lock = job.audio_path.parent / ".recording"
            lock.unlink(missing_ok=True)

    def _on_session_done(self: MainWindow, job: _Job, result) -> None:
        """Called when MeetingSession completes. Updates job from SessionResult."""
        assert_main_thread()
        from ..processing.session import SessionResult
        if isinstance(result, SessionResult):
            job.audio_path = result.audio_path
            job.transcript_path = result.transcript_path
            job.notes_path = result.notes_path
            if result.title:
                job.label = result.audio_path.parent.name
                widgets = self._job_widgets.get(job.job_id)
                if widgets:
                    widgets["job_name_label"].set_text(job.label)
        self._remove_recording_lock(job)
        job.status = "done"
        self._update_job_row(job)
        self._notify_tray()
        self._send_job_complete_notification(job)

    def _on_job_error(self: MainWindow, job: _Job, msg: str) -> None:
        assert_main_thread()
        self._remove_recording_lock(job)
        job.status = "error"
        job.error_msg = msg
        self._update_job_row(job)
        self._notify_tray()

    def _on_cancel_job(self: MainWindow, job: _Job) -> None:
        assert_main_thread()
        job.cancelled = True
        self._remove_recording_lock(job)
        self._dismiss_job(job)
        logger.info("Job %d cancelled by user", job.job_id)

    def _on_retry_job(self: MainWindow, job: _Job) -> None:
        assert_main_thread()
        job.status = "processing"
        job.error_msg = None
        job.cancelled = False
        self._update_job_row(job)
        self._notify_tray()

        def _bg():
            from ..processing.session import MeetingSession
            cfg = settings.load()
            session = MeetingSession(
                config=cfg,
                source_path=job.source_path,
                audio_path=job.audio_path if job.source_path is None else None,
                on_status=lambda msg: (
                    idle_call(self._update_job_status_text, job, msg)
                    if not job.cancelled else None
                ),
                on_done=lambda result: (
                    idle_call(self._on_session_done, job, result)
                    if not job.cancelled else None
                ),
                on_error=lambda err: (
                    idle_call(self._on_job_error, job, err)
                    if not job.cancelled else None
                ),
            )
            session.run()

        threading.Thread(target=_bg, daemon=True).start()

    def _on_open_job_folder(self: MainWindow, job: _Job) -> None:
        if not job.audio_path:
            return
        try:
            subprocess.Popen(["xdg-open", str(job.audio_path.parent)])
        except Exception:
            pass

    def _dismiss_job(self: MainWindow, job: _Job) -> None:
        assert_main_thread()
        widgets = self._job_widgets.pop(job.job_id, None)
        if widgets:
            row = widgets.get("row")
            if row and row in self._jobs_list.get_children():
                self._jobs_list.remove(row)
        if job in self._jobs:
            self._jobs.remove(job)
        if not self._jobs:
            self._jobs_section.hide()
        self._notify_tray()

    # -- Jobs panel UI -----------------------------------------------------

    def _add_job_row(self: MainWindow, job: _Job) -> None:
        """Add a row for a new job to the jobs panel. Main thread only."""
        assert_main_thread()

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_top(2)
        row.set_margin_bottom(2)

        spinner = Gtk.Spinner()
        spinner.start()
        row.pack_start(spinner, False, False, 0)

        status_icon = Gtk.Image.new_from_icon_name("system-run", Gtk.IconSize.BUTTON)
        status_icon.set_no_show_all(True)
        row.pack_start(status_icon, False, False, 0)

        label_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        job_name_label = Gtk.Label(label=job.label)
        job_name_label.set_xalign(0)
        status_label = Gtk.Label(label="Processing\u2026")
        status_label.set_xalign(0)
        label_box.pack_start(job_name_label, False, False, 0)
        label_box.pack_start(status_label, False, False, 0)
        row.pack_start(label_box, True, True, 0)

        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        row.pack_end(action_box, False, False, 0)

        self._job_widgets[job.job_id] = {
            "row": row,
            "spinner": spinner,
            "status_icon": status_icon,
            "job_name_label": job_name_label,
            "status_label": status_label,
            "action_box": action_box,
        }
        self._rebuild_action_box(job)

        self._jobs_list.pack_start(row, False, False, 0)
        self._jobs_list.reorder_child(row, 0)  # newest at top
        self._jobs_section.show()
        row.show_all()
        status_icon.hide()
        self._ensure_expiry_timer()

    def _update_job_row(self: MainWindow, job: _Job) -> None:
        """Refresh icon, status text, and action buttons for a status change."""
        assert_main_thread()
        widgets = self._job_widgets.get(job.job_id)
        if not widgets:
            return

        spinner: Gtk.Spinner = widgets["spinner"]
        status_icon: Gtk.Image = widgets["status_icon"]
        status_label: Gtk.Label = widgets["status_label"]

        spinner.stop()
        spinner.hide()
        status_icon.show()

        if job.status == "done":
            status_icon.set_from_icon_name("emblem-ok-symbolic", Gtk.IconSize.BUTTON)
            status_label.set_text(self._build_done_text(job))
        elif job.status == "error":
            status_icon.set_from_icon_name("dialog-error", Gtk.IconSize.BUTTON)
            err = (job.error_msg or "Error")[:60]
            status_label.set_text(f"Error: {err}")

        self._rebuild_action_box(job)

    @staticmethod
    def _build_done_text(job: _Job) -> str:
        """Build a status string like 'Done · Mar 18, 2:30 PM · 23m'."""
        from datetime import datetime
        from ..utils.meeting_scanner import _probe_audio_duration
        parts = ["Done"]
        now = datetime.now()
        parts.append(now.strftime("%b %d, %I:%M %p").replace(" 0", " ").lstrip("0"))
        audio = job.audio_path
        if audio and audio.exists():
            dur = _probe_audio_duration(audio)
            if dur is not None:
                if dur >= 3600:
                    parts.append(f"{dur // 3600}h {(dur % 3600) // 60}m")
                else:
                    parts.append(f"{dur // 60}m")
        return " \u00b7 ".join(parts)

    def _rebuild_action_box(self: MainWindow, job: _Job) -> None:
        """Replace the action buttons in the job row for the current status."""
        widgets = self._job_widgets.get(job.job_id)
        if not widgets:
            return
        action_box: Gtk.Box = widgets["action_box"]
        for child in action_box.get_children():
            action_box.remove(child)

        if job.status == "processing":
            btn = Gtk.Button(label="Cancel")
            btn.connect("clicked", lambda *_, j=job: self._on_cancel_job(j))
            action_box.pack_start(btn, False, False, 0)
        elif job.status == "done":
            btn = Gtk.Button(label="Open Folder")
            btn.connect("clicked", lambda *_, j=job: self._on_open_job_folder(j))
            action_box.pack_start(btn, False, False, 0)
            action_box.pack_start(self._make_dismiss_btn(job), False, False, 0)
        elif job.status == "error":
            btn = Gtk.Button(label="Retry")
            btn.connect("clicked", lambda *_, j=job: self._on_retry_job(j))
            action_box.pack_start(btn, False, False, 0)
            action_box.pack_start(self._make_dismiss_btn(job), False, False, 0)

        action_box.show_all()

    def _make_dismiss_btn(self: MainWindow, job: _Job) -> Gtk.Button:
        btn = Gtk.Button()
        btn.set_image(
            Gtk.Image.new_from_icon_name("window-close", Gtk.IconSize.BUTTON)
        )
        btn.set_tooltip_text("Dismiss")
        btn.connect("clicked", lambda *_, j=job: self._dismiss_job(j))
        return btn

    def _update_job_status_text(self: MainWindow, job: _Job, msg: str) -> None:
        """Update the status text for a job (pipeline progress). Main thread only."""
        assert_main_thread()
        widgets = self._job_widgets.get(job.job_id)
        if widgets:
            widgets["status_label"].set_text(msg)

    # -- Job expiry (24 h) -------------------------------------------------

    _expiry_timer_id: int | None = None

    def _ensure_expiry_timer(self: MainWindow) -> None:
        """Start the periodic expiry check if not already running."""
        if self._expiry_timer_id is not None:
            return
        # Check every 60 seconds
        self._expiry_timer_id = GLib.timeout_add_seconds(60, self._expire_old_jobs)

    def _expire_old_jobs(self: MainWindow) -> bool:
        """Remove jobs older than 24 hours. Returns True to keep the timer alive."""
        now = datetime.now()
        expired = [j for j in self._jobs if now - j.created_at >= _JOB_EXPIRY]
        for job in expired:
            self._dismiss_job(job)
        if not self._jobs:
            self._expiry_timer_id = None
            return False  # stop timer when no jobs remain
        return True
