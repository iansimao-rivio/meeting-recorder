import pytest
from meeting_recorder.platform.nightlight.base import NightLightInhibitor


def test_nightlight_inhibitor_is_abstract():
    with pytest.raises(TypeError):
        NightLightInhibitor()
