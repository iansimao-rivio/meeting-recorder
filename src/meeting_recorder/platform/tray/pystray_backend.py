from __future__ import annotations

import logging
import threading

from .base import TrayBackend

logger = logging.getLogger(__name__)

# Colors
_PURPLE = (108, 92, 231)           # #6c5ce7
_LAVENDER = (162, 155, 254)        # #a29bfe
_DARK_BG = (26, 26, 46)           # #1a1a2e
_TEAL = (0, 206, 201)             # #00cec9
_GOLD = (253, 203, 110)           # #fdcb6e
_DARK_PURPLE = (72, 52, 212)      # #4834d4
_BELLY_IDLE = (162, 155, 254, 90) # lavender, low alpha
_BELLY_REC = (229, 57, 53)        # #E53935
_BELLY_REC_DIM = (93, 22, 22)     # #5D1616
_BELLY_PROC = (253, 216, 53)      # #FDD835
_BELLY_PROC_DIM = (125, 106, 16)  # #7D6A10


def _draw_cat_icon(size: int = 64, belly_color: tuple | None = None):
    """Draw the cat mascot tray icon with belly indicator."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size / 64  # scale factor

    # Tail
    _draw_curve(draw, [(17, 52), (8, 50), (7, 42), (6, 36), (10, 34)], _PURPLE, s, 2.5)

    # Body
    _cx, _cy = int(32 * s), int(44 * s)
    _rx, _ry = int(16 * s), int(14 * s)
    draw.ellipse([_cx - _rx, _cy - _ry, _cx + _rx, _cy + _ry], fill=_PURPLE)

    # Belly (indicator zone)
    bx, by = int(32 * s), int(47 * s)
    brx, bry = int(10 * s), int(9 * s)
    if belly_color:
        draw.ellipse([bx - brx, by - bry, bx + brx, by + bry], fill=belly_color)
    else:
        draw.ellipse([bx - brx, by - bry, bx + brx, by + bry], fill=_BELLY_IDLE)

    # Head
    hx, hy, hr = int(32 * s), int(26 * s), int(13 * s)
    draw.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=_PURPLE)

    # Ears
    draw.polygon([_p(22, s), _p(18, 5, s), _p(26, 14, s)], fill=_PURPLE)
    draw.polygon([_p(42, s), _p(46, 5, s), _p(38, 14, s)], fill=_PURPLE)
    # Inner ears
    draw.polygon([_p(23, 17, s), _p(20, 8, s), _p(25, 14, s)], fill=_LAVENDER + (102,))
    draw.polygon([_p(41, 17, s), _p(44, 8, s), _p(39, 14, s)], fill=_LAVENDER + (102,))

    # Eyes
    for ex in [27, 37]:
        ecx, ecy = int(ex * s), int(25 * s)
        erx, ery = int(4 * s), int(4.5 * s)
        draw.ellipse([ecx - erx, ecy - ery, ecx + erx, ecy + ery], fill=_DARK_BG)
        irx, iry = int(1.5 * s), int(3.5 * s)
        draw.ellipse([ecx - irx, ecy - iry, ecx + irx, ecy + iry], fill=_TEAL)
        prx, pry = int(0.6 * s) or 1, int(3 * s)
        draw.ellipse([ecx - prx, ecy - pry, ecx + prx, ecy + pry], fill=_DARK_BG)

    # Nose
    nx = int(32 * s)
    draw.polygon(
        [(int(30.5 * s), int(29 * s)), (int(33.5 * s), int(29 * s)),
         (nx, int(31 * s))],
        fill=_DARK_PURPLE,
    )

    # Headphone band
    _draw_curve(draw, [(19, 22), (19, 10), (32, 7), (45, 10), (45, 22)], _GOLD, s, 2.5)

    # Headphone cups
    for cx in [14, 43]:
        x0, y0 = int(cx * s), int(20 * s)
        w, h = int(7 * s), int(9 * s)
        draw.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=int(3 * s), fill=_GOLD)

    # Mini notepad
    nx0, ny0 = int(46 * s), int(38 * s)
    nw, nh = int(10 * s), int(13 * s)
    draw.rounded_rectangle([nx0, ny0, nx0 + nw, ny0 + nh],
                           radius=max(1, int(1.5 * s)), fill=(255, 255, 255, 204))
    lw = max(1, int(1 * s))
    draw.line([int(48 * s), int(42 * s), int(55 * s), int(42 * s)],
              fill=_PURPLE, width=lw)
    draw.line([int(48 * s), int(45 * s), int(54 * s), int(45 * s)],
              fill=_PURPLE + (128,), width=lw)

    return img


def _p(*coords_and_scale):
    """Helper: scale coordinate pairs. _p(x, y, s) or _p(x_as_ear, s)."""
    if len(coords_and_scale) == 2:
        x, s = coords_and_scale
        return (int(x * s), int(18 * s))  # ear default y
    x, y, s = coords_and_scale
    return (int(x * s), int(y * s))


def _draw_curve(draw, points, color, s, width):
    """Draw connected line segments as a simple curve approximation."""
    scaled = [(int(x * s), int(y * s)) for x, y in points]
    w = max(1, int(width * s))
    for i in range(len(scaled) - 1):
        draw.line([scaled[i], scaled[i + 1]], fill=color, width=w)


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
        self._icon_idle = _draw_cat_icon()
        self._icon_rec_bright = _draw_cat_icon(belly_color=_BELLY_REC)
        self._icon_rec_dim = _draw_cat_icon(belly_color=_BELLY_REC_DIM)
        self._icon_proc_bright = _draw_cat_icon(belly_color=_BELLY_PROC)
        self._icon_proc_dim = _draw_cat_icon(belly_color=_BELLY_PROC_DIM)

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
