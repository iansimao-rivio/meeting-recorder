from __future__ import annotations

import logging
from pathlib import Path

from .base import TrayBackend

logger = logging.getLogger(__name__)

_ICONS_DIR = str(Path(__file__).resolve().parent.parent.parent / "assets" / "icons")

_INDICATOR_LIB = None
try:
    import gi
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3
    _INDICATOR_LIB = AyatanaAppIndicator3
except (ImportError, ValueError):
    pass

if _INDICATOR_LIB is None:
    try:
        import gi
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as AyatanaAppIndicator3
        _INDICATOR_LIB = AyatanaAppIndicator3
    except (ImportError, ValueError):
        pass

if _INDICATOR_LIB is None:
    raise ImportError("Neither AyatanaAppIndicator3 nor AppIndicator3 is available")


class AppIndicatorTray(TrayBackend):
    """AyatanaAppIndicator3-based tray implementation."""

    def __init__(self, window) -> None:
        super().__init__()
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk

        self._window = window
        self._Gtk = Gtk
        self._recording_state = "idle"
        self._jobs: list = []

        self._blink_timer_id = None
        self._blink_on = True
        self._blink_mode = "recording"

        self._indicator = _INDICATOR_LIB.Indicator.new(
            "meeting-recorder",
            "meeting-recorder",
            _INDICATOR_LIB.IndicatorCategory.APPLICATION_STATUS,
        )
        self._indicator.set_icon_theme_path(_ICONS_DIR)
        self._indicator.set_status(_INDICATOR_LIB.IndicatorStatus.ACTIVE)
        self._menu = Gtk.Menu()
        self._build_menu()

        # Hook into KDE's StatusNotifierItem Activate (left-click) via DBus
        self._hook_sni_activate()

    def _hook_sni_activate(self) -> None:
        """Register a DBus filter to intercept StatusNotifierItem Activate calls.

        On KDE Plasma (SNI protocol), left-click sends an Activate(x, y) method
        call over DBus. AppIndicator3 does not expose this as a GObject signal,
        so we intercept it at the DBus level to trigger our on_activate callback.
        """
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio

            bus = Gio.bus_get_sync(Gio.BusType.SESSION)

            def _on_dbus_message(connection, message):
                if (
                    message.get_message_type() == Gio.DBusMessageType.METHOD_CALL
                    and message.get_member() == "Activate"
                    and "StatusNotifierItem" in (message.get_interface() or "")
                ):
                    cb = self._on_activate
                    if cb is not None:
                        from gi.repository import GLib
                        GLib.idle_add(cb)
                    # Don't block — let AppIndicator handle it too (opens menu)
                return False  # False = don't filter out the message

            bus.add_filter(_on_dbus_message)
            logger.debug("Hooked SNI Activate via DBus filter")
        except Exception as exc:
            logger.debug("Could not hook SNI Activate: %s", exc)

    def _add_bold_item(self, label: str, callback) -> None:
        """Add a menu item with bold Pango markup to indicate default action."""
        from gi.repository import Gtk
        item = Gtk.MenuItem()
        lbl = Gtk.Label()
        lbl.set_markup(f"<b>{label}</b>")
        lbl.set_xalign(0)
        item.add(lbl)
        item.connect("activate", lambda *_: callback())
        self._menu.append(item)
        return item

    def _build_menu(self) -> None:
        from gi.repository import Gtk
        from ...config import settings
        for child in self._menu.get_children():
            self._menu.remove(child)

        state = self._recording_state
        jobs = self._jobs
        cfg = settings.load()

        _ACTION_MAP = {
            "record_headphones": ("Record (Headphones)", self._on_start_headphones),
            "record_speaker": ("Record (Speaker)", self._on_start_speaker),
            "transcribe_file": ("Transcribe File", self._on_transcribe_file),
        }
        _REC_ACTION_MAP = {
            "stop": ("Stop Recording", self._on_stop),
            "pause": ("Pause Recording", self._on_pause),
            "cancel_save": ("Cancel (save recording)", self._on_cancel_save),
            "cancel_discard": ("Cancel", self._on_cancel),
        }

        if state == "idle":
            default_action = cfg.get("tray_default_action", "record_headphones")
            def_label, def_cb = _ACTION_MAP.get(
                default_action, _ACTION_MAP["record_headphones"]
            )
            default_item = self._add_bold_item(def_label, def_cb)
            self._indicator.set_secondary_activate_target(default_item)
            # Add all three options (including the default one again as normal text)
            self._add_item("Record (Headphones)", self._on_start_headphones)
            self._add_item("Record (Speaker)", self._on_start_speaker)
            self._add_item("Transcribe File", self._on_transcribe_file)
        elif state == "recording":
            recording_action = cfg.get("tray_recording_action", "stop")
            def_label, def_cb = _REC_ACTION_MAP.get(
                recording_action, _REC_ACTION_MAP["stop"]
            )
            default_item = self._add_bold_item(def_label, def_cb)
            self._indicator.set_secondary_activate_target(default_item)
            self._add_item("Pause Recording", self._on_pause)
            self._add_item("Stop Recording", self._on_stop)
            self._add_item("Cancel (save recording)", self._on_cancel_save)
            self._add_item("Cancel", self._on_cancel)
        elif state == "paused":
            default_item = self._add_bold_item("Resume Recording", self._on_resume)
            self._indicator.set_secondary_activate_target(default_item)
            self._add_item("Resume Recording", self._on_resume)
            self._add_item("Stop Recording", self._on_stop)
            self._add_item("Cancel (save recording)", self._on_cancel_save)
            self._add_item("Cancel", self._on_cancel)

        if jobs:
            self._menu.append(Gtk.SeparatorMenuItem())
            header = Gtk.MenuItem(label=f"Processing ({len(jobs)} active)")
            header.set_sensitive(False)
            self._menu.append(header)
            for label, cancel_fn in jobs:
                self._add_item(f"  Cancel: {label}", cancel_fn)

        self._menu.append(Gtk.SeparatorMenuItem())
        self._add_item("Open Meetings Folder", self._on_open_meetings_folder)
        self._add_item("Show Window", self._on_show)
        self._add_item("Quit", self._on_quit)

        self._menu.show_all()
        self._indicator.set_menu(self._menu)

    def _add_item(self, label: str, callback) -> None:
        from gi.repository import Gtk
        item = Gtk.MenuItem(label=label)
        item.connect("activate", lambda *_: callback())
        self._menu.append(item)

    def update(self, recording_state: str, jobs: list) -> None:
        self._recording_state = recording_state
        self._jobs = jobs
        self._build_menu()

        # Stop any existing blink timer
        if self._blink_timer_id is not None:
            from gi.repository import GLib
            GLib.source_remove(self._blink_timer_id)
            self._blink_timer_id = None

        if recording_state in ("recording", "paused"):
            self._blink_mode = "recording"
            self._blink_on = True
            self._indicator.set_icon_full("meeting-recorder-recording", "recording")
            from gi.repository import GLib
            self._blink_timer_id = GLib.timeout_add(700, self._blink_tick)
        elif recording_state == "idle" and bool(jobs):
            self._blink_mode = "processing"
            self._blink_on = True
            self._indicator.set_icon_full("meeting-recorder-processing", "processing")
            from gi.repository import GLib
            self._blink_timer_id = GLib.timeout_add(700, self._blink_tick)
        else:
            self._indicator.set_icon_full("meeting-recorder", "idle")

    def _blink_tick(self) -> bool:
        if self._blink_mode == "recording":
            if self._recording_state not in ("recording", "paused"):
                self._blink_timer_id = None
                return False
            self._blink_on = not self._blink_on
            icon = "meeting-recorder-recording" if self._blink_on else "meeting-recorder-recording-dim"
            self._indicator.set_icon_full(icon, "recording")
        else:  # processing
            if self._recording_state != "idle" or not bool(self._jobs):
                self._blink_timer_id = None
                return False
            self._blink_on = not self._blink_on
            icon = "meeting-recorder-processing" if self._blink_on else "meeting-recorder-processing-dim"
            self._indicator.set_icon_full(icon, "processing")
        return True

    def _on_start_headphones(self) -> None:
        from ...utils.glib_bridge import idle_call
        idle_call(self._window.on_record_headphones_clicked)

    def _on_start_speaker(self) -> None:
        from ...utils.glib_bridge import idle_call
        idle_call(self._window.on_record_speaker_clicked)

    def _on_transcribe_file(self) -> None:
        from ...utils.glib_bridge import idle_call
        idle_call(self._window.on_transcribe_file_clicked)

    def _on_pause(self) -> None:
        from ...utils.glib_bridge import idle_call
        idle_call(self._window.on_pause_clicked)

    def _on_resume(self) -> None:
        from ...utils.glib_bridge import idle_call
        idle_call(self._window.on_resume_clicked)

    def _on_stop(self) -> None:
        from ...utils.glib_bridge import idle_call
        idle_call(self._window.on_stop_clicked)

    def _on_cancel_save(self) -> None:
        from ...utils.glib_bridge import idle_call
        idle_call(self._window.on_cancel_save_clicked)

    def _on_cancel(self) -> None:
        from ...utils.glib_bridge import idle_call
        idle_call(self._window.on_cancel_clicked)

    def _on_open_meetings_folder(self) -> None:
        import os, subprocess
        from ...config import settings
        folder = os.path.expanduser(settings.load().get("output_folder", "~/meetings"))
        try:
            subprocess.Popen(["xdg-open", folder])
        except Exception:
            pass

    def _on_show(self) -> None:
        from gi.repository import GLib
        GLib.idle_add(self._window.present)

    def _on_quit(self) -> None:
        from gi.repository import GLib
        def _do_quit():
            if self._window._recorder:
                self._window._recorder.stop()
            self._window.get_application().quit()
        GLib.idle_add(_do_quit)
