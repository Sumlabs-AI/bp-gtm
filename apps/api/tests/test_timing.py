"""Timing multiplier: pre-event bump, post-event peak, fade, strongest phase wins."""

from datetime import UTC, datetime, timedelta

import pytest

from app.need.config import timing as config
from app.need.timing import AlertEvent, timing_for

NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)


def ended(event: str, days_ago: float, hours: float = 12) -> AlertEvent:
    end = NOW - timedelta(days=days_ago)
    return AlertEvent(event, end - timedelta(hours=hours), end)


def test_no_alerts_is_neutral():
    t = timing_for([], NOW)
    assert (t.multiplier, t.phase) == (1.0, "none")


def test_pre_event_while_in_effect_or_due_soon():
    ongoing = AlertEvent("Winter Storm Watch", NOW - timedelta(hours=2), NOW + timedelta(hours=10))
    due = AlertEvent("Ice Storm Warning", NOW + timedelta(hours=48), NOW + timedelta(hours=60))
    too_far = AlertEvent(
        "Ice Storm Warning", NOW + timedelta(hours=100), NOW + timedelta(hours=120)
    )
    assert timing_for([ongoing], NOW).phase == "pre_event"
    assert timing_for([due], NOW).multiplier == config.pre_event
    assert timing_for([too_far], NOW).phase == "none"


def test_peak_then_fade_after_a_storm():
    assert timing_for([ended("Severe Thunderstorm Warning", 3)], NOW).multiplier == config.peak
    assert timing_for([ended("Severe Thunderstorm Warning", config.peak_days)], NOW).phase == "peak"
    middle = (config.peak_days + config.fade_days) / 2
    t = timing_for([ended("Severe Thunderstorm Warning", middle)], NOW)
    assert t.phase == "fading"
    assert t.multiplier == pytest.approx(1 + (config.peak - 1) / 2)
    assert timing_for([ended("Severe Thunderstorm Warning", config.fade_days + 1)], NOW).phase == (
        "none"
    )


def test_major_event_lasts_longer():
    days = config.fade_days + 10
    assert timing_for([ended("Tornado Warning", days)], NOW).multiplier == 1.0
    t = timing_for([ended("Ice Storm Warning", days)], NOW)
    assert t.major and t.multiplier > 1.0


def test_watches_and_advisories_open_no_post_event_window():
    assert timing_for([ended("Winter Storm Watch", 5)], NOW).multiplier == 1.0
    assert timing_for([ended("Heat Advisory", 5)], NOW).multiplier == 1.0


def test_strongest_phase_wins_no_stacking():
    events = [
        ended("Tornado Warning", 5),
        ended("Ice Storm Warning", 10),
        AlertEvent("Heat Advisory", NOW - timedelta(hours=1), NOW + timedelta(hours=5)),
    ]
    t = timing_for(events, NOW)
    assert t.multiplier == config.peak
    assert t.phase == "peak"
