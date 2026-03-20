from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


class TrayBackend(ABC):
    """Abstract base for system tray implementations."""

    def __init__(self) -> None:
        self._on_activate: Callable[[], None] | None = None

    @abstractmethod
    def update(self, recording_state: str, jobs: list) -> None:
        """Update tray icon and menu.

        Args:
            recording_state: "idle" | "recording" | "paused"
            jobs: list of (label: str, cancel_fn: Callable) tuples
                  Processing icon shown when bool(jobs) is True and not recording.
        """
        ...

    def set_on_activate(self, callback) -> None:
        """Set callback for tray activation (single-click / default action)."""
        self._on_activate = callback
