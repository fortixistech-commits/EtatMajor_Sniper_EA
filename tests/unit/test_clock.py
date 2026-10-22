"""Simulation clock tests."""

from __future__ import annotations

import pytest

from etatmajor.core.clock import SimClock, ns_to_iso


def test_clock_starts_at_zero():
    assert SimClock().now() == 0


def test_clock_moves_forward():
    clock = SimClock().advance_to(100).advance_to(250)
    assert clock.now() == 250


def test_clock_accepts_the_same_timestamp():
    clock = SimClock().advance_to(100).advance_to(100)
    assert clock.now() == 100


def test_clock_refuses_to_move_backwards():
    clock = SimClock().advance_to(100)
    with pytest.raises(ValueError):
        clock.advance_to(99)


def test_iso_conversion():
    assert ns_to_iso(1_767_571_200_000_000_000) == "2026-01-05T00:00:00+00:00"
