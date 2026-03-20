"""
Settings dialog — thin shell that delegates to per-tab builders.

Each tab lives in settings/<tab>_tab.py and exposes a build_<tab>_tab(cfg, dialog)
function that creates widgets and stores them on the dialog object so _save()
can read them back.
"""

from __future__ import annotations

import logging

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from ..config import settings
from ..config.defaults import (
    GEMINI_MODELS,
    GEMINI_TRANSCRIPTION_PROMPT,
    OLLAMA_DEFAULT_HOST,
    OLLAMA_MODELS,
    SUMMARIZATION_PROMPT,
    WHISPER_MODELS,
)
from ..utils.autostart import update_autostart

from .settings.general_tab import build_general_tab, update_litellm_visibility
from .settings.platform_tab import build_platform_tab
from .settings.models_tab import build_models_tab, _refresh_local_model_statuses
from .settings.api_keys_tab import build_api_keys_tab, collect_api_keys
from .settings.prompts_tab import build_prompts_tab
from .settings.artifacts_tab import build_artifacts_tab, collect_keep_artifacts
from .settings.tray_tab import build_tray_tab

logger = logging.getLogger(__name__)


class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, nightlight_available: bool = False) -> None:
        super().__init__(
            title="Settings",
            transient_for=parent,
            modal=True,
            use_header_bar=True,
        )
        self.add_buttons(
            "Close", Gtk.ResponseType.CLOSE,
            "Save", Gtk.ResponseType.APPLY,
        )
        self.set_default_size(620, 680)

        self._cfg = settings.load()

        # Model download tracking
        self._whisper_rows: dict[str, dict] = {}
        self._ollama_rows: dict[str, dict] = {}
        self._ollama_status_label: Gtk.Label | None = None

        # API key rows
        self._api_key_rows: list[dict] = []
        self._api_keys_box: Gtk.Box | None = None
        self._api_keys_error_label: Gtk.Label | None = None

        self._nightlight_available = nightlight_available

        self._build_ui()

        self.connect("response", self._on_response)

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        notebook = Gtk.Notebook()
        self.get_content_area().add(notebook)

        notebook.append_page(build_general_tab(self._cfg, self), Gtk.Label(label="General"))
        notebook.append_page(
            build_platform_tab(self._cfg, self, nightlight_available=self._nightlight_available),
            Gtk.Label(label="Platform"),
        )
        notebook.append_page(build_models_tab(self._cfg, self), Gtk.Label(label="Model Config"))
        notebook.append_page(build_api_keys_tab(self._cfg, self), Gtk.Label(label="API Keys"))
        notebook.append_page(build_prompts_tab(self._cfg, self), Gtk.Label(label="Prompts"))
        notebook.append_page(build_artifacts_tab(self._cfg, self), Gtk.Label(label="Artifacts"))
        notebook.append_page(build_tray_tab(self._cfg, self), Gtk.Label(label="Tray"))

        self.show_all()

        # Hide litellm model rows if not selected
        update_litellm_visibility(self)

        # Kick off background status checks after show_all so labels are realized
        _refresh_local_model_statuses(self)

    # ------------------------------------------------------------------

    def _on_response(self, dialog: Gtk.Dialog, response_id: int) -> None:
        if response_id == Gtk.ResponseType.APPLY:
            self._save()
            self.stop_emission_by_name("response")  # prevent dialog close

    def _save(self) -> None:
        # Collect and validate API keys first
        api_keys = collect_api_keys(self)
        if api_keys is None:
            return  # duplicates found, save blocked

        cfg = settings.load()

        # General tab
        cfg["transcription_provider"] = self._ts_combo.get_active_id() or "gemini"
        cfg["summarization_provider"] = self._ss_combo.get_active_id() or "litellm"
        cfg["litellm_transcription_model"] = self._litellm_ts_combo.get_child().get_text().strip() or "groq/whisper-large-v3"
        cfg["litellm_summarization_model"] = self._litellm_ss_combo.get_child().get_text().strip() or "gemini/gemini-2.5-flash"
        cfg["output_folder"] = self._folder_entry.get_text().strip() or "~/meetings"
        cfg["recording_quality"] = self._quality_combo.get_active_id() or "high"
        cfg["llm_request_timeout_minutes"] = int(self._timeout_combo.get_active_id() or "5")
        cfg["auto_title"] = self._auto_title_switch.get_active()
        cfg["tray_default_action"] = self._tray_default_combo.get_active_id() or "record_headphones"
        cfg["tray_recording_action"] = self._tray_recording_combo.get_active_id() or "stop"
        cfg["call_detection_enabled"] = self._detection_switch.get_active()
        cfg["start_at_startup"] = self._startup_switch.get_active()

        # Platform tab
        cfg["audio_backend"] = self._audio_backend_combo.get_active_id() or "pipewire"
        cfg["separate_audio_tracks"] = self._separate_tracks_switch.get_active()
        cfg["screen_recording"] = self._screen_recording_switch.get_active()
        cfg["screen_recorder"] = self._screen_recorder_combo.get_active_id() or "none"
        cfg["monitors"] = self._get_selected_monitors()
        cfg["merge_screen_audio"] = self._merge_screen_check.get_active()
        cfg["screen_fps"] = int(self._fps_spin.get_value())
        cfg["inhibit_nightlight"] = self._inhibit_nl_switch.get_active()

        # Models tab
        cfg["gemini_model"] = self._gemini_model_combo.get_active_id() or GEMINI_MODELS[0]
        cfg["whisper_model"] = self._whisper_model_combo.get_active_id() or WHISPER_MODELS[0]
        cfg["ollama_model"] = self._ollama_model_combo.get_child().get_text().strip() or OLLAMA_MODELS[0]
        cfg["ollama_host"] = self._ollama_host_entry.get_text().strip() or OLLAMA_DEFAULT_HOST

        # API Keys
        cfg["api_keys"] = api_keys

        # Artifacts
        cfg["keep_artifacts"] = collect_keep_artifacts(self)

        # Prompts
        ts_buf = self._ts_prompt_view.get_buffer()
        ts_text = ts_buf.get_text(ts_buf.get_start_iter(), ts_buf.get_end_iter(), False).strip()
        cfg["transcription_prompt"] = (
            "" if ts_text == GEMINI_TRANSCRIPTION_PROMPT.strip() else ts_text
        )

        ss_buf = self._ss_prompt_view.get_buffer()
        ss_text = ss_buf.get_text(ss_buf.get_start_iter(), ss_buf.get_end_iter(), False).strip()
        cfg["summarization_prompt"] = (
            "" if ss_text == SUMMARIZATION_PROMPT.strip() else ss_text
        )

        try:
            settings.save(cfg)
            settings.inject_api_keys(cfg)
            update_autostart(cfg["start_at_startup"])
            self._flash_saved()
        except Exception as exc:
            logger.error("Failed to save settings: %s", exc)

    def _flash_saved(self) -> None:
        btn = self.get_widget_for_response(Gtk.ResponseType.APPLY)
        if btn:
            btn.set_label("Saved!")
            btn.set_sensitive(False)
            GLib.timeout_add(1200, self._reset_save_btn, btn)

    def _reset_save_btn(self, btn: Gtk.Widget) -> bool:
        btn.set_label("Save")
        btn.set_sensitive(True)
        return False
