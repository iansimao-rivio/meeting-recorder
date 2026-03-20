"""MeetingSession — composable post-recording lifecycle.

Owns the full pipeline: media ingestion, transcription, summarization,
auto-title, and artifact cleanup. Used by both live recording and
Transcribe File entry points.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..config.defaults import RECORDING_QUALITIES

logger = logging.getLogger(__name__)


@dataclass
class SessionResult:
    """Returned via on_done when the session completes successfully."""
    meeting_dir: Path
    audio_path: Path
    transcript_path: Path | None
    notes_path: Path | None
    title: str | None


class MeetingSession:
    """Composable post-recording lifecycle.

    Exactly one of ``source_path`` (Transcribe File) or ``audio_path``
    (live recording, already in meeting dir) must be provided.
    """

    def __init__(
        self,
        config: dict,
        source_path: Path | None = None,
        audio_path: Path | None = None,
        on_status: Callable[[str], None] = lambda m: None,
        on_done: Callable[[SessionResult], None] = lambda r: None,
        on_error: Callable[[str], None] = lambda e: None,
    ) -> None:
        if (source_path is None) == (audio_path is None):
            raise ValueError(
                "Exactly one of source_path or audio_path must be provided"
            )
        self._config = config
        self._source_path = source_path
        self._audio_path = audio_path
        self._on_status = on_status
        self._on_done = on_done
        self._on_error = on_error
        self._cancelled = False
        self._ffmpeg_proc: subprocess.Popen | None = None

    def cancel(self) -> None:
        """Request cancellation. Checked between steps; kills ffmpeg if active."""
        self._cancelled = True
        proc = self._ffmpeg_proc
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass

    def run(self) -> None:
        """Run the full session lifecycle. Call from a background thread."""
        try:
            self._run_impl()
        except Exception as exc:
            if not self._cancelled:
                logger.error("MeetingSession failed: %s", exc, exc_info=True)
                self._on_error(str(exc))

    def _run_impl(self) -> None:
        if self._cancelled:
            return

        # Step 1: Ingest (Transcribe File only)
        if self._source_path is not None:
            audio_path = self._ingest_audio()
            if audio_path is None:
                return  # error already reported
        else:
            audio_path = self._audio_path

        meeting_dir = audio_path.parent
        transcript_path = meeting_dir / "transcript.md"
        notes_path = meeting_dir / "notes.md"

        if self._cancelled:
            return

        # Step 2: Run pipeline
        self._on_status("Transcribing\u2026")
        from .pipeline import Pipeline
        pipeline = Pipeline(
            config=self._config,
            audio_path=audio_path,
            transcript_path=transcript_path,
            notes_path=notes_path,
            on_status=self._on_status,
        )
        pipeline.run()

        if self._cancelled:
            return

        # Step 3: Auto-title (may rename meeting_dir)
        title = None
        if self._config.get("auto_title", False):
            title, new_dir = self._auto_title(meeting_dir, notes_path, audio_path)
            if new_dir and new_dir != meeting_dir:
                audio_path = new_dir / audio_path.name
                meeting_dir = new_dir
                transcript_path = new_dir / "transcript.md"
                notes_path = new_dir / "notes.md"

        if self._cancelled:
            return

        # Step 4: Cleanup artifacts
        self._cleanup_artifacts(meeting_dir)

        # Done
        self._on_done(SessionResult(
            meeting_dir=meeting_dir,
            audio_path=audio_path,
            transcript_path=transcript_path if transcript_path.exists() else None,
            notes_path=notes_path if notes_path.exists() else None,
            title=title,
        ))

    def _ingest_audio(self) -> Path | None:
        """Convert external media file to mp3 in a new meeting directory."""
        self._on_status("Converting media\u2026")

        if not shutil.which("ffmpeg"):
            self._on_error(
                "ffmpeg is required for Transcribe File. "
                "Install it with your package manager "
                "(e.g., sudo pacman -S ffmpeg)"
            )
            return None

        # Create meeting directory
        from ..utils.filename import output_paths
        output_folder = self._config.get("output_folder", "~/meetings")
        audio_path, transcript_path, notes_path = output_paths(output_folder)
        meeting_dir = audio_path.parent

        # Convert to mp3
        quality_key = self._config.get("recording_quality", "high")
        _, q_value = RECORDING_QUALITIES.get(quality_key, ("High", "5"))

        try:
            cmd = [
                "ffmpeg", "-i", str(self._source_path),
                "-vn", "-q:a", q_value,
                "-y", str(audio_path),
            ]
            self._ffmpeg_proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            _, stderr = self._ffmpeg_proc.communicate()
            returncode = self._ffmpeg_proc.returncode
            self._ffmpeg_proc = None

            if self._cancelled:
                self._cleanup_meeting_dir(meeting_dir, output_folder)
                return None

            if returncode != 0:
                raise RuntimeError(
                    f"ffmpeg exited with code {returncode}: "
                    f"{stderr.decode(errors='replace')[:200]}"
                )

            if not audio_path.exists() or audio_path.stat().st_size == 0:
                raise RuntimeError("ffmpeg produced empty output")

        except Exception as exc:
            self._cleanup_meeting_dir(meeting_dir, output_folder)
            if not self._cancelled:
                self._on_error(f"Media conversion failed: {exc}")
            return None

        return audio_path

    def _auto_title(
        self, meeting_dir: Path, notes_path: Path, audio_path: Path,
    ) -> tuple[str | None, Path | None]:
        """Generate AI title from notes if enabled and no user title.

        Returns (title, new_meeting_dir) — new_meeting_dir is the renamed
        path if rename succeeded, else None.
        """
        if not self._config.get("auto_title", False):
            return None, None

        folder_name = meeting_dir.name
        if not re.match(r"^\d{2}-\d{2}$", folder_name):
            return None, None  # user already provided a title

        if not notes_path.exists():
            return None, None

        self._on_status("Generating title\u2026")

        try:
            from ..ui.meeting_explorer import MeetingExplorer
            from ..utils.meeting_scanner import (
                Meeting, rename_meeting_dir, write_metadata,
            )

            notes_text = notes_path.read_text(encoding="utf-8")
            provider = MeetingExplorer._build_title_provider(self._config)
            title = provider.summarize(notes_text)
            title = title.strip().strip('"').strip("'").strip()
            if not title:
                return None, None

            write_metadata(meeting_dir, {
                "title": title,
                "generated_at": datetime.now().isoformat(),
            })

            meeting = Meeting(
                path=meeting_dir,
                time_label=meeting_dir.name,
                date=datetime.now(),
                title=title,
                has_notes=True,
                has_transcript=(meeting_dir / "transcript.md").exists(),
                has_audio=True,
                duration_seconds=None,
            )
            new_path = rename_meeting_dir(meeting, title)
            logger.info("Auto-titled meeting: %s -> %s", folder_name, new_path.name)

            return title, new_path
        except Exception as exc:
            logger.warning("Auto-title failed: %s", exc)
            return None, None

    def _cleanup_artifacts(self, meeting_dir: Path) -> None:
        """Delete artifacts the user chose not to keep."""
        keep = self._config.get("keep_artifacts", {})
        if not meeting_dir.is_dir():
            return

        artifact_patterns = {
            "combined_audio": ["recording.mp3"],
            "mic_track": ["recording_mic.mp3"],
            "system_track": ["recording_system.mp3"],
            "screen_recordings": ["screen-*.mp4"],
            "merged_screen_audio": ["screen-*_merged.mp4"],
            "transcript": ["transcript.md", "*_transcript.md"],
            "notes": ["notes.md", "*_notes.md"],
        }

        for key, patterns in artifact_patterns.items():
            if keep.get(key, True):
                continue
            for pat in patterns:
                for f in meeting_dir.glob(pat):
                    if key == "screen_recordings" and "_merged" in f.name:
                        continue
                    try:
                        f.unlink()
                        logger.info("Cleaned up artifact: %s", f)
                    except Exception as exc:
                        logger.warning("Failed to delete %s: %s", f, exc)

    def _cleanup_meeting_dir(self, meeting_dir: Path, output_folder: str) -> None:
        """Remove orphaned meeting dir and prune empty ancestors up to output root."""
        try:
            output_root = Path(os.path.expanduser(output_folder)).resolve()
            if meeting_dir.exists():
                shutil.rmtree(meeting_dir)
            # Prune empty parent dirs up to output root
            parent = meeting_dir.parent
            while parent != output_root and parent.is_dir():
                try:
                    parent.rmdir()  # only succeeds if empty
                    parent = parent.parent
                except OSError:
                    break
        except Exception as exc:
            logger.warning("Failed to clean up meeting dir: %s", exc)
