"""Werkdag-bewuste berekening van de vervaldatum.

De bewaartermijn is N *werkdagen* ná het afronden van de verwerking. Weekenden
(zaterdag/zondag) tellen niet mee. Voorbeeld uit de opdracht:
    klaar op vrijdag + 2 werkdagen -> verloopt dinsdag (niet zondag).

Feestdagen worden bewust NIET meegenomen (de opdracht noemt alleen weekenden);
`extra_holidays` maakt uitbreiding mogelijk zonder de kernlogica te wijzigen.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable

SATURDAY = 5
SUNDAY = 6


def add_working_days(
    start: datetime,
    n: int,
    extra_holidays: Iterable[date] | None = None,
) -> datetime:
    """Tel `n` werkdagen op bij `start`, met behoud van tijdstip.

    Alleen dagen die op een werkdag vallen tellen af tegen `n`. Het tijdstip
    (uur/minuut) van `start` blijft ongewijzigd.
    """
    if n < 0:
        raise ValueError("n moet >= 0 zijn")
    holidays = set(extra_holidays or ())
    result = start
    added = 0
    while added < n:
        result = result + timedelta(days=1)
        if result.weekday() >= SATURDAY:  # zaterdag of zondag
            continue
        if result.date() in holidays:
            continue
        added += 1
    return result


def compute_expires_at(
    finished_at: datetime,
    workdays: int,
    extra_holidays: Iterable[date] | None = None,
) -> datetime:
    """Vervaldatum = afgerond-op-moment + `workdays` werkdagen."""
    return add_working_days(finished_at, workdays, extra_holidays)
