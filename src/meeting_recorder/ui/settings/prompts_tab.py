"""Prompts settings tab — transcription and summarization prompt editors."""

from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ...config.defaults import (
    GEMINI_TRANSCRIPTION_PROMPT,
    SUMMARIZATION_PROMPT,
)


def _reset_prompt(dialog, which: str) -> None:
    if which == "transcription":
        dialog._ts_prompt_view.get_buffer().set_text(GEMINI_TRANSCRIPTION_PROMPT)
    else:
        dialog._ss_prompt_view.get_buffer().set_text(SUMMARIZATION_PROMPT)


def build_prompts_tab(cfg: dict, dialog) -> Gtk.Widget:
    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    vbox.set_margin_top(16)
    vbox.set_margin_bottom(16)
    vbox.set_margin_start(16)
    vbox.set_margin_end(16)

    # Transcription prompt
    ts_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    ts_label = Gtk.Label(xalign=0)
    ts_label.set_markup("<b>Transcription Prompt</b>")
    ts_label.set_hexpand(True)
    ts_reset = Gtk.Button(label="Reset to default")
    ts_reset.connect("clicked", lambda *_: _reset_prompt(dialog, "transcription"))
    ts_header.pack_start(ts_label, True, True, 0)
    ts_header.pack_start(ts_reset, False, False, 0)
    vbox.pack_start(ts_header, False, False, 0)

    prompt_note = Gtk.Label(
        label="Note: Transcription prompts apply to Gemini direct provider only. "
              "Whisper, ElevenLabs, and LiteLLM transcription providers do not use custom prompts.",
        xalign=0,
    )
    prompt_note.set_line_wrap(True)
    vbox.pack_start(prompt_note, False, False, 0)

    dialog._ts_prompt_view = Gtk.TextView()
    dialog._ts_prompt_view.set_wrap_mode(Gtk.WrapMode.WORD)
    dialog._ts_prompt_view.set_monospace(True)
    stored_ts = cfg.get("transcription_prompt") or GEMINI_TRANSCRIPTION_PROMPT
    dialog._ts_prompt_view.get_buffer().set_text(stored_ts)
    ts_scroll = Gtk.ScrolledWindow()
    ts_scroll.set_min_content_height(180)
    ts_scroll.set_vexpand(True)
    ts_scroll.add(dialog._ts_prompt_view)
    vbox.pack_start(ts_scroll, True, True, 0)

    vbox.pack_start(Gtk.Separator(), False, False, 4)

    # Summarization prompt
    ss_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    ss_label = Gtk.Label(xalign=0)
    ss_label.set_markup("<b>Summarization Prompt</b>")
    ss_label.set_hexpand(True)
    ss_reset = Gtk.Button(label="Reset to default")
    ss_reset.connect("clicked", lambda *_: _reset_prompt(dialog, "summarization"))
    ss_header.pack_start(ss_label, True, True, 0)
    ss_header.pack_start(ss_reset, False, False, 0)
    vbox.pack_start(ss_header, False, False, 0)

    dialog._ss_prompt_view = Gtk.TextView()
    dialog._ss_prompt_view.set_wrap_mode(Gtk.WrapMode.WORD)
    dialog._ss_prompt_view.set_monospace(True)
    stored_ss = cfg.get("summarization_prompt") or SUMMARIZATION_PROMPT
    dialog._ss_prompt_view.get_buffer().set_text(stored_ss)
    ss_scroll = Gtk.ScrolledWindow()
    ss_scroll.set_min_content_height(180)
    ss_scroll.set_vexpand(True)
    ss_scroll.add(dialog._ss_prompt_view)
    vbox.pack_start(ss_scroll, True, True, 0)

    return vbox
