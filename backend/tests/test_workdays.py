"""Tests voor de werkdag-bewuste vervaldatumberekening."""
from datetime import datetime

import pytest

from app.workdays import add_working_days, compute_expires_at


def dt(y, m, d, hh=14, mm=30):
    return datetime(y, m, d, hh, mm)


def test_friday_plus_two_is_tuesday():
    # Uit de opdracht: klaar op vrijdag -> verloopt dinsdag (niet zondag).
    friday = dt(2026, 7, 24)  # vrijdag
    assert friday.weekday() == 4
    result = add_working_days(friday, 2)
    assert result.weekday() == 1  # dinsdag
    assert (result.year, result.month, result.day) == (2026, 7, 28)


def test_time_of_day_preserved():
    friday = dt(2026, 7, 24, 9, 15)
    result = add_working_days(friday, 2)
    assert (result.hour, result.minute) == (9, 15)


def test_midweek():
    wednesday = dt(2026, 7, 22)
    assert wednesday.weekday() == 2
    result = add_working_days(wednesday, 2)
    assert (result.month, result.day) == (7, 24)  # vrijdag


def test_thursday_crosses_weekend():
    thursday = dt(2026, 7, 23)
    assert thursday.weekday() == 3
    result = add_working_days(thursday, 2)
    assert result.weekday() == 0  # maandag
    assert (result.month, result.day) == (7, 27)


def test_zero_workdays_is_same_moment():
    d = dt(2026, 7, 22)
    assert add_working_days(d, 0) == d


def test_negative_raises():
    with pytest.raises(ValueError):
        add_working_days(dt(2026, 7, 22), -1)


def test_holidays_are_skipped():
    from datetime import date
    thursday = dt(2026, 7, 23)
    # Vrijdag 24 juli als feestdag -> +1 werkdag landt op maandag 27.
    result = add_working_days(thursday, 1, extra_holidays=[date(2026, 7, 24)])
    assert (result.month, result.day) == (7, 27)


def test_compute_expires_at_delegates():
    finished = dt(2026, 7, 24)
    assert compute_expires_at(finished, 2) == add_working_days(finished, 2)
