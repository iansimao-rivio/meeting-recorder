"""
Mixin for MainWindow: recording lifecycle controls -- start, pause, resume,
stop, cancel, countdown, and API key validation.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ..config import settings
from ..utils.glib_bridge import assert_main_thread, idle_call
from ..utils.filename import output_paths

if TYPE_CHECKING:
    from .main_window import MainWindow, _Job

logger = logging.getLogger(__name__)


class RecordingControlsMixin:
    """Recording lifecycle methods.  Expects ``self`` to be a MainWindow."""

    def on_record_headphones_clicked(self: MainWindow) -> None:
        self._recording_mode = "headphones"
        self._start_recording()

    def on_record_speaker_clicked(self: MainWindow) -> None:
        self._recording_mode = "speaker"
        self._start_recording()

    def _start_recording(self: MainWindow) -> None:
        assert_main_thread()
        from .main_window import State

        if self._state != State.IDLE:
            return
        if not self._audio_backend:
            self._show_error("No audio backend available. Check Settings \u2192 Platform.")
            return

        cfg = settings.load()
        key_missing = self._check_api_keys(
            cfg, cfg.get("transcription_provider", "gemini"),
            cfg.get("summarization_provider", "litellm"))
        if key_missing:
            self._show_error(key_missing); return

        ok, err = self._audio_backend.validate()
        if not ok:
            self._show_error(f"Audio device error: {err}"); return

        title = self._title_entry.get_text().strip() or None
        audio, transcript, notes = output_paths(
            cfg.get("output_folder", "~/meetings"), title)
        self._audio_path, self._transcript_path, self._notes_path = audio, transcript, notes
        # Mark directory as active so the explorer skips it
        (audio.parent / ".recording").touch()

        from ..audio.recorder import Recorder, RecordingError
        from ..config.defaults import RECORDING_QUALITIES
        from ..platform.audio.base import CaptureMode

        q_key = cfg.get("recording_quality", "high")
        _, q_val = RECORDING_QUALITIES.get(q_key, RECORDING_QUALITIES["high"])

        self._recorder = Recorder(
            backend=self._audio_backend, output_dir=audio.parent,
            mode=CaptureMode(self._recording_mode), quality=q_val,
            separate_tracks=cfg.get("separate_audio_tracks", True),
            on_tick=self._on_tick, on_error=self._on_recording_error)
        try:
            self._recorder.start()
        except RecordingError as exc:
            self._show_error(str(exc)); return

        mode_label = "headphones" if self._recording_mode == "headphones" else "speaker"
        self._transition(State.RECORDING, status=f"Recording\u2026 ({mode_label} mode)")

        # Start screen recording in background thread so it doesn't block the GUI
        if cfg.get("screen_recording"):
            import threading
            threading.Thread(
                target=self._try_start_screen_recording,
                args=(cfg, audio.parent), daemon=True,
            ).start()

    def _try_start_screen_recording(self: MainWindow, cfg: dict, out_dir: Path) -> None:
        """Start screen recording. Called from a background thread."""
        # Inhibit night light before starting screen recording for accurate colors
        if cfg.get("inhibit_nightlight", True):
            try:
                self._nightlight_inhibitor.inhibit()
            except Exception as exc:
                logger.warning("Night light inhibit failed: %s", exc)

        if not self._screen_recorder:
            self._nightlight_inhibitor.uninhibit()
            idle_call(self._show_error,
                "Screen recording is enabled but gpu-screen-recorder is not installed.\n"
                "Install it: yay -S gpu-screen-recorder"); return
        if hasattr(self._screen_recorder, "is_available") and not self._screen_recorder.is_available():
            self._nightlight_inhibitor.uninhibit()
            idle_call(self._show_error,
                "Screen recording is enabled but gpu-screen-recorder is not found on PATH.\n"
                "Install it: yay -S gpu-screen-recorder"); return
        try:
            monitors_cfg = cfg.get("monitors", "all")
            if monitors_cfg == "all":
                names = [m.name for m in self._screen_recorder.list_monitors()]
            else:
                names = [m.strip() for m in monitors_cfg.split(",") if m.strip()]
            self._screen_recorder.start(names, out_dir, cfg.get("screen_fps", 30))
        except Exception as exc:
            self._nightlight_inhibitor.uninhibit()
            logger.warning("Screen recording failed to start: %s", exc)
            idle_call(self._show_error, f"Screen recording failed to start: {exc}")

    # -- Transcribe file ----------------------------------------------------

    def on_transcribe_file_clicked(self: MainWindow) -> None:
        assert_main_thread()
        from .main_window import State, _Job

        if self._state != State.IDLE:
            return
        cfg = settings.load()
        key_missing = self._check_api_keys(
            cfg, cfg.get("transcription_provider", "gemini"),
            cfg.get("summarization_provider", "litellm"))
        if key_missing:
            self._show_error(key_missing); return

        dialog = Gtk.FileChooserDialog(
            title="Select Media File", parent=self,
            action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        af = Gtk.FileFilter()
        af.set_name("Media Files")
        af.add_mime_type("audio/*")
        af.add_mime_type("video/*")
        dialog.add_filter(af)

        response = dialog.run()
        filename = dialog.get_filename()
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not filename:
            return

        p = Path(filename)
        job = _Job(job_id=self._next_job_id, audio_path=p,
                   transcript_path=p.parent / f"{p.stem}_transcript.md",
                   notes_path=p.parent / f"{p.stem}_notes.md", label=p.name)
        self._next_job_id += 1
        self._jobs.append(job)
        self._add_job_row(job)
        self._notify_tray()

        def _bg():
            from ..processing.session import MeetingSession
            session = MeetingSession(
                config=cfg,
                audio_path=job.audio_path,
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

    # -- Pause / resume / stop ---------------------------------------------

    def on_pause_clicked(self: MainWindow) -> None:
        assert_main_thread()
        from .main_window import State
        if self._state != State.RECORDING or not self._recorder:
            return
        self._recorder.pause()
        self._transition(State.PAUSED)

    def on_resume_clicked(self: MainWindow) -> None:
        assert_main_thread()
        from .main_window import State
        if self._state != State.PAUSED or not self._recorder:
            return
        self._recorder.resume()
        self._transition(State.RECORDING)

    def on_stop_clicked(self: MainWindow) -> None:
        assert_main_thread()
        from .main_window import State, _Job

        if self._state not in (State.RECORDING, State.PAUSED) or not self._recorder:
            return

        recorder = self._recorder
        self._recorder = None

        # Create job immediately
        job = _Job(
            job_id=self._next_job_id, audio_path=self._audio_path,
            transcript_path=self._transcript_path, notes_path=self._notes_path,
            label=self._make_job_label())
        self._next_job_id += 1

        self._jobs.append(job)
        self._add_job_row(job)
        self._update_job_status_text(job, "Finishing recording\u2026")

        # Transition to IDLE immediately
        self._transition(State.IDLE)

        # Background: stop recorder, then run MeetingSession
        def _bg():
            try:
                self._nightlight_inhibitor.uninhibit()
            except Exception as exc:
                logger.warning("Night light uninhibit failed: %s", exc)
            if self._screen_recorder:
                try:
                    screen_paths = self._screen_recorder.stop()
                    if screen_paths:
                        self._merge_screen_with_audio(screen_paths, job.audio_path)
                except Exception:
                    pass
            try:
                recorder.stop()
            except Exception as exc:
                if not job.cancelled:
                    idle_call(self._on_job_error, job, f"Failed to stop recording: {exc}")
                return

            if job.cancelled:
                return

            from ..processing.session import MeetingSession
            cfg = settings.load()
            session = MeetingSession(
                config=cfg,
                audio_path=job.audio_path,
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

    # -- Cancel variants ---------------------------------------------------

    def on_cancel_save_clicked(self: MainWindow) -> None:
        assert_main_thread()
        from .main_window import State
        if self._state not in (State.RECORDING, State.PAUSED) or not self._recorder:
            return
        recorder = self._recorder
        ap, tp, np_ = self._audio_path, self._transcript_path, self._notes_path
        self._recorder = None
        self._transition(State.IDLE, status="Stopping recording\u2026")

        def _bg():
            try: self._nightlight_inhibitor.uninhibit()
            except Exception as exc: logger.warning("Night light uninhibit failed: %s", exc)
            if self._screen_recorder:
                try: self._screen_recorder.stop()
                except Exception: pass
            try: recorder.stop()
            except Exception as exc:
                idle_call(self._show_error, f"Failed to stop recording: {exc}"); return
            idle_call(_done)

        def _done():
            # Remove lock so the meeting appears in the explorer
            if ap:
                (ap.parent / ".recording").unlink(missing_ok=True)
            self._transition(State.IDLE, status="Recording saved (no transcription).")
            paths = []
            if tp and tp.exists(): paths.append(f"Transcript: {tp}")
            if np_ and np_.exists(): paths.append(f"Notes: {np_}")
            if ap and ap.exists(): paths.append(f"Audio: {ap}")
            if paths:
                self._output_label.set_text("\n".join(paths))
                self._output_box.show_all()

        threading.Thread(target=_bg, daemon=True).start()

    def on_cancel_clicked(self: MainWindow) -> None:
        assert_main_thread()
        from .main_window import State
        if self._state not in (State.RECORDING, State.PAUSED) or not self._recorder:
            return
        recorder = self._recorder
        audio_path = self._audio_path
        self._recorder = None
        self._transition(State.IDLE, status="Cancelling\u2026")

        def _bg():
            try: self._nightlight_inhibitor.uninhibit()
            except Exception as exc: logger.warning("Night light uninhibit failed: %s", exc)
            if self._screen_recorder:
                try: self._screen_recorder.stop()
                except Exception: pass
            try: recorder.stop()
            except Exception as exc:
                idle_call(self._show_error, f"Failed to stop recording: {exc}"); return
            if audio_path:
                d = audio_path.parent
                # Clean up all files in the session dir (audio, lock, segments)
                if d.is_dir():
                    for f in d.iterdir():
                        try: f.unlink()
                        except Exception: pass
                    try: d.rmdir()
                    except Exception: pass
            idle_call(self._transition, State.IDLE)

        threading.Thread(target=_bg, daemon=True).start()

    # -- Background helpers ------------------------------------------------

    @staticmethod
    def _merge_screen_with_audio(video_paths: list[Path], audio_path: Path) -> None:
        """Merge each screen recording mp4 with the combined audio track."""
        for vpath in video_paths:
            if not vpath.exists():
                continue
            merged = vpath.with_name(vpath.stem + "_merged.mp4")
            cmd = ["ffmpeg", "-y", "-i", str(vpath), "-i", str(audio_path),
                   "-c:v", "copy", "-c:a", "aac", "-shortest", str(merged)]
            try:
                subprocess.run(cmd, capture_output=True, timeout=300)
                if merged.exists() and merged.stat().st_size > 0:
                    logger.info("Merged screen+audio: %s", merged)
                else:
                    logger.warning("Merge produced empty file: %s", merged)
            except Exception as exc:
                logger.warning("Failed to merge %s with audio: %s", vpath.name, exc)

    def _make_job_label(self: MainWindow) -> str:
        time_part = self._audio_path.parent.name if self._audio_path else "recording"
        title = self._title_entry.get_text().strip()
        return f"{time_part} {title}".strip() if title else time_part

    # -- API key validation ------------------------------------------------

    @staticmethod
    def _has_key(cfg: dict, env_name: str) -> bool:
        """Check if API key is available in config or environment."""
        from ..utils.api_keys import has_api_key
        return has_api_key(cfg, env_name)

    def _check_api_keys(self: MainWindow, cfg: dict, ts: str, ss: str) -> str | None:
        from ..utils.api_keys import check_api_keys
        return check_api_keys(cfg, ts, ss)
