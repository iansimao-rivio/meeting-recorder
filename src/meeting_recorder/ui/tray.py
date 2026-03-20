"""
System tray icon — thin wrapper delegating to platform tray backends.

Priority:
1. SNI (pure DBus StatusNotifierItem) — KDE Plasma native, supports left-click
2. pystray — cross-platform fallback
3. AppIndicator — legacy fallback
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _has_sni_watcher() -> bool:
    """Check if KDE's StatusNotifierWatcher is running on the session bus."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        result = bus.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            GLib.Variant("(s)", ("org.kde.StatusNotifierWatcher",)),
            GLib.VariantType("(b)"),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
        return result.get_child_value(0).get_boolean()
    except Exception:
        return False


class TrayIcon:
    def __init__(self, window) -> None:
        self._impl = None

        # On KDE Plasma (SNI watcher present), use our pure DBus SNI backend
        # which supports left-click Activate (ItemIsMenu=false)
        if _has_sni_watcher():
            try:
                from ..platform.tray.sni_backend import SNITray
                self._impl = SNITray(window)
                logger.debug("Using SNI (pure DBus) tray backend")
                return
            except Exception as exc:
                logger.debug("SNI backend failed: %s, trying fallbacks", exc)

        # Try pystray
        try:
            from ..platform.tray.pystray_backend import PystrayBackend
            self._impl = PystrayBackend(window)
            logger.debug("Using pystray tray backend")
            return
        except Exception:
            logger.debug("pystray not available, trying AppIndicator")

        # Fall back to AppIndicator
        try:
            from ..platform.tray.appindicator import AppIndicatorTray
            self._impl = AppIndicatorTray(window)
            logger.debug("Using AppIndicator tray backend")
        except Exception:
            logger.warning("No tray backend available")

    def update(self, recording_state: str, jobs: list) -> None:
        if self._impl:
            self._impl.update(recording_state, jobs)

    def set_on_activate(self, callback) -> None:
        if self._impl:
            self._impl.set_on_activate(callback)
