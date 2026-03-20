from meeting_recorder.platform.nightlight.none import NoOpNightLightInhibitor


def test_noop_inhibit_does_nothing():
    inhibitor = NoOpNightLightInhibitor()
    inhibitor.inhibit()  # should not raise


def test_noop_uninhibit_does_nothing():
    inhibitor = NoOpNightLightInhibitor()
    inhibitor.uninhibit()  # should not raise


def test_noop_is_available_returns_false():
    inhibitor = NoOpNightLightInhibitor()
    assert inhibitor.is_available() is False
