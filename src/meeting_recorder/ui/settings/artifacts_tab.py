"""Artifacts tab — choose which output files to keep after recording."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


# Each artifact: (config_key, label, description, condition_fn)
# condition_fn takes the dialog and returns whether this artifact is generated
_ARTIFACTS = [
    (
        "combined_audio",
        "Combined audio (recording.mp3)",
        "Merged mic + system audio in a single file",
        lambda d: True,
    ),
    (
        "mic_track",
        "Microphone track (recording_mic.mp3)",
        "Separate microphone recording",
        lambda d: d._cfg.get("separate_audio_tracks", True),
    ),
    (
        "system_track",
        "System audio track (recording_system.mp3)",
        "Separate system/desktop audio recording",
        lambda d: d._cfg.get("separate_audio_tracks", True),
    ),
    (
        "screen_recordings",
        "Screen recordings (screen-{monitor}.mp4)",
        "Per-monitor screen capture files",
        lambda d: d._cfg.get("screen_recording", False),
    ),
    (
        "merged_screen_audio",
        "Merged screen + audio (screen-{monitor}_merged.mp4)",
        "Screen recording combined with audio into one video",
        lambda d: d._cfg.get("screen_recording", False) and d._cfg.get("merge_screen_audio", False),
    ),
    (
        "transcript",
        "Transcript (transcript.md)",
        "Timestamped, speaker-labeled transcription",
        lambda d: True,
    ),
    (
        "notes",
        "Meeting notes (notes.md)",
        "AI-generated structured meeting summary",
        lambda d: True,
    ),
]


def build_artifacts_tab(cfg: dict, dialog) -> Gtk.Widget:
    """Build the Artifacts tab content."""
    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    vbox.set_margin_top(16)
    vbox.set_margin_bottom(16)
    vbox.set_margin_start(16)
    vbox.set_margin_end(16)

    header = Gtk.Label(xalign=0)
    header.set_markup(
        "<b>Output Artifacts</b>\n"
        "Select which files to keep after recording and processing.\n"
        "Unchecked artifacts will be automatically deleted."
    )
    header.set_line_wrap(True)
    vbox.pack_start(header, False, False, 0)

    vbox.pack_start(Gtk.Separator(), False, False, 4)

    keep = cfg.get("keep_artifacts", {})
    dialog._artifact_checks = {}

    for key, label, desc, condition_fn in _ARTIFACTS:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        row.set_margin_start(8)
        row.set_margin_top(4)

        generated = condition_fn(dialog)

        cb = Gtk.CheckButton(label=label)
        cb.set_active(keep.get(key, True))
        if not generated:
            cb.set_sensitive(False)
            cb.set_active(False)
        dialog._artifact_checks[key] = cb
        row.pack_start(cb, False, False, 0)

        note = Gtk.Label(xalign=0)
        status = desc if generated else f"{desc} (not generated with current settings)"
        note.set_markup(f'<span size="small" foreground="gray">{status}</span>')
        note.set_margin_start(24)
        row.pack_start(note, False, False, 0)

        vbox.pack_start(row, False, False, 0)

    vbox.pack_start(Gtk.Separator(), False, False, 8)

    # Summary
    dialog._artifacts_summary = Gtk.Label(xalign=0)
    dialog._artifacts_summary.set_line_wrap(True)
    vbox.pack_start(dialog._artifacts_summary, False, False, 0)

    _update_summary(dialog)

    for cb in dialog._artifact_checks.values():
        cb.connect("toggled", lambda *_: _update_summary(dialog))

    return vbox


def _update_summary(dialog) -> None:
    """Update the artifact count summary label."""
    checks = dialog._artifact_checks
    kept = sum(1 for cb in checks.values() if cb.get_active())
    total = sum(1 for cb in checks.values() if cb.get_sensitive())
    dialog._artifacts_summary.set_markup(
        f"<b>{kept}</b> of <b>{total}</b> generated artifacts will be kept."
    )


def collect_keep_artifacts(dialog) -> dict[str, bool]:
    """Read checkbox states into a config dict."""
    return {
        key: cb.get_active()
        for key, cb in dialog._artifact_checks.items()
    }
