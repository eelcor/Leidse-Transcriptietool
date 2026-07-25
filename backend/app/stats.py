"""Anonieme statistieken: events wegschrijven en aggregeren voor het dashboard.

Alle gegevens zijn geaggregeerd-veilig (geen persoonsgegevens). Aggregatie gebeurt
in Python (DB-agnostisch: werkt op Postgres én SQLite).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import Session, SessionStatus, StatEvent


def report_mode(auto_report: dict | None) -> str:
    """Categoriseer de verslag-keuze voor statistiek."""
    if not auto_report:
        return "geen"
    if auto_report.get("custom_prompt"):
        return "eigen"
    kinds = auto_report.get("kinds") or []
    if kinds == ["volledig"]:
        return "volledig"
    return "secties" if kinds else "geen"


def report_mode_from_report(kinds: list | None, custom_prompt: str | None) -> str:
    if custom_prompt:
        return "eigen"
    if kinds == ["volledig"]:
        return "volledig"
    return "secties" if kinds else "geen"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def record_event(db: AsyncSession, kind: str, **dims) -> None:
    """Voeg een anoniem event toe (caller commit)."""
    db.add(StatEvent(
        kind=kind,
        created_at=_now(),
        source=dims.get("source"),
        audio_format=dims.get("audio_format"),
        audio_bytes=dims.get("audio_bytes"),
        audio_seconds=dims.get("audio_seconds"),
        language=dims.get("language"),
        duration_seconds=dims.get("duration_seconds"),
        words=dims.get("words"),
        report_mode=dims.get("report_mode"),
        stars=dims.get("stars"),
        target=dims.get("target"),
        download_kind=dims.get("download_kind"),
    ))


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return round(s[k], 1)


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


async def compute_stats(db: AsyncSession) -> dict:
    s = get_settings()
    # Events ophalen (venster van 180 dagen om onbeperkte groei te vermijden).
    since = _now() - timedelta(days=180)
    res = await db.execute(select(StatEvent).where(StatEvent.created_at >= since))
    events = list(res.scalars().all())

    by_kind: dict[str, list[StatEvent]] = defaultdict(list)
    for e in events:
        by_kind[e.kind].append(e)

    created = by_kind.get("created", [])
    transcribed = by_kind.get("transcribed", [])
    reports = by_kind.get("report", [])
    failed = by_kind.get("failed", [])
    feedback = by_kind.get("feedback", [])
    downloads = by_kind.get("download", [])

    # --- histogrammen ---
    hours = Counter(e.created_at.hour for e in created)
    weekdays = Counter(e.created_at.weekday() for e in created)  # 0=ma .. 6=zo

    def dist(evts, attr):
        c = Counter(getattr(e, attr) for e in evts if getattr(e, attr))
        return dict(c.most_common())

    # dagtrend (laatste 30 dagen)
    day_counts = Counter(e.created_at.date().isoformat() for e in created)
    trend = []
    today = _now().date()
    for i in range(29, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        trend.append({"date": d, "count": day_counts.get(d, 0)})

    t_durations = [e.duration_seconds for e in transcribed if e.duration_seconds is not None]
    r_durations = [e.duration_seconds for e in reports if e.duration_seconds is not None]
    audio_secs = [e.audio_seconds for e in transcribed if e.audio_seconds]
    words = [e.words for e in transcribed if e.words]

    stars = [e.stars for e in feedback if e.stars]
    star_dist = {str(n): sum(1 for x in stars if x == n) for n in range(1, 6)}

    # --- live: wachtrij + schatting ---
    live = await estimate_wait(db, avg_transcribe=_avg(t_durations[-50:]) if t_durations else None)

    n_trans = len(transcribed)
    n_fail_trans = sum(1 for e in failed if e.target == "transcribe")

    return {
        "totals": {
            "transcriptions": n_trans,
            "audio_hours": round(sum(audio_secs) / 3600, 1) if audio_secs else 0,
            "words": sum(words) if words else 0,
            "reports": len(reports),
            "avg_audio_seconds": _avg(audio_secs),
            "success_rate": round(100 * n_trans / (n_trans + n_fail_trans), 1) if (n_trans + n_fail_trans) else None,
        },
        "by_hour": [hours.get(h, 0) for h in range(24)],
        "by_weekday": [weekdays.get(d, 0) for d in range(7)],
        "source": dist(created, "source"),
        "formats": dist(created, "audio_format"),
        "languages": dist(created, "language"),
        "report_modes": dist(created, "report_mode"),
        "report_modes_generated": dist(reports, "report_mode"),
        "downloads": dist(downloads, "download_kind"),
        "trend": trend,
        "processing": {
            "transcribe": {"avg": _avg(t_durations), "p50": _pct(t_durations, 50), "p90": _pct(t_durations, 90)},
            "report": {"avg": _avg(r_durations), "p50": _pct(r_durations, 50), "p90": _pct(r_durations, 90)},
        },
        "satisfaction": {
            "count": len(stars),
            "avg": round(sum(stars) / len(stars), 2) if stars else None,
            "distribution": star_dist,
        },
        "live": live,
        "generated_at": _now().isoformat(),
    }


async def estimate_wait(db: AsyncSession, avg_transcribe: float | None = None) -> dict:
    """Geschatte wachttijd op basis van de wachtrij en gemiddelde verwerkingstijd."""
    s = get_settings()
    if avg_transcribe is None:
        res = await db.execute(
            select(func.avg(StatEvent.duration_seconds)).where(StatEvent.kind == "transcribed")
        )
        avg_transcribe = res.scalar() or 20.0
    queued = (await db.execute(
        select(func.count()).select_from(Session).where(Session.status == SessionStatus.QUEUED)
    )).scalar() or 0
    in_progress = (await db.execute(
        select(func.count()).select_from(Session).where(Session.status == SessionStatus.TRANSCRIBING)
    )).scalar() or 0
    concurrency = max(1, s.stt_concurrency)
    eta = (queued + in_progress) * float(avg_transcribe) / concurrency
    return {
        "queued": int(queued),
        "in_progress": int(in_progress),
        "avg_transcribe_seconds": round(float(avg_transcribe), 1),
        "eta_seconds": int(round(eta)),
    }
