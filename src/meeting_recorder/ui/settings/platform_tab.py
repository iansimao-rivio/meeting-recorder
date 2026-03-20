"""Platform settings tab — audio backend, screen recording, monitors."""

from __future__ import annotations

import shutil

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


def _detect_monitors() -> list[str]:
    """Detect available monitors via gpu-screen-recorder or kscreen-doctor."""
    try:
        from ...platform.screen.gpu_screen_recorder import GpuScreenRecorder
        rec = GpuScreenRecorder()
        return [m.name for m in rec.list_monitors()]
    except Exception:
        return []


def _on_monitor_all_toggled(check: Gtk.CheckButton, monitor_checks: list[Gtk.CheckButton]) -> None:
    active = check.get_active()
    for cb in monitor_checks:
        cb.set_sensitive(not active)
        if active:
            cb.set_active(False)


def _get_selected_monitors(dialog) -> str:
    if dialog._monitor_all_check.get_active():
        return "all"
    selected = [cb.get_label() for cb in dialog._monitor_checks if cb.get_active()]
    return ",".join(selected) if selected else "all"


def _on_screen_toggle(switch, dialog, *_) -> None:
    active = switch.get_active()
    _update_screen_warning(dialog)
    for w in (dialog._screen_recorder_label, dialog._screen_recorder_combo,
              dialog._monitors_label, dialog._fps_label, dialog._fps_spin,
              dialog._merge_label, dialog._merge_screen_check,
              dialog._monitor_all_check):
        w.set_sensitive(active)
    for cb in dialog._monitor_checks:
        cb.set_sensitive(active and not dialog._monitor_all_check.get_active())
    nl_available = getattr(dialog, '_nightlight_available', False)
    for w in (dialog._inhibit_nl_label, dialog._inhibit_nl_switch):
        w.set_sensitive(active and nl_available)


def _update_screen_warning(dialog) -> None:
    active = dialog._screen_recording_switch.get_active()
    if active and not shutil.which("gpu-screen-recorder"):
        dialog._screen_warn_label.set_markup(
            '<span foreground="red">gpu-screen-recorder is not installed. '
            'Install it: <b>yay -S gpu-screen-recorder</b></span>'
        )
        dialog._screen_warn_label.show()
    else:
        dialog._screen_warn_label.hide()


def build_platform_tab(cfg: dict, dialog, nightlight_available: bool = False) -> Gtk.Widget:
    grid = Gtk.Grid(column_spacing=12, row_spacing=12)
    grid.set_margin_top(16)
    grid.set_margin_bottom(16)
    grid.set_margin_start(16)
    grid.set_margin_end(16)
    dialog._nightlight_available = nightlight_available

    row = 0

    # Audio backend
    grid.attach(Gtk.Label(label="Audio backend:", xalign=0), 0, row, 1, 1)
    dialog._audio_backend_combo = Gtk.ComboBoxText()
    for name in ("pulseaudio", "pipewire"):
        dialog._audio_backend_combo.append(name, name)
    dialog._audio_backend_combo.set_active_id(
        cfg.get("audio_backend", "pipewire")
    )
    grid.attach(dialog._audio_backend_combo, 1, row, 1, 1)
    row += 1

    # Separate audio tracks
    grid.attach(Gtk.Label(label="Separate audio tracks:", xalign=0), 0, row, 1, 1)
    dialog._separate_tracks_switch = Gtk.Switch()
    dialog._separate_tracks_switch.set_active(
        cfg.get("separate_audio_tracks", True)
    )
    dialog._separate_tracks_switch.set_halign(Gtk.Align.START)
    grid.attach(dialog._separate_tracks_switch, 1, row, 1, 1)
    row += 1

    sep_note = Gtk.Label(
        label="Records mic and system audio as separate files for better diarization.",
        xalign=0,
    )
    sep_note.set_line_wrap(True)
    grid.attach(sep_note, 0, row, 2, 1)
    row += 1

    grid.attach(Gtk.Separator(), 0, row, 2, 1)
    row += 1

    # Screen recording
    grid.attach(Gtk.Label(label="Screen recording:", xalign=0), 0, row, 1, 1)
    dialog._screen_recording_switch = Gtk.Switch()
    dialog._screen_recording_switch.set_active(
        cfg.get("screen_recording", False)
    )
    dialog._screen_recording_switch.set_halign(Gtk.Align.START)
    dialog._screen_recording_switch.connect(
        "notify::active", lambda sw, *a: _on_screen_toggle(sw, dialog, *a)
    )
    grid.attach(dialog._screen_recording_switch, 1, row, 1, 1)
    row += 1

    # Screen recorder
    dialog._screen_recorder_label = Gtk.Label(label="Screen recorder:", xalign=0)
    grid.attach(dialog._screen_recorder_label, 0, row, 1, 1)
    dialog._screen_recorder_combo = Gtk.ComboBoxText()
    for name in ("gpu-screen-recorder", "none"):
        dialog._screen_recorder_combo.append(name, name)
    dialog._screen_recorder_combo.set_active_id(
        cfg.get("screen_recorder", "none")
    )
    grid.attach(dialog._screen_recorder_combo, 1, row, 1, 1)
    row += 1

    # Monitors
    dialog._monitors_label = Gtk.Label(label="Monitors:", xalign=0)
    dialog._monitors_label.set_valign(Gtk.Align.START)
    grid.attach(dialog._monitors_label, 0, row, 1, 1)

    monitors_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    dialog._monitor_all_check = Gtk.CheckButton(label="All monitors")
    dialog._monitor_checks: list[Gtk.CheckButton] = []

    dialog._monitor_all_check.connect(
        "toggled", lambda chk: _on_monitor_all_toggled(chk, dialog._monitor_checks)
    )
    monitors_box.pack_start(dialog._monitor_all_check, False, False, 0)

    detected = _detect_monitors()
    for name in detected:
        cb = Gtk.CheckButton(label=name)
        dialog._monitor_checks.append(cb)
        monitors_box.pack_start(cb, False, False, 0)

    if not detected:
        no_mon = Gtk.Label(label="No monitors detected", xalign=0)
        monitors_box.pack_start(no_mon, False, False, 0)

    # Set initial state from config
    cfg_monitors = cfg.get("monitors", "all")
    if cfg_monitors == "all":
        dialog._monitor_all_check.set_active(True)
    else:
        selected = {m.strip() for m in cfg_monitors.split(",") if m.strip()}
        for cb in dialog._monitor_checks:
            cb.set_active(cb.get_label() in selected)

    grid.attach(monitors_box, 1, row, 1, 1)
    row += 1

    # FPS
    dialog._fps_label = Gtk.Label(label="FPS:", xalign=0)
    grid.attach(dialog._fps_label, 0, row, 1, 1)
    dialog._fps_spin = Gtk.SpinButton.new_with_range(1, 60, 1)
    dialog._fps_spin.set_value(cfg.get("screen_fps", 30))
    grid.attach(dialog._fps_spin, 1, row, 1, 1)
    row += 1

    # Merge screen recording with audio
    dialog._merge_label = Gtk.Label(label="Merge screen + audio:", xalign=0)
    grid.attach(dialog._merge_label, 0, row, 1, 1)
    dialog._merge_screen_check = Gtk.CheckButton(label="Combine into a single video file with audio")
    dialog._merge_screen_check.set_active(cfg.get("merge_screen_audio", False))
    grid.attach(dialog._merge_screen_check, 1, row, 1, 1)
    row += 1

    # Night light inhibition
    dialog._inhibit_nl_label = Gtk.Label(label="Pause night light during screen recording:", xalign=0)
    grid.attach(dialog._inhibit_nl_label, 0, row, 1, 1)
    dialog._inhibit_nl_switch = Gtk.Switch()
    dialog._inhibit_nl_switch.set_active(cfg.get("inhibit_nightlight", True))
    dialog._inhibit_nl_switch.set_halign(Gtk.Align.START)
    grid.attach(dialog._inhibit_nl_switch, 1, row, 1, 1)
    row += 1

    dialog._nl_note = Gtk.Label(xalign=0)
    dialog._nl_note.set_line_wrap(True)
    dialog._nl_note.set_no_show_all(True)
    if not nightlight_available:
        dialog._nl_note.set_markup(
            '<span foreground="gray">Night light control not available on this system</span>'
        )
        dialog._nl_note.show()
    grid.attach(dialog._nl_note, 0, row, 2, 1)
    row += 1

    # Screen recorder availability warning
    dialog._screen_warn_label = Gtk.Label(xalign=0)
    dialog._screen_warn_label.set_line_wrap(True)
    dialog._screen_warn_label.set_no_show_all(True)
    grid.attach(dialog._screen_warn_label, 0, row, 2, 1)

    _update_screen_warning(dialog)

    # Store helper on dialog for _save() access
    dialog._get_selected_monitors = lambda: _get_selected_monitors(dialog)

    # Apply initial sensitivity for all screen-recording-dependent widgets
    _on_screen_toggle(dialog._screen_recording_switch, dialog)

    return grid
