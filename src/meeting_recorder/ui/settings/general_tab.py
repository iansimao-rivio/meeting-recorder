"""General settings tab — provider selection, output, quality, startup."""

from __future__ import annotations

import os

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ...config.defaults import (
    LITELLM_SUMMARIZATION_MODELS,
    LITELLM_TRANSCRIPTION_MODELS,
    LLM_TIMEOUT_OPTIONS,
    RECORDING_QUALITIES,
    SUMMARIZATION_PROVIDERS,
    TRANSCRIPTION_PROVIDERS,
)
from ...utils.autostart import can_enable_autostart, is_autostart_enabled

_PROVIDER_LABELS = {
    "gemini": "Google Gemini (Direct Audio Upload)",
    "elevenlabs": "ElevenLabs Scribe v2",
    "whisper": "Whisper (local)",
    "litellm": "LiteLLM (100+ providers)",
    "claude_code": "Claude Code CLI",
}


def _make_provider_combo(items: list[str], active: str) -> Gtk.ComboBoxText:
    combo = Gtk.ComboBoxText()
    for item in items:
        combo.append(item, _PROVIDER_LABELS.get(item, item))
    combo.set_active_id(active)
    if combo.get_active_id() is None and items:
        combo.set_active(0)
    return combo


def update_litellm_visibility(dialog) -> None:
    ts_is_litellm = (dialog._ts_combo.get_active_id() == "litellm")
    dialog._litellm_ts_label.set_visible(ts_is_litellm)
    dialog._litellm_ts_combo.set_visible(ts_is_litellm)

    ss_is_litellm = (dialog._ss_combo.get_active_id() == "litellm")
    dialog._litellm_ss_label.set_visible(ss_is_litellm)
    dialog._litellm_ss_combo.set_visible(ss_is_litellm)


def build_general_tab(cfg: dict, dialog) -> Gtk.Widget:
    grid = Gtk.Grid(column_spacing=12, row_spacing=12)
    grid.set_margin_top(16)
    grid.set_margin_bottom(16)
    grid.set_margin_start(16)
    grid.set_margin_end(16)

    row = 0

    # Transcription provider
    grid.attach(Gtk.Label(label="Transcription provider:", xalign=0), 0, row, 1, 1)
    dialog._ts_combo = _make_provider_combo(
        TRANSCRIPTION_PROVIDERS, cfg.get("transcription_provider", "gemini")
    )
    dialog._ts_combo.connect("changed", lambda *_: update_litellm_visibility(dialog))
    grid.attach(dialog._ts_combo, 1, row, 1, 1)
    row += 1

    # LiteLLM transcription model (visible only when litellm selected)
    dialog._litellm_ts_label = Gtk.Label(label="LiteLLM transcription model:", xalign=0)
    grid.attach(dialog._litellm_ts_label, 0, row, 1, 1)
    dialog._litellm_ts_combo = Gtk.ComboBoxText.new_with_entry()
    for m in LITELLM_TRANSCRIPTION_MODELS:
        dialog._litellm_ts_combo.append_text(m)
    entry = dialog._litellm_ts_combo.get_child()
    entry.set_text(cfg.get("litellm_transcription_model", "groq/whisper-large-v3"))
    dialog._litellm_ts_combo.set_hexpand(True)
    grid.attach(dialog._litellm_ts_combo, 1, row, 1, 1)
    row += 1

    # Summarization provider
    grid.attach(Gtk.Label(label="Summarization provider:", xalign=0), 0, row, 1, 1)
    dialog._ss_combo = _make_provider_combo(
        SUMMARIZATION_PROVIDERS, cfg.get("summarization_provider", "litellm")
    )
    dialog._ss_combo.connect("changed", lambda *_: update_litellm_visibility(dialog))
    grid.attach(dialog._ss_combo, 1, row, 1, 1)
    row += 1

    # LiteLLM summarization model (visible only when litellm selected)
    dialog._litellm_ss_label = Gtk.Label(label="LiteLLM summarization model:", xalign=0)
    grid.attach(dialog._litellm_ss_label, 0, row, 1, 1)
    dialog._litellm_ss_combo = Gtk.ComboBoxText.new_with_entry()
    for m in LITELLM_SUMMARIZATION_MODELS:
        dialog._litellm_ss_combo.append_text(m)
    entry = dialog._litellm_ss_combo.get_child()
    entry.set_text(cfg.get("litellm_summarization_model", "gemini/gemini-2.5-flash"))
    dialog._litellm_ss_combo.set_hexpand(True)
    grid.attach(dialog._litellm_ss_combo, 1, row, 1, 1)
    row += 1

    grid.attach(Gtk.Separator(), 0, row, 2, 1)
    row += 1

    # Output folder
    grid.attach(Gtk.Label(label="Output folder:", xalign=0), 0, row, 1, 1)
    folder_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    dialog._folder_entry = Gtk.Entry()
    dialog._folder_entry.set_text(cfg.get("output_folder", "~/meetings"))
    dialog._folder_entry.set_hexpand(True)
    browse_btn = Gtk.Button(label="Browse\u2026")

    def _on_browse_folder(*_):
        chooser = Gtk.FileChooserDialog(
            title="Select Output Folder",
            transient_for=dialog,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        chooser.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK,
        )
        current = os.path.expanduser(dialog._folder_entry.get_text())
        if os.path.isdir(current):
            chooser.set_current_folder(current)
        if chooser.run() == Gtk.ResponseType.OK:
            dialog._folder_entry.set_text(chooser.get_filename())
        chooser.destroy()

    browse_btn.connect("clicked", _on_browse_folder)
    folder_box.pack_start(dialog._folder_entry, True, True, 0)
    folder_box.pack_start(browse_btn, False, False, 0)
    grid.attach(folder_box, 1, row, 1, 1)
    row += 1

    # Recording quality
    grid.attach(Gtk.Label(label="Recording quality:", xalign=0), 0, row, 1, 1)
    dialog._quality_combo = Gtk.ComboBoxText()
    for key, (label, _) in RECORDING_QUALITIES.items():
        dialog._quality_combo.append(key, label)
    dialog._quality_combo.set_active_id(cfg.get("recording_quality", "high"))
    grid.attach(dialog._quality_combo, 1, row, 1, 1)
    row += 1

    # Processing timeout
    grid.attach(Gtk.Label(label="Processing timeout:", xalign=0), 0, row, 1, 1)
    dialog._timeout_combo = Gtk.ComboBoxText()
    current_timeout = cfg.get("llm_request_timeout_minutes", 5)
    for minutes in LLM_TIMEOUT_OPTIONS:
        dialog._timeout_combo.append(str(minutes), f"{minutes} min")
    dialog._timeout_combo.set_active_id(str(current_timeout))
    if dialog._timeout_combo.get_active_id() is None:
        dialog._timeout_combo.set_active_id("5")
    grid.attach(dialog._timeout_combo, 1, row, 1, 1)
    row += 1

    grid.attach(Gtk.Separator(), 0, row, 2, 1)
    row += 1

    # Start at system startup
    dialog._startup_switch = Gtk.Switch()
    dialog._startup_switch.set_active(is_autostart_enabled())
    dialog._startup_switch.set_halign(Gtk.Align.START)

    can_enable = can_enable_autostart()
    is_enabled = is_autostart_enabled()
    dialog._startup_switch.set_sensitive(is_enabled or can_enable)

    grid.attach(Gtk.Label(label="Start at system startup:", xalign=0), 0, row, 1, 1)
    grid.attach(dialog._startup_switch, 1, row, 1, 1)
    row += 1

    if not (is_enabled or can_enable):
        note = Gtk.Label(
            label="Note: To enable autostart, the app must first be installed via install.sh."
        )
        note.set_line_wrap(True)
        note.set_xalign(0)
        grid.attach(note, 0, row, 2, 1)
        row += 1

    # Auto-title after processing
    grid.attach(Gtk.Label(label="Auto-generate title:", xalign=0), 0, row, 1, 1)
    dialog._auto_title_switch = Gtk.Switch()
    dialog._auto_title_switch.set_active(cfg.get("auto_title", False))
    dialog._auto_title_switch.set_halign(Gtk.Align.START)
    grid.attach(dialog._auto_title_switch, 1, row, 1, 1)
    row += 1

    auto_title_note = Gtk.Label(
        label="When no title is provided, use AI to generate one from meeting notes after processing.",
    )
    auto_title_note.set_line_wrap(True)
    auto_title_note.set_xalign(0)
    grid.attach(auto_title_note, 0, row, 2, 1)
    row += 1

    # Enable call detection
    dialog._detection_switch = Gtk.Switch()
    dialog._detection_switch.set_active(
        cfg.get("call_detection_enabled", False)
    )
    dialog._detection_switch.set_halign(Gtk.Align.START)

    grid.attach(Gtk.Label(label="Enable call detection:", xalign=0), 0, row, 1, 1)
    grid.attach(dialog._detection_switch, 1, row, 1, 1)
    row += 1

    note_detection = Gtk.Label(
        label=(
            "When enabled, the app monitors running processes and audio streams\n"
            "to detect active calls and notify you to start recording.\n\n"
            "Note: May produce false positives for other apps that use the microphone."
        )
    )
    note_detection.set_line_wrap(True)
    note_detection.set_xalign(0)
    grid.attach(note_detection, 0, row, 2, 1)

    return grid
