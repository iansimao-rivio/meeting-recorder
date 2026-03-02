"""ffmpeg command builder for mixing mic + system audio into MP3."""

from __future__ import annotations

from pathlib import Path


def build_ffmpeg_command(
    source: str,
    monitor: str,
    output_path: str | Path,
) -> list[str]:
    """
    Build ffmpeg command that reads two PulseAudio sources into a stereo MP3.

    Channel layout:
      Left  (ch 0) = mic input    — the local speaker
      Right (ch 1) = system audio — remote participants

    amerge produces a true stereo file with separate channels, preserving
    speaker separation for AI transcription.
    """
    # highpass=f=80  : cut sub-80 Hz rumble that makes mics sound muffled
    # No denoiser: afftdn/anlmdn are both too slow for real-time use and cause
    # the input thread queue to fill, making ffmpeg drop packets and produce a
    # file shorter than the wall-clock recording duration.
    filter_str = "[0:a]highpass=f=80[mic];[mic][1:a]amerge=inputs=2[out]"
    return [
        "ffmpeg",
        "-hide_banner",
        "-y",
        # thread_queue_size buffers packets between the PulseAudio input thread and
        # the filter/encode thread. Without it the queue fills up and ffmpeg silently
        # drops audio packets, producing a file shorter than the wall-clock recording.
        "-thread_queue_size", "4096",
        "-f", "pulse", "-i", source,
        "-thread_queue_size", "4096",
        "-f", "pulse", "-i", monitor,
        "-filter_complex", filter_str,
        "-map", "[out]",
        "-acodec", "libmp3lame",
        "-q:a", "2",
        str(output_path),
    ]


def build_split_command(
    input_path: str | Path,
    segment_path_template: str,
    segment_duration_secs: int = 1200,  # 20 minutes
) -> list[str]:
    """
    Build ffmpeg command to split a large audio file into segments.
    segment_path_template should contain %03d, e.g. /tmp/chunk_%03d.mp3
    """
    return [
        "ffmpeg",
        "-y",
        "-i", str(input_path),
        "-f", "segment",
        "-segment_time", str(segment_duration_secs),
        "-c", "copy",
        str(segment_path_template),
    ]
