from __future__ import annotations

import logging
import threading

from .base import TrayBackend

logger = logging.getLogger(__name__)

# Colors
_MIC_COLOR = (220, 220, 220)
_DOT_RED = (229, 57, 53)
_DOT_MAROON = (93, 22, 22)
_DOT_YELLOW = (253, 216, 53)       # #FDD835
_DOT_DARK_YELLOW = (93, 85, 22)    # #5D5516


def _draw_mic_icon(size: int = 64, dot_color: tuple | None = None):
    """Draw a microphone tray icon with optional recording dot."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size / 64  # scale factor

    # Mic capsule (rounded rect)
    draw.rounded_rectangle(
        [int(21 * s), int(5 * s), int(43 * s), int(33 * s)],
        radius=int(11 * s),
        fill=_MIC_COLOR,
    )

    # Holder arc (U-shape under capsule)
    # Draw as the bottom half of an ellipse
    bbox = [int(15 * s), int(12 * s), int(49 * s), int(50 * s)]
    draw.arc(bbox, start=0, end=180, fill=_MIC_COLOR, width=max(1, int(4.5 * s)))

    # Stem (short vertical line from arc bottom to base)
    cx = int(32 * s)
    draw.line(
        [cx, int(50 * s), cx, int(55 * s)],
        fill=_MIC_COLOR, width=max(1, int(4.5 * s)),
    )

    # Base (horizontal line)
    draw.line(
        [int(23 * s), int(58 * s), int(41 * s), int(58 * s)],
        fill=_MIC_COLOR, width=max(1, int(4.5 * s)),
    )

    # Recording dot overlay
    if dot_color:
        r = int(10 * s)
        cx_dot, cy_dot = int(52 * s), int(52 * s)
        draw.ellipse(
            [cx_dot - r, cy_dot - r, cx_dot + r, cy_dot + r],
            fill=dot_color,
        )

    return img


class PystrayBackend(TrayBackend):
    """pystray fallback implementation with recording dot blink."""

    def __init__(self, window) -> None:
        super().__init__()
        import pystray

        self._window = window
        self._recording_state = "idle"
        self._jobs: list = []
        self._pystray = pystray

        # Pre-render icon variants
        self._icon_idle = _draw_mic_icon()
        self._icon_rec_bright = _draw_mic_icon(dot_color=_DOT_RED)
        self._icon_rec_dim = _draw_mic_icon(dot_color=_DOT_MAROON)
        self._icon_proc_bright = _draw_mic_icon(dot_color=_DOT_YELLOW)
        self._icon_proc_dim = _draw_mic_icon(dot_color=_DOT_DARK_YELLOW)

        self._blink_on = True
        self._blink_mode = "recording"
        self._blink_timer: threading.Timer | None = None

        self._icon = pystray.Icon(
            "meeting-recorder",
            self._icon_idle,
            "Meeting Recorder",
            menu=self._build_menu(),
        )
        threading.Thread(target=self._icon.run, daemon=True).start()

    def _build_menu(self):
        import pystray
        from ...utils.glib_bridge import idle_call
        from ...config import settings

        state = self._recording_state
        jobs = self._jobs
        cfg = settings.load()
        items = []

        _ACTION_MAP = {
            "record_headphones": (
                "Record (Headphones)",
                lambda *_: idle_call(self._window.on_record_headphones_clicked),
            ),
            "record_speaker": (
                "Record (Speaker)",
                lambda *_: idle_call(self._window.on_record_speaker_clicked),
            ),
            "transcribe_file": (
                "Transcribe File",
                lambda *_: idle_call(self._window.on_transcribe_file_clicked),
            ),
        }
        _REC_ACTION_MAP = {
            "stop": (
                "Stop Recording",
                lambda *_: idle_call(self._window.on_stop_clicked),
            ),
            "pause": (
                "Pause Recording",
                lambda *_: idle_call(self._window.on_pause_clicked),
            ),
            "cancel_save": (
                "Cancel (save recording)",
                lambda *_: idle_call(self._window.on_cancel_save_clicked),
            ),
            "cancel_discard": (
                "Cancel",
                lambda *_: idle_call(self._window.on_cancel_clicked),
            ),
        }

        if state == "idle":
            default_action = cfg.get("tray_default_action", "record_headphones")
            def_label, def_cb = _ACTION_MAP.get(
                default_action, _ACTION_MAP["record_headphones"]
            )
            items.append(pystray.MenuItem(def_label, def_cb, default=True))
            items.append(pystray.MenuItem(
                "Record (Headphones)",
                lambda *_: idle_call(self._window.on_record_headphones_clicked),
            ))
            items.append(pystray.MenuItem(
                "Record (Speaker)",
                lambda *_: idle_call(self._window.on_record_speaker_clicked),
            ))
            items.append(pystray.MenuItem(
                "Transcribe File",
                lambda *_: idle_call(self._window.on_transcribe_file_clicked),
            ))
        elif state == "recording":
            recording_action = cfg.get("tray_recording_action", "stop")
            def_label, def_cb = _REC_ACTION_MAP.get(
                recording_action, _REC_ACTION_MAP["stop"]
            )
            items.append(pystray.MenuItem(def_label, def_cb, default=True))
            items.append(pystray.MenuItem(
                "Pause Recording",
                lambda *_: idle_call(self._window.on_pause_clicked),
            ))
            items.append(pystray.MenuItem(
                "Stop Recording",
                lambda *_: idle_call(self._window.on_stop_clicked),
            ))
            items.append(pystray.MenuItem(
                "Cancel (save recording)",
                lambda *_: idle_call(self._window.on_cancel_save_clicked),
            ))
            items.append(pystray.MenuItem(
                "Cancel",
                lambda *_: idle_call(self._window.on_cancel_clicked),
            ))
        elif state == "paused":
            items.append(pystray.MenuItem(
                "Resume Recording",
                lambda *_: idle_call(self._window.on_resume_clicked),
                default=True,
            ))
            items.append(pystray.MenuItem(
                "Resume Recording",
                lambda *_: idle_call(self._window.on_resume_clicked),
            ))
            items.append(pystray.MenuItem(
                "Stop Recording",
                lambda *_: idle_call(self._window.on_stop_clicked),
            ))
            items.append(pystray.MenuItem(
                "Cancel (save recording)",
                lambda *_: idle_call(self._window.on_cancel_save_clicked),
            ))
            items.append(pystray.MenuItem(
                "Cancel",
                lambda *_: idle_call(self._window.on_cancel_clicked),
            ))

        if jobs:
            items.append(pystray.MenuItem(
                f"Processing ({len(jobs)} active)", lambda *_: None, enabled=False
            ))
            for label, cancel_fn in jobs:
                items.append(pystray.MenuItem(f"  Cancel: {label}", cancel_fn))

        items.append(pystray.MenuItem(
            "Open Meetings Folder", lambda *_: self._on_open_meetings_folder()
        ))
        items.append(pystray.MenuItem(
            "Show Window", lambda *_: idle_call(self._window.present)
        ))
        items.append(pystray.MenuItem("Quit", lambda *_: self._do_quit()))

        return pystray.Menu(*items)

    def _on_open_meetings_folder(self) -> None:
        import os, subprocess
        from ...config import settings
        folder = os.path.expanduser(settings.load().get("output_folder", "~/meetings"))
        try:
            subprocess.Popen(["xdg-open", folder])
        except Exception:
            pass

    def _do_quit(self) -> None:
        from ...utils.glib_bridge import idle_call
        def _quit():
            if self._window._recorder:
                self._window._recorder.stop()
            self._window.get_application().quit()
        idle_call(_quit)

    def update(self, recording_state: str, jobs: list) -> None:
        self._recording_state = recording_state
        self._jobs = jobs
        self._icon.menu = self._build_menu()
        self._icon.update_menu()

        # Stop existing blink timer
        if self._blink_timer is not None:
            self._blink_timer.cancel()
            self._blink_timer = None

        if recording_state in ("recording", "paused"):
            self._blink_mode = "recording"
            self._blink_on = True
            self._icon.icon = self._icon_rec_bright
            self._schedule_blink()
        elif recording_state == "idle" and bool(jobs):
            self._blink_mode = "processing"
            self._blink_on = True
            self._icon.icon = self._icon_proc_bright
            self._schedule_blink()
        else:
            self._icon.icon = self._icon_idle

    def _schedule_blink(self) -> None:
        self._blink_timer = threading.Timer(0.7, self._blink_tick)
        self._blink_timer.daemon = True
        self._blink_timer.start()

    def _blink_tick(self) -> None:
        if self._blink_mode == "recording":
            if self._recording_state not in ("recording", "paused"):
                return
            self._blink_on = not self._blink_on
            self._icon.icon = self._icon_rec_bright if self._blink_on else self._icon_rec_dim
        else:  # processing
            if self._recording_state != "idle" or not bool(self._jobs):
                return
            self._blink_on = not self._blink_on
            self._icon.icon = self._icon_proc_bright if self._blink_on else self._icon_proc_dim
        self._schedule_blink()
