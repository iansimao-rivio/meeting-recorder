"""Models settings tab — Gemini, Whisper, Ollama config and download management."""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from ...config.defaults import (
    GEMINI_MODELS,
    OLLAMA_DEFAULT_HOST,
    OLLAMA_MODEL_INFO,
    OLLAMA_MODELS,
    WHISPER_HF_REPOS,
    WHISPER_MODEL_INFO,
    WHISPER_MODELS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level helpers (no UI dependencies)
# ---------------------------------------------------------------------------

def _is_whisper_cached(model_name: str) -> bool:
    repo = WHISPER_HF_REPOS.get(model_name, f"Systran/faster-whisper-{model_name}")
    cache_dir = (
        Path.home()
        / ".cache"
        / "huggingface"
        / "hub"
        / f"models--{repo.replace('/', '--')}"
    )
    return cache_dir.exists()


def _get_ollama_installed_models(host: str) -> list[str] | None:
    """Returns list of installed model names, or None if ollama unreachable."""
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=3) as r:
            data = json.loads(r.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return None


def _ollama_model_installed(model: str, installed: list[str]) -> bool:
    return any(n == model or n.startswith(f"{model}:") for n in installed)


def _make_combo(items: list[str], active: str) -> Gtk.ComboBoxText:
    combo = Gtk.ComboBoxText()
    for item in items:
        combo.append(item, item)
    combo.set_active_id(active)
    if combo.get_active_id() is None and items:
        combo.set_active(0)
    return combo


# ---------------------------------------------------------------------------
# Row UI updaters (all called via GLib.idle_add, return False)
# ---------------------------------------------------------------------------

def _set_whisper_not_downloaded(dialog, model: str) -> bool:
    row = dialog._whisper_rows.get(model)
    if row:
        row["status"].set_text("Not downloaded")
        row["btn"].set_label("Download")
        row["btn"].set_sensitive(True)
    return False


def _set_whisper_ready(dialog, model: str) -> bool:
    row = dialog._whisper_rows.get(model)
    if row:
        row["status"].set_text("Ready")
        row["btn"].set_label("Downloaded")
        row["btn"].set_sensitive(False)
    return False


def _set_whisper_error(dialog, model: str, msg: str) -> bool:
    row = dialog._whisper_rows.get(model)
    if row:
        row["status"].set_text(msg[:60])
        row["btn"].set_label("Retry")
        row["btn"].set_sensitive(True)
    return False


def _set_ollama_unreachable(dialog) -> bool:
    if dialog._ollama_status_label:
        dialog._ollama_status_label.set_text(
            "Ollama not reachable. Start it with: ollama serve"
        )
    for model in OLLAMA_MODELS:
        row = dialog._ollama_rows.get(model)
        if row:
            row["status"].set_text("Ollama offline")
            row["btn"].set_sensitive(True)
    return False


def _set_ollama_reachable(dialog) -> bool:
    if dialog._ollama_status_label:
        dialog._ollama_status_label.set_text("Ollama is running.")
    return False


def _set_ollama_not_downloaded(dialog, model: str) -> bool:
    row = dialog._ollama_rows.get(model)
    if row:
        row["status"].set_text("Not downloaded")
        row["btn"].set_label("Download")
        row["btn"].set_sensitive(True)
    return False


def _set_ollama_progress(dialog, model: str, text: str) -> bool:
    row = dialog._ollama_rows.get(model)
    if row:
        row["status"].set_text(text[:40])
        row["btn"].set_sensitive(False)
    return False


def _set_ollama_ready(dialog, model: str) -> bool:
    row = dialog._ollama_rows.get(model)
    if row:
        row["status"].set_text("Ready")
        row["btn"].set_label("Downloaded")
        row["btn"].set_sensitive(False)
    return False


def _set_ollama_error(dialog, model: str, msg: str) -> bool:
    row = dialog._ollama_rows.get(model)
    if row:
        row["status"].set_text(msg[:60])
        row["btn"].set_label("Retry")
        row["btn"].set_sensitive(True)
    return False


def _set_custom_pull_status(dialog, text: str) -> bool:
    dialog._ollama_custom_dl_btn.set_label(text[:25])
    return False


def _set_custom_pull_done(dialog, text: str) -> bool:
    dialog._ollama_custom_dl_btn.set_label("Pull Model")
    dialog._ollama_custom_dl_btn.set_sensitive(True)
    if dialog._ollama_status_label:
        dialog._ollama_status_label.set_text(text)
    return False


# ---------------------------------------------------------------------------
# Background status checks
# ---------------------------------------------------------------------------

def _refresh_local_model_statuses(dialog) -> None:
    threading.Thread(target=_check_whisper_statuses, args=(dialog,), daemon=True).start()
    threading.Thread(target=_check_ollama_statuses, args=(dialog,), daemon=True).start()


def _check_whisper_statuses(dialog) -> None:
    for model in WHISPER_MODELS:
        if _is_whisper_cached(model):
            GLib.idle_add(_set_whisper_ready, dialog, model)
        else:
            GLib.idle_add(_set_whisper_not_downloaded, dialog, model)


def _check_ollama_statuses(dialog) -> None:
    host = dialog._cfg.get("ollama_host", OLLAMA_DEFAULT_HOST)
    installed = _get_ollama_installed_models(host)
    if installed is None:
        GLib.idle_add(_set_ollama_unreachable, dialog)
        return
    GLib.idle_add(_set_ollama_reachable, dialog)
    for model in OLLAMA_MODELS:
        if _ollama_model_installed(model, installed):
            GLib.idle_add(_set_ollama_ready, dialog, model)
        else:
            GLib.idle_add(_set_ollama_not_downloaded, dialog, model)


# ---------------------------------------------------------------------------
# Download handlers
# ---------------------------------------------------------------------------

def _start_whisper_download(dialog, model: str) -> None:
    row = dialog._whisper_rows.get(model)
    if row:
        row["status"].set_text("Downloading\u2026")
        row["btn"].set_sensitive(False)
    threading.Thread(
        target=_do_whisper_download, args=(dialog, model), daemon=True
    ).start()


def _do_whisper_download(dialog, model: str) -> None:
    try:
        from faster_whisper import WhisperModel
        WhisperModel(model, device="cpu", compute_type="int8")
        GLib.idle_add(_set_whisper_ready, dialog, model)
    except Exception as exc:
        GLib.idle_add(_set_whisper_error, dialog, model, str(exc))


def _on_ollama_pull_custom(dialog, *_) -> None:
    model = dialog._ollama_model_combo.get_child().get_text().strip()
    if not model:
        return
    host = dialog._ollama_host_entry.get_text().strip() or OLLAMA_DEFAULT_HOST
    dialog._ollama_custom_dl_btn.set_label("Pulling\u2026")
    dialog._ollama_custom_dl_btn.set_sensitive(False)
    threading.Thread(
        target=_do_ollama_pull_custom, args=(dialog, model, host), daemon=True
    ).start()


def _do_ollama_pull_custom(dialog, model: str, host: str) -> None:
    """Fetch model info then pull. Updates button on completion."""
    try:
        payload = json.dumps({"name": model, "stream": True}).encode()
        req = urllib.request.Request(
            f"{host}/api/pull", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=None) as resp:
            while True:
                line = resp.readline()
                if not line:
                    break
                try:
                    data = json.loads(line.decode())
                except json.JSONDecodeError:
                    continue
                status = data.get("status", "")
                total = data.get("total", 0)
                completed = data.get("completed", 0)
                if total and completed:
                    pct = int(completed / total * 100)
                    status = f"{status} {pct}%"
                GLib.idle_add(_set_custom_pull_status, dialog, status)
                if data.get("status") == "success":
                    GLib.idle_add(_set_custom_pull_done, dialog, "Ready")
                    return
        GLib.idle_add(_set_custom_pull_done, dialog, "Ready")
    except Exception as exc:
        GLib.idle_add(_set_custom_pull_done, dialog, f"Error: {str(exc)[:40]}")


def _start_ollama_download(dialog, model: str, host: str) -> None:
    row = dialog._ollama_rows.get(model)
    if row:
        row["status"].set_text("Starting\u2026")
        row["btn"].set_sensitive(False)
    threading.Thread(
        target=_do_ollama_download, args=(dialog, model, host), daemon=True
    ).start()


def _do_ollama_download(dialog, model: str, host: str) -> None:
    payload = json.dumps({"name": model, "stream": True}).encode()
    req = urllib.request.Request(
        f"{host}/api/pull",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=None) as resp:
            while True:
                line = resp.readline()
                if not line:
                    break
                try:
                    data = json.loads(line.decode())
                except json.JSONDecodeError:
                    continue
                status_text = data.get("status", "")
                total = data.get("total", 0)
                completed = data.get("completed", 0)
                if total and completed:
                    pct = int(completed / total * 100)
                    status_text = f"{status_text} {pct}%"
                GLib.idle_add(_set_ollama_progress, dialog, model, status_text)
                if data.get("status") == "success":
                    GLib.idle_add(_set_ollama_ready, dialog, model)
                    return
        # If loop ended without "success", do a final status check
        host_val = dialog._ollama_host_entry.get_text().strip()
        installed = _get_ollama_installed_models(host_val)
        if installed and _ollama_model_installed(model, installed):
            GLib.idle_add(_set_ollama_ready, dialog, model)
        else:
            GLib.idle_add(_set_ollama_error, dialog, model, "Download may have failed")
    except Exception as exc:
        GLib.idle_add(_set_ollama_error, dialog, model, str(exc))


# ---------------------------------------------------------------------------
# Tab builder
# ---------------------------------------------------------------------------

def build_models_tab(cfg: dict, dialog) -> Gtk.Widget:
    outer_scroll = Gtk.ScrolledWindow()
    outer_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
    vbox.set_margin_top(16)
    vbox.set_margin_bottom(16)
    vbox.set_margin_start(16)
    vbox.set_margin_end(16)
    outer_scroll.add(vbox)

    config_note = Gtk.Label(xalign=0)
    config_note.set_markup(
        "These settings apply only when the corresponding provider is selected "
        "in the <b>General</b> tab (e.g. Gemini model is used when transcription "
        "provider is set to Google Gemini, Whisper/Ollama when Whisper or LiteLLM "
        "with ollama is selected)."
    )
    config_note.set_line_wrap(True)
    vbox.pack_start(config_note, False, False, 0)

    vbox.pack_start(Gtk.Separator(), False, False, 4)

    # --- Gemini section ---
    gemini_title = Gtk.Label(xalign=0)
    gemini_title.set_markup("<b>Gemini</b>")
    vbox.pack_start(gemini_title, False, False, 0)

    gemini_grid = Gtk.Grid(column_spacing=12, row_spacing=8)

    gemini_grid.attach(Gtk.Label(label="Model:", xalign=0), 0, 0, 1, 1)
    dialog._gemini_model_combo = _make_combo(
        GEMINI_MODELS, cfg.get("gemini_model", GEMINI_MODELS[0])
    )
    gemini_grid.attach(dialog._gemini_model_combo, 1, 0, 1, 1)

    gemini_note = Gtk.Label(
        label="Controls the model for direct Gemini transcription. "
              "LiteLLM-routed gemini/ calls use the model from the General tab.",
        xalign=0,
    )
    gemini_note.set_line_wrap(True)
    gemini_grid.attach(gemini_note, 0, 1, 2, 1)

    vbox.pack_start(gemini_grid, False, False, 0)

    vbox.pack_start(Gtk.Separator(), False, False, 4)

    # --- Whisper section ---
    whisper_title = Gtk.Label(xalign=0)
    whisper_title.set_markup("<b>Whisper</b>")
    vbox.pack_start(whisper_title, False, False, 0)

    whisper_model_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    whisper_model_box.pack_start(Gtk.Label(label="Whisper model:", xalign=0), False, False, 0)
    dialog._whisper_model_combo = _make_combo(
        WHISPER_MODELS, cfg.get("whisper_model", WHISPER_MODELS[0])
    )
    whisper_model_box.pack_start(dialog._whisper_model_combo, False, False, 0)
    vbox.pack_start(whisper_model_box, False, False, 0)

    whisper_note = Gtk.Label(
        label="Models are downloaded from HuggingFace and cached locally.",
        xalign=0,
    )
    whisper_note.set_line_wrap(True)
    vbox.pack_start(whisper_note, False, False, 0)

    whisper_grid = Gtk.Grid(column_spacing=12, row_spacing=8)
    for col, text in enumerate(["Model", "Size", "Note", "Status", ""]):
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup(f"<b>{text}</b>")
        whisper_grid.attach(lbl, col, 0, 1, 1)

    for r, model in enumerate(WHISPER_MODELS, start=1):
        info = WHISPER_MODEL_INFO.get(model, {})
        whisper_grid.attach(Gtk.Label(label=model, xalign=0), 0, r, 1, 1)
        whisper_grid.attach(Gtk.Label(label=info.get("size", ""), xalign=0), 1, r, 1, 1)
        whisper_grid.attach(Gtk.Label(label=info.get("note", ""), xalign=0), 2, r, 1, 1)

        status_lbl = Gtk.Label(label="Checking\u2026", xalign=0)
        whisper_grid.attach(status_lbl, 3, r, 1, 1)

        btn = Gtk.Button(label="Download")
        btn.connect("clicked", lambda _b, m=model: _start_whisper_download(dialog, m))
        whisper_grid.attach(btn, 4, r, 1, 1)

        dialog._whisper_rows[model] = {"status": status_lbl, "btn": btn}

    vbox.pack_start(whisper_grid, False, False, 0)

    vbox.pack_start(Gtk.Separator(), False, False, 4)

    # --- Ollama section ---
    ollama_title = Gtk.Label(xalign=0)
    ollama_title.set_markup("<b>Ollama</b>")
    vbox.pack_start(ollama_title, False, False, 0)

    ollama_config_grid = Gtk.Grid(column_spacing=12, row_spacing=8)

    ollama_config_grid.attach(Gtk.Label(label="Ollama model:", xalign=0), 0, 0, 1, 1)
    model_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
    dialog._ollama_model_combo = Gtk.ComboBoxText.new_with_entry()
    for m in OLLAMA_MODELS:
        dialog._ollama_model_combo.append_text(m)
    dialog._ollama_model_combo.get_child().set_text(
        cfg.get("ollama_model", OLLAMA_MODELS[0])
    )
    dialog._ollama_model_combo.set_hexpand(True)
    model_box.pack_start(dialog._ollama_model_combo, True, True, 0)
    dialog._ollama_custom_dl_btn = Gtk.Button(label="Pull Model")
    dialog._ollama_custom_dl_btn.connect(
        "clicked", lambda *_: _on_ollama_pull_custom(dialog)
    )
    model_box.pack_start(dialog._ollama_custom_dl_btn, False, False, 0)
    ollama_config_grid.attach(model_box, 1, 0, 1, 1)

    ollama_config_grid.attach(Gtk.Label(label="Ollama host:", xalign=0), 0, 1, 1, 1)
    dialog._ollama_host_entry = Gtk.Entry()
    dialog._ollama_host_entry.set_text(
        cfg.get("ollama_host", OLLAMA_DEFAULT_HOST)
    )
    dialog._ollama_host_entry.set_hexpand(True)
    ollama_config_grid.attach(dialog._ollama_host_entry, 1, 1, 1, 1)

    vbox.pack_start(ollama_config_grid, False, False, 0)

    dialog._ollama_status_label = Gtk.Label(
        label="Checking Ollama connection\u2026", xalign=0
    )
    vbox.pack_start(dialog._ollama_status_label, False, False, 0)

    ollama_note = Gtk.Label(
        label="Requires Ollama to be installed and running (ollama serve). "
              "Use ollama_chat/ prefix in LiteLLM for summarization.",
        xalign=0,
    )
    ollama_note.set_line_wrap(True)
    vbox.pack_start(ollama_note, False, False, 0)

    ollama_grid = Gtk.Grid(column_spacing=12, row_spacing=8)
    for col, text in enumerate(["Model", "Size", "Note", "Status", ""]):
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup(f"<b>{text}</b>")
        ollama_grid.attach(lbl, col, 0, 1, 1)

    for r, model in enumerate(OLLAMA_MODELS, start=1):
        info = OLLAMA_MODEL_INFO.get(model, {})
        ollama_grid.attach(Gtk.Label(label=model, xalign=0), 0, r, 1, 1)
        ollama_grid.attach(Gtk.Label(label=info.get("size", ""), xalign=0), 1, r, 1, 1)
        ollama_grid.attach(Gtk.Label(label=info.get("note", ""), xalign=0), 2, r, 1, 1)

        status_lbl = Gtk.Label(label="Checking\u2026", xalign=0)
        ollama_grid.attach(status_lbl, 3, r, 1, 1)

        btn = Gtk.Button(label="Download")
        btn.connect(
            "clicked",
            lambda _b, m=model: _start_ollama_download(
                dialog, m, dialog._ollama_host_entry.get_text().strip()
            ),
        )
        ollama_grid.attach(btn, 4, r, 1, 1)

        dialog._ollama_rows[model] = {"status": status_lbl, "btn": btn}

    vbox.pack_start(ollama_grid, False, False, 0)

    return outer_scroll
