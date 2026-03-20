"""Pure DBus StatusNotifierItem tray backend for KDE Plasma.

Implements the SNI spec directly via Gio.DBus — no AppIndicator or pystray
dependency. This gives full control over ItemIsMenu (set to false so KDE
calls Activate on left-click instead of opening the menu).

Left-click  → Activate  → triggers configured default action
Right-click → ContextMenu → KDE renders menu natively via Dbusmenu
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from .base import TrayBackend

logger = logging.getLogger(__name__)

_ICONS_DIR = str(Path(__file__).resolve().parent.parent.parent / "assets" / "icons")

# DBus interface XML for org.kde.StatusNotifierItem
_SNI_XML = """\
<node>
  <interface name="org.kde.StatusNotifierItem">
    <method name="Activate">
      <arg direction="in" type="i" name="x"/>
      <arg direction="in" type="i" name="y"/>
    </method>
    <method name="SecondaryActivate">
      <arg direction="in" type="i" name="x"/>
      <arg direction="in" type="i" name="y"/>
    </method>
    <method name="ContextMenu">
      <arg direction="in" type="i" name="x"/>
      <arg direction="in" type="i" name="y"/>
    </method>
    <method name="Scroll">
      <arg direction="in" type="i" name="delta"/>
      <arg direction="in" type="s" name="orientation"/>
    </method>
    <method name="ProvideXdgActivationToken">
      <arg direction="in" type="s" name="token"/>
    </method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewOverlayIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus">
      <arg type="s" name="status"/>
    </signal>
    <signal name="NewMenu"/>
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="u" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
  </interface>
</node>
"""


class SNITray(TrayBackend):
    """Pure DBus StatusNotifierItem tray for KDE Plasma.

    Left-click triggers Activate (configured default action).
    Right-click triggers ContextMenu (GTK popup menu).
    """

    def __init__(self, window) -> None:
        super().__init__()
        import gi
        gi.require_version("Gio", "2.0")
        gi.require_version("Dbusmenu", "0.4")
        from gi.repository import Dbusmenu, Gio, GLib

        self._window = window
        self._GLib = GLib
        self._Dbusmenu = Dbusmenu
        self._recording_state = "idle"
        self._jobs: list = []
        self._icon_name = "meeting-recorder"

        self._blink_timer_id = None
        self._blink_on = True
        self._blink_mode = "recording"

        # Menu callbacks keyed by Dbusmenu.Menuitem id
        self._menu_callbacks: dict[int, callable] = {}

        # Create Dbusmenu server — KDE reads this to render the context menu
        self._menu_path = "/MenuBar"
        self._menu_root = Dbusmenu.Menuitem()
        self._dbusmenu_server = Dbusmenu.Server.new(self._menu_path)
        self._dbusmenu_server.set_root(self._menu_root)

        # Register on session bus
        self._bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self._bus_name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._object_path = "/StatusNotifierItem"

        # Parse interface XML
        self._node_info = Gio.DBusNodeInfo.new_for_xml(_SNI_XML)
        self._iface_info = self._node_info.lookup_interface(
            "org.kde.StatusNotifierItem"
        )

        # Register the object
        self._registration_id = self._bus.register_object(
            self._object_path,
            self._iface_info,
            self._handle_method_call,
            self._handle_get_property,
            None,  # set_property not needed
        )

        # Own the bus name
        self._name_id = Gio.bus_own_name_on_connection(
            self._bus,
            self._bus_name,
            Gio.BusNameOwnerFlags.NONE,
            None,
            None,
        )

        # Install icon to XDG icon path so KDE can find it
        self._install_icons()

        # Register with StatusNotifierWatcher
        self._register_with_watcher()

        self._build_menu()
        logger.info("SNI tray backend initialized (bus=%s)", self._bus_name)

    def _install_icons(self) -> None:
        """Copy SVG icons to XDG data dir so KDE's icon theme can find them."""
        xdg_data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        icon_dir = xdg_data / "icons" / "hicolor" / "scalable" / "apps"
        icon_dir.mkdir(parents=True, exist_ok=True)

        import shutil
        src_dir = Path(_ICONS_DIR)
        for svg in src_dir.glob("meeting-recorder*.svg"):
            dst = icon_dir / svg.name
            if not dst.exists() or not self._icons_match(svg, dst):
                shutil.copy2(svg, dst)
                logger.debug("Installed icon: %s", dst)

    @staticmethod
    def _icons_match(src: Path, dst: Path) -> bool:
        """Check if installed icon matches source (by size)."""
        try:
            return src.stat().st_size == dst.stat().st_size
        except OSError:
            return False

    def _register_with_watcher(self) -> None:
        """Register this item with org.kde.StatusNotifierWatcher."""
        try:
            from gi.repository import Gio, GLib
            self._bus.call_sync(
                "org.kde.StatusNotifierWatcher",
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (self._bus_name,)),
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
        except Exception as exc:
            logger.warning("Failed to register with StatusNotifierWatcher: %s", exc)

    def _handle_method_call(
        self, connection, sender, object_path, interface_name,
        method_name, parameters, invocation,
    ):
        """Handle DBus method calls on the SNI interface."""
        from gi.repository import GLib

        if method_name == "Activate":
            cb = self._on_activate
            if cb is not None:
                GLib.idle_add(cb)
            invocation.return_value(None)

        elif method_name == "ContextMenu":
            # KDE renders the menu from our Dbusmenu server — nothing to do here
            invocation.return_value(None)

        elif method_name == "SecondaryActivate":
            # Middle-click — same as Activate
            cb = self._on_activate
            if cb is not None:
                GLib.idle_add(cb)
            invocation.return_value(None)

        elif method_name == "Scroll":
            invocation.return_value(None)

        elif method_name == "ProvideXdgActivationToken":
            invocation.return_value(None)

        else:
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownMethod",
                f"Unknown method: {method_name}",
            )

    def _handle_get_property(
        self, connection, sender, object_path, interface_name, property_name,
    ):
        """Handle DBus property reads on the SNI interface."""
        from gi.repository import GLib

        props = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", "meeting-recorder"),
            "Title": GLib.Variant("s", "Meeting Recorder"),
            "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("u", 0),
            "IconName": GLib.Variant("s", self._icon_name),
            "IconThemePath": GLib.Variant("s", _ICONS_DIR),
            "IconPixmap": GLib.Variant("a(iiay)", []),
            "OverlayIconName": GLib.Variant("s", ""),
            "OverlayIconPixmap": GLib.Variant("a(iiay)", []),
            "AttentionIconName": GLib.Variant("s", ""),
            "AttentionIconPixmap": GLib.Variant("a(iiay)", []),
            "AttentionMovieName": GLib.Variant("s", ""),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", ("", [], "", "")),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", self._menu_path),
        }
        return props.get(property_name)

    def _emit_new_icon(self) -> None:
        """Emit NewIcon signal to tell KDE to refresh the icon."""
        try:
            from gi.repository import GLib
            self._bus.emit_signal(
                None,
                self._object_path,
                "org.kde.StatusNotifierItem",
                "NewIcon",
                None,
            )
        except Exception:
            pass

    # -- Menu building (same pattern as AppIndicator) --------------------------

    def _build_menu(self) -> None:
        """Rebuild the Dbusmenu tree. KDE reads this on right-click."""
        Dbusmenu = self._Dbusmenu

        # Clear existing children
        self._menu_callbacks.clear()
        while True:
            children = self._menu_root.get_children()
            if not children:
                break
            for child in children:
                self._menu_root.child_delete(child)

        state = self._recording_state
        jobs = self._jobs

        if state == "idle":
            self._add_item("Record (Headphones)", self._on_start_headphones)
            self._add_item("Record (Speaker)", self._on_start_speaker)
            self._add_item("Transcribe File", self._on_transcribe_file)
        elif state == "recording":
            self._add_item("Pause Recording", self._on_pause)
            self._add_item("Stop Recording", self._on_stop)
            self._add_item("Cancel (save recording)", self._on_cancel_save)
            self._add_item("Cancel", self._on_cancel)
        elif state == "paused":
            self._add_item("Resume Recording", self._on_resume)
            self._add_item("Stop Recording", self._on_stop)
            self._add_item("Cancel (save recording)", self._on_cancel_save)
            self._add_item("Cancel", self._on_cancel)

        if jobs:
            self._add_separator()
            header = Dbusmenu.Menuitem()
            header.property_set("label", f"Processing ({len(jobs)} active)")
            header.property_set_bool("enabled", False)
            self._menu_root.child_append(header)
            for label, cancel_fn in jobs:
                self._add_item(f"  Cancel: {label}", cancel_fn)

        self._add_separator()
        self._add_item("Open Meetings Folder", self._on_open_meetings_folder)
        self._add_item("Show Window", self._on_show)
        self._add_item("Quit", self._on_quit)

    def _add_item(self, label: str, callback) -> None:
        item = self._Dbusmenu.Menuitem()
        item.property_set("label", label)
        item_id = item.get_id()
        self._menu_callbacks[item_id] = callback
        item.connect("item-activated", self._on_menu_item_activated)
        self._menu_root.child_append(item)

    def _add_separator(self) -> None:
        sep = self._Dbusmenu.Menuitem()
        sep.property_set("type", "separator")
        self._menu_root.child_append(sep)

    def _on_menu_item_activated(self, menuitem, timestamp) -> None:
        """Called when a Dbusmenu item is clicked."""
        item_id = menuitem.get_id()
        cb = self._menu_callbacks.get(item_id)
        if cb:
            cb()

    # -- TrayBackend interface -------------------------------------------------

    def update(self, recording_state: str, jobs: list) -> None:
        self._recording_state = recording_state
        self._jobs = jobs
        self._build_menu()

        # Stop existing blink timer
        if self._blink_timer_id is not None:
            from gi.repository import GLib
            GLib.source_remove(self._blink_timer_id)
            self._blink_timer_id = None

        if recording_state in ("recording", "paused"):
            self._blink_mode = "recording"
            self._blink_on = True
            self._icon_name = "meeting-recorder-recording"
            self._emit_new_icon()
            from gi.repository import GLib
            self._blink_timer_id = GLib.timeout_add(700, self._blink_tick)
        elif recording_state == "idle" and bool(jobs):
            self._blink_mode = "processing"
            self._blink_on = True
            self._icon_name = "meeting-recorder-processing"
            self._emit_new_icon()
            from gi.repository import GLib
            self._blink_timer_id = GLib.timeout_add(700, self._blink_tick)
        else:
            self._icon_name = "meeting-recorder"
            self._emit_new_icon()

    def _blink_tick(self) -> bool:
        if self._blink_mode == "recording":
            if self._recording_state not in ("recording", "paused"):
                self._blink_timer_id = None
                return False
            self._blink_on = not self._blink_on
            self._icon_name = (
                "meeting-recorder-recording" if self._blink_on
                else "meeting-recorder-recording-dim"
            )
        else:  # processing
            if self._recording_state != "idle" or not bool(self._jobs):
                self._blink_timer_id = None
                return False
            self._blink_on = not self._blink_on
            self._icon_name = (
                "meeting-recorder-processing" if self._blink_on
                else "meeting-recorder-processing-dim"
            )
        self._emit_new_icon()
        return True

    # -- Callbacks (delegate to main window) -----------------------------------

    def _on_start_headphones(self):
        from ...utils.glib_bridge import idle_call
        idle_call(self._window.on_record_headphones_clicked)

    def _on_start_speaker(self):
        from ...utils.glib_bridge import idle_call
        idle_call(self._window.on_record_speaker_clicked)

    def _on_transcribe_file(self):
        from ...utils.glib_bridge import idle_call
        idle_call(self._window.on_transcribe_file_clicked)

    def _on_pause(self):
        from ...utils.glib_bridge import idle_call
        idle_call(self._window.on_pause_clicked)

    def _on_resume(self):
        from ...utils.glib_bridge import idle_call
        idle_call(self._window.on_resume_clicked)

    def _on_stop(self):
        from ...utils.glib_bridge import idle_call
        idle_call(self._window.on_stop_clicked)

    def _on_cancel_save(self):
        from ...utils.glib_bridge import idle_call
        idle_call(self._window.on_cancel_save_clicked)

    def _on_cancel(self):
        from ...utils.glib_bridge import idle_call
        idle_call(self._window.on_cancel_clicked)

    def _on_open_meetings_folder(self):
        import subprocess
        from ...config import settings
        folder = os.path.expanduser(settings.load().get("output_folder", "~/meetings"))
        try:
            subprocess.Popen(["xdg-open", folder])
        except Exception:
            pass

    def _on_show(self):
        from gi.repository import GLib
        GLib.idle_add(self._window.present)

    def _on_quit(self):
        from gi.repository import GLib
        def _do_quit():
            if self._window._recorder:
                self._window._recorder.stop()
            self._window.get_application().quit()
        GLib.idle_add(_do_quit)
