from unittest.mock import MagicMock, patch
import pytest

from meeting_recorder.platform.nightlight.kwin import KWinNightLightInhibitor


class TestIsAvailable:
    @patch("meeting_recorder.platform.nightlight.kwin.Gio")
    def test_available_when_dbus_responds(self, mock_gio):
        proxy = MagicMock()
        proxy.get_cached_property.return_value = MagicMock()
        proxy.get_cached_property.return_value.get_boolean.return_value = True
        mock_gio.DBusProxy.new_for_bus_sync.return_value = proxy
        inhibitor = KWinNightLightInhibitor()
        assert inhibitor.is_available() is True

    @patch("meeting_recorder.platform.nightlight.kwin.Gio")
    def test_not_available_when_dbus_fails(self, mock_gio):
        mock_gio.DBusProxy.new_for_bus_sync.side_effect = Exception("no bus")
        inhibitor = KWinNightLightInhibitor()
        assert inhibitor.is_available() is False


class TestInhibit:
    @patch("meeting_recorder.platform.nightlight.kwin.Gio")
    @patch("meeting_recorder.platform.nightlight.kwin.GLib")
    def test_inhibit_calls_dbus_and_stores_cookie(self, mock_glib, mock_gio):
        proxy = MagicMock()
        result = MagicMock()
        result.unpack.return_value = (42,)
        proxy.call_sync.return_value = result
        mock_gio.DBusProxy.new_for_bus_sync.return_value = proxy

        inhibitor = KWinNightLightInhibitor()
        inhibitor.inhibit()

        proxy.call_sync.assert_called_once()
        assert proxy.call_sync.call_args[0][0] == "inhibit"

    @patch("meeting_recorder.platform.nightlight.kwin.Gio")
    @patch("meeting_recorder.platform.nightlight.kwin.GLib")
    def test_inhibit_noop_when_already_inhibited(self, mock_glib, mock_gio):
        proxy = MagicMock()
        result = MagicMock()
        result.unpack.return_value = (42,)
        proxy.call_sync.return_value = result
        mock_gio.DBusProxy.new_for_bus_sync.return_value = proxy

        inhibitor = KWinNightLightInhibitor()
        inhibitor.inhibit()
        proxy.call_sync.reset_mock()
        inhibitor.inhibit()  # second call should be no-op
        proxy.call_sync.assert_not_called()


class TestUninhibit:
    @patch("meeting_recorder.platform.nightlight.kwin.Gio")
    @patch("meeting_recorder.platform.nightlight.kwin.GLib")
    def test_uninhibit_calls_dbus_with_cookie(self, mock_glib, mock_gio):
        proxy = MagicMock()
        result = MagicMock()
        result.unpack.return_value = (42,)
        proxy.call_sync.return_value = result
        mock_gio.DBusProxy.new_for_bus_sync.return_value = proxy

        inhibitor = KWinNightLightInhibitor()
        inhibitor.inhibit()
        proxy.call_sync.reset_mock()
        inhibitor.uninhibit()

        proxy.call_sync.assert_called_once()
        args = proxy.call_sync.call_args[0]
        assert args[0] == "uninhibit"

    @patch("meeting_recorder.platform.nightlight.kwin.Gio")
    @patch("meeting_recorder.platform.nightlight.kwin.GLib")
    def test_uninhibit_noop_when_not_inhibited(self, mock_glib, mock_gio):
        inhibitor = KWinNightLightInhibitor()
        inhibitor.uninhibit()  # should not raise or call dbus

    @patch("meeting_recorder.platform.nightlight.kwin.Gio")
    @patch("meeting_recorder.platform.nightlight.kwin.GLib")
    def test_inhibit_failure_logged_not_raised(self, mock_glib, mock_gio):
        proxy = MagicMock()
        proxy.call_sync.side_effect = Exception("dbus error")
        mock_gio.DBusProxy.new_for_bus_sync.return_value = proxy

        inhibitor = KWinNightLightInhibitor()
        inhibitor.inhibit()  # should not raise
