import json
from datetime import datetime
from pathlib import Path

import pytest

from meeting_recorder.utils.meeting_scanner import (
    Meeting,
    scan_meetings,
    read_metadata,
    write_metadata,
    delete_meetings,
    rename_meeting_dir,
)


@pytest.fixture
def meetings_dir(tmp_path):
    """Create a sample meeting hierarchy."""
    # Meeting 1: 2026/March/18/14-30_Standup with notes
    m1 = tmp_path / "2026" / "March" / "18" / "14-30_Standup"
    m1.mkdir(parents=True)
    (m1 / "recording.mp3").write_bytes(b"fake audio")
    (m1 / "transcript.md").write_text("transcript text")
    (m1 / "notes.md").write_text("# Meeting Notes\n\nDiscussed stuff.")

    # Meeting 2: 2026/March/17/09-15 (no title, no notes)
    m2 = tmp_path / "2026" / "March" / "17" / "09-15"
    m2.mkdir(parents=True)
    (m2 / "recording.mp3").write_bytes(b"fake audio")
    (m2 / "transcript.md").write_text("transcript")

    # Meeting 3: 2026/February/28/16-00 with metadata
    m3 = tmp_path / "2026" / "February" / "28" / "16-00"
    m3.mkdir(parents=True)
    (m3 / "recording.mp3").write_bytes(b"fake audio")
    (m3 / "notes.md").write_text("notes")
    (m3 / "meeting.json").write_text(json.dumps({"title": "Sprint Planning"}))

    return tmp_path


def test_scan_meetings_finds_all(meetings_dir):
    meetings = scan_meetings(str(meetings_dir))
    assert len(meetings) == 3


def test_scan_meetings_sorted_newest_first(meetings_dir):
    meetings = scan_meetings(str(meetings_dir))
    assert meetings[0].time_label == "14-30_Standup"  # Mar 18
    assert meetings[1].time_label == "09-15"           # Mar 17
    assert meetings[2].time_label == "16-00"           # Feb 28


def test_scan_meetings_reads_metadata_title(meetings_dir):
    meetings = scan_meetings(str(meetings_dir))
    feb_meeting = [m for m in meetings if m.time_label == "16-00"][0]
    assert feb_meeting.title == "Sprint Planning"


def test_scan_meetings_detects_files(meetings_dir):
    meetings = scan_meetings(str(meetings_dir))
    m1 = [m for m in meetings if m.time_label == "14-30_Standup"][0]
    assert m1.has_audio is True
    assert m1.has_transcript is True
    assert m1.has_notes is True

    m2 = [m for m in meetings if m.time_label == "09-15"][0]
    assert m2.has_notes is False


def test_scan_meetings_parses_date(meetings_dir):
    meetings = scan_meetings(str(meetings_dir))
    m1 = [m for m in meetings if m.time_label == "14-30_Standup"][0]
    assert m1.date.year == 2026
    assert m1.date.month == 3
    assert m1.date.day == 18
    assert m1.date.hour == 14
    assert m1.date.minute == 30


def test_scan_meetings_empty_folder(tmp_path):
    meetings = scan_meetings(str(tmp_path))
    assert meetings == []


def test_read_metadata_existing(meetings_dir):
    path = meetings_dir / "2026" / "February" / "28" / "16-00"
    meta = read_metadata(path)
    assert meta["title"] == "Sprint Planning"


def test_read_metadata_missing(meetings_dir):
    path = meetings_dir / "2026" / "March" / "18" / "14-30_Standup"
    meta = read_metadata(path)
    assert meta == {}


def test_write_metadata_creates_file(tmp_path):
    write_metadata(tmp_path, {"title": "Test"})
    data = json.loads((tmp_path / "meeting.json").read_text())
    assert data["title"] == "Test"


def test_write_metadata_merges(tmp_path):
    (tmp_path / "meeting.json").write_text(json.dumps({"title": "Old", "extra": "keep"}))
    write_metadata(tmp_path, {"title": "New"})
    data = json.loads((tmp_path / "meeting.json").read_text())
    assert data["title"] == "New"
    assert data["extra"] == "keep"


def test_delete_meetings_removes_dirs(meetings_dir):
    meetings = scan_meetings(str(meetings_dir))
    to_delete = [m for m in meetings if m.time_label == "09-15"]
    succeeded, failures = delete_meetings(to_delete, str(meetings_dir))
    assert len(succeeded) == 1
    assert len(failures) == 0
    assert not to_delete[0].path.exists()


def test_delete_meetings_prunes_empty_parents(meetings_dir):
    """After deleting the only meeting in a day dir, the day/month/year dirs should be pruned."""
    meetings = scan_meetings(str(meetings_dir))
    feb_meeting = [m for m in meetings if m.time_label == "16-00"]
    delete_meetings(feb_meeting, str(meetings_dir))
    # February dir should be gone since it had only one meeting
    assert not (meetings_dir / "2026" / "February").exists()


def test_delete_meetings_preserves_output_root(meetings_dir):
    """Deleting all meetings should never delete the root output folder."""
    meetings = scan_meetings(str(meetings_dir))
    delete_meetings(meetings, str(meetings_dir))
    assert meetings_dir.exists()


def test_rename_meeting_dir(meetings_dir):
    meetings = scan_meetings(str(meetings_dir))
    m = [m for m in meetings if m.time_label == "09-15"][0]
    new_path = rename_meeting_dir(m, "Daily Standup")
    assert new_path.name == "09-15_Daily_Standup"
    assert new_path.exists()
    assert not m.path.exists()  # old path gone


def test_rename_meeting_dir_collision(meetings_dir):
    """If target name exists, append numeric suffix."""
    meetings = scan_meetings(str(meetings_dir))
    m = [m for m in meetings if m.time_label == "09-15"][0]
    # Create the target dir first to force collision
    (m.path.parent / "09-15_Collide").mkdir()
    new_path = rename_meeting_dir(m, "Collide")
    assert new_path.name == "09-15_Collide_2"
    assert new_path.exists()
