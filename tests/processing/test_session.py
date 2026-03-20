"""Tests for MeetingSession — composable post-recording lifecycle."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from meeting_recorder.processing.session import MeetingSession, SessionResult


class TestMeetingSessionValidation:
    """Constructor invariant: exactly one of source_path/audio_path."""

    def test_both_paths_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Exactly one"):
            MeetingSession(
                config={},
                source_path=tmp_path / "a.mp4",
                audio_path=tmp_path / "b.mp3",
                on_status=lambda m: None,
                on_done=lambda r: None,
                on_error=lambda e: None,
            )

    def test_neither_path_raises(self):
        with pytest.raises(ValueError, match="Exactly one"):
            MeetingSession(
                config={},
                on_status=lambda m: None,
                on_done=lambda r: None,
                on_error=lambda e: None,
            )


class TestMeetingSessionLiveRecording:
    """Entry point: audio_path already in meeting dir."""

    @patch("meeting_recorder.processing.pipeline.Pipeline")
    def test_run_calls_pipeline_and_done(self, MockPipeline, tmp_path):
        audio = tmp_path / "2026" / "March" / "19" / "14-30" / "recording.mp3"
        audio.parent.mkdir(parents=True)
        audio.write_text("fake audio")
        transcript = audio.parent / "transcript.md"
        notes = audio.parent / "notes.md"

        done_cb = MagicMock()
        status_cb = MagicMock()

        session = MeetingSession(
            config={"auto_title": False, "keep_artifacts": {}},
            audio_path=audio,
            on_status=status_cb,
            on_done=done_cb,
            on_error=lambda e: None,
        )
        session.run()

        MockPipeline.assert_called_once()
        MockPipeline.return_value.run.assert_called_once()
        done_cb.assert_called_once()
        result = done_cb.call_args[0][0]
        assert isinstance(result, SessionResult)
        assert result.meeting_dir == audio.parent


class TestMeetingSessionTranscribeFile:
    """Entry point: source_path is external media file."""

    @patch("meeting_recorder.processing.pipeline.Pipeline")
    @patch("shutil.which", return_value="/usr/bin/ffmpeg")
    def test_ingest_creates_meeting_dir_and_converts(
        self, mock_which, MockPipeline, tmp_path
    ):
        source = tmp_path / "video.mp4"
        source.write_text("fake video")
        output_folder = str(tmp_path / "meetings")

        done_cb = MagicMock()
        status_cb = MagicMock()

        # Mock Popen to simulate ffmpeg creating the output file
        def fake_popen(cmd, **kwargs):
            output_path = Path(cmd[-1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("fake audio")
            mock_proc = MagicMock()
            mock_proc.communicate.return_value = (b"", b"")
            mock_proc.returncode = 0
            return mock_proc

        with patch("subprocess.Popen", side_effect=fake_popen) as mock_popen:
            session = MeetingSession(
                config={
                    "output_folder": output_folder,
                    "recording_quality": "high",
                    "auto_title": False,
                    "keep_artifacts": {},
                },
                source_path=source,
                on_status=status_cb,
                on_done=done_cb,
                on_error=lambda e: None,
            )
            session.run()

            mock_popen.assert_called_once()
            cmd = mock_popen.call_args[0][0]
            assert "ffmpeg" in cmd[0]
            assert "-vn" in cmd

        status_cb.assert_any_call("Converting media\u2026")
        done_cb.assert_called_once()
        result = done_cb.call_args[0][0]
        assert isinstance(result, SessionResult)
        assert result.audio_path.name == "recording.mp3"

    def test_missing_ffmpeg_calls_on_error(self, tmp_path):
        source = tmp_path / "video.mp4"
        source.write_text("fake video")

        error_cb = MagicMock()

        with patch("shutil.which", return_value=None):
            session = MeetingSession(
                config={"output_folder": str(tmp_path / "meetings")},
                source_path=source,
                on_status=lambda m: None,
                on_done=lambda r: None,
                on_error=error_cb,
            )
            session.run()

        error_cb.assert_called_once()
        assert "ffmpeg" in error_cb.call_args[0][0].lower()

    @patch("shutil.which", return_value="/usr/bin/ffmpeg")
    @patch("subprocess.Popen", side_effect=Exception("conversion failed"))
    def test_ffmpeg_failure_cleans_up_meeting_dir(
        self, mock_popen, mock_which, tmp_path
    ):
        source = tmp_path / "video.mp4"
        source.write_text("fake video")
        output_folder = tmp_path / "meetings"

        error_cb = MagicMock()

        session = MeetingSession(
            config={
                "output_folder": str(output_folder),
                "recording_quality": "high",
            },
            source_path=source,
            on_status=lambda m: None,
            on_done=lambda r: None,
            on_error=error_cb,
        )
        session.run()

        error_cb.assert_called_once()
        if output_folder.exists():
            assert not any(output_folder.rglob("recording.mp3"))


class TestMeetingSessionCancellation:
    """cancel() stops processing between steps."""

    @patch("meeting_recorder.processing.pipeline.Pipeline")
    def test_cancel_before_pipeline_skips_it(self, MockPipeline, tmp_path):
        audio = tmp_path / "recording.mp3"
        audio.write_text("fake")

        done_cb = MagicMock()
        error_cb = MagicMock()

        session = MeetingSession(
            config={"auto_title": False, "keep_artifacts": {}},
            audio_path=audio,
            on_status=lambda m: None,
            on_done=done_cb,
            on_error=error_cb,
        )
        session.cancel()
        session.run()

        MockPipeline.return_value.run.assert_not_called()
        done_cb.assert_not_called()
