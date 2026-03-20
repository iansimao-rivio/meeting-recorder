from __future__ import annotations

import logging

from gi.repository import Gio, GLib

from .base import NightLightInhibitor

logger = logging.getLogger(__name__)

_BUS_NAME = "org.kde.KWin"
_OBJECT_PATH = "/org/kde/KWin/NightLight"
_INTERFACE = "org.kde.KWin.NightLight"


class KWinNightLightInhibitor(NightLightInhibitor):
    """KDE Plasma 6 Night Color inhibitor using DBus.

    Uses Gio.DBusProxy for a persistent session bus connection.
    KWin ties inhibition to the caller's DBus connection — if the
    connection drops (e.g. app crash), inhibition is auto-released.

    The proxy is created lazily on the first inhibit() call to keep
    construction safe and avoid a DBus connection if never used.
    """

    def __init__(self) -> None:
        self._proxy: Gio.DBusProxy | None = None
        self._cookie: int | None = None

    def _get_proxy(self) -> Gio.DBusProxy:
        """Create or return the cached DBus proxy."""
        if self._proxy is None:
            self._proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,
                _BUS_NAME,
                _OBJECT_PATH,
                _INTERFACE,
                None,
            )
        return self._proxy

    def is_available(self) -> bool:
        """Check if the KWin NightLight DBus interface exists.

        Creates a temporary probe proxy (discarded after check) because
        the caller may substitute a NoOp based on the result — persisting
        the proxy would leak a connection in that case.
        """
        try:
            probe = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,
                _BUS_NAME,
                _OBJECT_PATH,
                _INTERFACE,
                None,
            )
            prop = probe.get_cached_property("available")
            return prop is not None and prop.get_boolean()
        except Exception:
            return False

    def inhibit(self) -> None:
        if self._cookie is not None:
            return
        try:
            proxy = self._get_proxy()
            result = proxy.call_sync(
                "inhibit",
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            self._cookie = result.unpack()[0]
            logger.info("Night light inhibited (cookie=%d)", self._cookie)
        except Exception as exc:
            logger.warning("Failed to inhibit night light: %s", exc)

    def uninhibit(self) -> None:
        if self._cookie is None:
            return
        try:
            proxy = self._get_proxy()
            proxy.call_sync(
                "uninhibit",
                GLib.Variant("(u)", (self._cookie,)),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            logger.info("Night light uninhibited (cookie=%d)", self._cookie)
        except Exception as exc:
            logger.warning("Failed to uninhibit night light: %s", exc)
        finally:
            self._cookie = None
