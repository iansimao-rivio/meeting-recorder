"""Tray settings tab — default action and recording click behavior."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


_DEFAULT_ACTION_OPTIONS = [
    ("record_headphones", "Record Headphones"),
    ("record_speaker", "Record Speaker"),
    ("transcribe_file", "Transcribe File"),
]

_RECORDING_ACTION_OPTIONS = [
    ("stop", "Stop Recording"),
    ("pause", "Pause Recording"),
    ("cancel_save", "Cancel (save recording)"),
    ("cancel_discard", "Cancel (discard)"),
]


def build_tray_tab(cfg: dict, dialog) -> Gtk.Widget:
    grid = Gtk.Grid(column_spacing=12, row_spacing=12)
    grid.set_margin_top(16)
    grid.set_margin_bottom(16)
    grid.set_margin_start(16)
    grid.set_margin_end(16)

    row = 0

    # Default tray action
    grid.attach(Gtk.Label(label="Default tray action:", xalign=0), 0, row, 1, 1)
    dialog._tray_default_combo = Gtk.ComboBoxText()
    for key, label in _DEFAULT_ACTION_OPTIONS:
        dialog._tray_default_combo.append(key, label)
    dialog._tray_default_combo.set_active_id(
        cfg.get("tray_default_action", "record_headphones")
    )
    grid.attach(dialog._tray_default_combo, 1, row, 1, 1)
    row += 1

    default_note = Gtk.Label(
        label="Action triggered by single-clicking the tray icon when not recording."
    )
    default_note.set_line_wrap(True)
    default_note.set_xalign(0)
    grid.attach(default_note, 0, row, 2, 1)
    row += 1

    grid.attach(Gtk.Separator(), 0, row, 2, 1)
    row += 1

    # Click while recording
    grid.attach(Gtk.Label(label="Click while recording:", xalign=0), 0, row, 1, 1)
    dialog._tray_recording_combo = Gtk.ComboBoxText()
    for key, label in _RECORDING_ACTION_OPTIONS:
        dialog._tray_recording_combo.append(key, label)
    dialog._tray_recording_combo.set_active_id(
        cfg.get("tray_recording_action", "stop")
    )
    grid.attach(dialog._tray_recording_combo, 1, row, 1, 1)
    row += 1

    # Pause note (shown/hidden based on selection)
    dialog._tray_pause_note = Gtk.Label(
        label="While paused, clicking the tray icon again will resume recording, "
              "not start a new one."
    )
    dialog._tray_pause_note.set_line_wrap(True)
    dialog._tray_pause_note.set_xalign(0)
    dialog._tray_pause_note.set_no_show_all(True)
    grid.attach(dialog._tray_pause_note, 0, row, 2, 1)
    row += 1

    def _on_recording_action_changed(*_):
        is_pause = dialog._tray_recording_combo.get_active_id() == "pause"
        if is_pause:
            dialog._tray_pause_note.show()
        else:
            dialog._tray_pause_note.hide()

    dialog._tray_recording_combo.connect("changed", _on_recording_action_changed)
    _on_recording_action_changed()

    return grid
