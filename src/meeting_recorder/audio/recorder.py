"""Recording thread: ffmpeg subprocess lifecycle, pause/resume."""

from __future__ import annotations

import logging
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from .devices import get_default_source, get_default_sink, get_monitor_source
from .mixer import build_ffmpeg_command, build_ffmpeg_command_mic_only

logger = logging.getLogger(__name__)


class RecordingError(Exception):
    pass


class Recorder:
    """
    Manages the full recording lifecycle.

    Usage:
        r = Recorder(output_path, on_tick=..., on_error=...)
        r.start()
        r.pause()
        r.resume()
        r.stop()   # blocks until ffmpeg exits
    """

    def __init__(
        self,
        output_path: Path,
        mode: str = "headphones",
        on_tick: Callable[[int], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._output_path = output_path
        self._mode = mode  # "headphones" = mic + monitor; "speaker" = mic only
        self._on_tick = on_tick
        self._on_error = on_error

        self._ffmpeg: subprocess.Popen | None = None

        self._timer_thread: threading.Thread | None = None
        self._elapsed: int = 0  # seconds
        self._paused = False
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start recording. Raises RecordingError on failure."""
        mic_source = get_default_source()
        if not mic_source:
            raise RecordingError("No microphone found. Check audio setup.")

        if self._mode == "speaker":
            cmd = build_ffmpeg_command_mic_only(mic_source, self._output_path)
        else:
            sink = get_default_sink()
            if not sink:
                raise RecordingError("No audio output device found. Check audio setup.")
            monitor_source = get_monitor_source(sink)
            cmd = build_ffmpeg_command(mic_source, monitor_source, self._output_path)
        try:
            self._ffmpeg = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            raise RecordingError("ffmpeg not found. Please install ffmpeg.")

        self._stop_event.clear()
        self._paused = False
        self._elapsed = 0
        self._timer_thread = threading.Thread(
            target=self._timer_loop, daemon=True
        )
        self._timer_thread.start()

        threading.Thread(target=self._monitor_ffmpeg, daemon=True).start()

        logger.info("Recording started → %s", self._output_path)

    def pause(self) -> None:
        """Pause recording by sending SIGSTOP to ffmpeg."""
        with self._lock:
            if self._paused:
                return
            self._paused = True
        if self._ffmpeg and self._ffmpeg.poll() is None:
            try:
                self._ffmpeg.send_signal(signal.SIGSTOP)
            except ProcessLookupError:
                pass
        logger.info("Recording paused")

    def resume(self) -> None:
        """Resume recording by sending SIGCONT to ffmpeg."""
        with self._lock:
            if not self._paused:
                return
            self._paused = False
        if self._ffmpeg and self._ffmpeg.poll() is None:
            try:
                self._ffmpeg.send_signal(signal.SIGCONT)
            except ProcessLookupError:
                pass
        logger.info("Recording resumed")

    def stop(self) -> None:
        """Stop recording gracefully. Waits for ffmpeg to finish."""
        logger.info("Stopping recording...")
        self._stop_event.set()

        # Resume ffmpeg before terminating: a SIGSTOP'd process can't receive SIGTERM.
        if self._paused and self._ffmpeg and self._ffmpeg.poll() is None:
            try:
                self._ffmpeg.send_signal(signal.SIGCONT)
            except ProcessLookupError:
                pass

        if self._ffmpeg and self._ffmpeg.poll() is None:
            self._ffmpeg.terminate()
            try:
                self._ffmpeg.wait(timeout=30)
            except subprocess.TimeoutExpired:
                logger.warning("ffmpeg did not exit in time; killing")
                self._ffmpeg.kill()
                self._ffmpeg.wait()

        if self._timer_thread:
            self._timer_thread.join(timeout=2)

        self._ffmpeg = None
        logger.info("Recording stopped. File: %s", self._output_path)

    @property
    def elapsed(self) -> int:
        return self._elapsed

    @property
    def is_paused(self) -> bool:
        return self._paused

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _timer_loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(1)
            if not self._stop_event.is_set():
                with self._lock:
                    paused = self._paused
                if not paused:
                    self._elapsed += 1
                    if self._on_tick:
                        self._on_tick(self._elapsed)

    def _monitor_ffmpeg(self) -> None:
        """Watch for unexpected ffmpeg exit and report error."""
        if not self._ffmpeg:
            return
        retcode = self._ffmpeg.wait()
        if not self._stop_event.is_set() and retcode != 0:
            stderr = b""
            if self._ffmpeg.stderr:
                stderr = self._ffmpeg.stderr.read()
            msg = f"ffmpeg exited unexpectedly (code {retcode}): {stderr.decode(errors='replace')}"
            logger.error(msg)
            if self._on_error:
                self._on_error(msg)
            self._stop_event.set()
