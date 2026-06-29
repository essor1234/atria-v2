from atria.models.config import AppConfig


def test_simple_mode_defaults_true():
    assert AppConfig().simple_mode is True


def test_simple_mode_can_be_disabled():
    assert AppConfig(simple_mode=False).simple_mode is False
