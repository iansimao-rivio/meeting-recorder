"""API Keys settings tab — add, remove, toggle, collect key rows."""

from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

_SUGGESTED_ENV_KEYS = [
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "ELEVENLABS_API_KEY",
    "DEEPGRAM_API_KEY",
]


def _add_api_key_row(dialog, env_name: str = "", value: str = "") -> None:
    row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

    # Env name combo with entry
    name_combo = Gtk.ComboBoxText.new_with_entry()
    for suggestion in _SUGGESTED_ENV_KEYS:
        name_combo.append_text(suggestion)
    entry = name_combo.get_child()
    entry.set_text(env_name)
    entry.set_placeholder_text("ENV_VAR_NAME")
    name_combo.set_hexpand(True)
    row_box.pack_start(name_combo, True, True, 0)

    # Value entry (password masked)
    val_entry = Gtk.Entry()
    val_entry.set_text(value)
    val_entry.set_visibility(False)
    val_entry.set_placeholder_text("API key value")
    val_entry.set_hexpand(True)
    row_box.pack_start(val_entry, True, True, 0)

    # Show/hide toggle
    toggle_btn = Gtk.Button(label="Show")
    toggle_btn.connect("clicked", lambda b: _toggle_key_visibility(b, val_entry))
    row_box.pack_start(toggle_btn, False, False, 0)

    # Delete button
    row_data = {"box": row_box, "name_combo": name_combo, "val_entry": val_entry}
    del_btn = Gtk.Button(label="Delete")
    del_btn.connect("clicked", lambda *_: _remove_api_key_row(dialog, row_data))
    row_box.pack_start(del_btn, False, False, 0)

    dialog._api_key_rows.append(row_data)
    dialog._api_keys_box.pack_start(row_box, False, False, 0)
    row_box.show_all()


def _remove_api_key_row(dialog, row_data: dict) -> None:
    dialog._api_keys_box.remove(row_data["box"])
    dialog._api_key_rows.remove(row_data)


def _toggle_key_visibility(button: Gtk.Button, entry: Gtk.Entry) -> None:
    visible = not entry.get_visibility()
    entry.set_visibility(visible)
    button.set_label("Hide" if visible else "Show")


def collect_api_keys(dialog) -> dict[str, str] | None:
    """Collect API keys from rows. Returns None if duplicates found."""
    keys: dict[str, str] = {}
    seen_names: dict[str, int] = {}
    has_dupes = False

    for i, row_data in enumerate(dialog._api_key_rows):
        name_entry = row_data["name_combo"].get_child()
        name = name_entry.get_text().strip()
        value = row_data["val_entry"].get_text().strip()
        if not name:
            continue
        if name in seen_names:
            has_dupes = True
        seen_names[name] = i
        keys[name] = value

    if has_dupes:
        dialog._api_keys_error_label.set_text("Duplicate environment variable names found!")
        dialog._api_keys_error_label.show()
        return None

    dialog._api_keys_error_label.hide()
    return keys


def build_api_keys_tab(cfg: dict, dialog) -> Gtk.Widget:
    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    vbox.set_margin_top(16)
    vbox.set_margin_bottom(16)
    vbox.set_margin_start(16)
    vbox.set_margin_end(16)

    note = Gtk.Label(
        label="API keys are passed directly to providers and also set as environment variables.",
        xalign=0,
    )
    note.set_line_wrap(True)
    vbox.pack_start(note, False, False, 0)

    # Error label for duplicate validation
    dialog._api_keys_error_label = Gtk.Label(xalign=0)
    dialog._api_keys_error_label.set_no_show_all(True)
    vbox.pack_start(dialog._api_keys_error_label, False, False, 0)

    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_vexpand(True)

    dialog._api_keys_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    scroll.add(dialog._api_keys_box)
    vbox.pack_start(scroll, True, True, 0)

    # Load existing keys
    for env_name, value in cfg.get("api_keys", {}).items():
        _add_api_key_row(dialog, env_name, value)

    # Add button
    add_btn = Gtk.Button(label="Add Key")
    add_btn.connect("clicked", lambda *_: _add_api_key_row(dialog, "", ""))
    add_btn.set_halign(Gtk.Align.START)
    vbox.pack_start(add_btn, False, False, 0)

    return vbox
