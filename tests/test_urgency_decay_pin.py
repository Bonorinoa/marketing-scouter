from src.scorer import URGENCY_FRESH_DROP, URGENCY_FRESH_HOURS, urgency_from_age_hours as u


def test_constants_pinned():
    assert URGENCY_FRESH_HOURS == 48.0 and URGENCY_FRESH_DROP == 0.4


def test_decay_is_linear_and_continuous():
    assert u(0) == 1.0
    assert u(24) == 0.8 and u(24.9) == 0.8
    assert u(47.999) == round(1 - 0.4 * 47 / 48, 4) and u(48) == 0.6
    assert u(1.5) > u(3.3) > u(23.9) and u(0.2) == u(0.9) == 1.0


def test_other_bands_unchanged():
    assert u(None) == 0.3 and u(5, evergreen=True) == 0.3
    assert u(100) == 0.6 and u(24 * 8) == 0.0 and u(-1) == 0.0
