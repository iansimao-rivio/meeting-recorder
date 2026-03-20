from __future__ import annotations

from abc import ABC, abstractmethod


class Notifier(ABC):
    """Abstract base for desktop notifications."""

    @abstractmethod
    def notify(
        self,
        summary: str,
        body: str = "",
        icon: str = "meeting-recorder",
    ) -> None:
        """Send a desktop notification."""
        ...
