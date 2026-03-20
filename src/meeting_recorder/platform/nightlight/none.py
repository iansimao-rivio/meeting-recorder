from __future__ import annotations

from .base import NightLightInhibitor


class NoOpNightLightInhibitor(NightLightInhibitor):
    """No-op night light inhibitor. Used when no system night light is detected."""

    def inhibit(self) -> None:
        pass

    def uninhibit(self) -> None:
        pass

    def is_available(self) -> bool:
        return False
