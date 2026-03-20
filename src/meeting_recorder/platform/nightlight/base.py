from __future__ import annotations

from abc import ABC, abstractmethod


class NightLightInhibitor(ABC):
    """Abstract base for night light inhibition backends."""

    @abstractmethod
    def inhibit(self) -> None:
        """Pause the system night light. No-op if already inhibited."""
        ...

    @abstractmethod
    def uninhibit(self) -> None:
        """Resume the system night light. No-op if not inhibited."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this system's night light can be controlled.

        Checks whether the interface exists, NOT whether the user
        has night light currently enabled.
        """
        ...
