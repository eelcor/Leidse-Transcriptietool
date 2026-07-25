"""ORM-modellen. BEWUST geen persoonsgegevens: alleen technische status,
paden en de door de gebruiker gevraagde inhoud (transcript/verslag).

De sessie-id is een hoge-entropie geheim token en is de enige sleutel tot de
data. Er is geen koppeling naar gebruikers, IP's of accounts.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --- Statuswaarden ---
class SessionStatus:
    CREATED = "created"        # sessie aangemaakt, upload nog bezig/nog niet afgerond
    QUEUED = "queued"          # upload klaar, job op de wachtrij
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    FAILED = "failed"

    TERMINAL = {TRANSCRIBED, FAILED}


class ReportStatus:
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"

    TERMINAL = {DONE, FAILED}


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default=SessionStatus.CREATED, index=True)
    language: Mapped[str] = mapped_column(String(8), default="nl")

    # Welke backend het transcript maakte (audit/debug, geen persoonsgegeven).
    stt_backend: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Opslag
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    audio_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ASR-audio-optimalisatie toepassen tijdens verwerking (default aan).
    optimize_audio: Mapped[bool] = mapped_column(Boolean, default=True)
    # Optioneel: verslag dat automatisch ná de transcriptie moet draaien.
    # Vorm: {"kinds": [...], "custom_prompt": str|None, "context": str|None} of NULL.
    auto_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Herkomst (voor anonieme statistieken): "upload" of "record". Geen persoonsgegeven.
    source: Mapped[str | None] = mapped_column(String(12), nullable=True)
    audio_format: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Resultaat
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Segmenten met (woord/segment) timestamps: [{"start":..,"end":..,"text":..}, ...]
    segments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Tijdstempels
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Werkdag-bewust; pas gezet zodra de verwerking klaar is (niet bij upload).
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    reports: Mapped[list["Report"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)

    # Gekozen standaard-secties (["samenvatting", "actiepunten", ...] of ["volledig"]).
    kinds: Mapped[list | None] = mapped_column(JSON, nullable=True)
    custom_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default=ReportStatus.QUEUED, index=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    session: Mapped[Session] = relationship(back_populates="reports")


class StatEvent(Base):
    """Anonieme, geaggregeerd-veilige gebeurtenis voor het statistiekdashboard.

    Bevat BEWUST geen persoonsgegevens: geen IP, geen bestandsnaam, geen
    transcript-inhoud, geen koppeling naar een gebruiker. Alleen tellingen,
    tijdstippen, duur, formaat, taal en keuzes. Blijft bewaard (los van de
    sessies die na de bewaartermijn verdwijnen) zodat het dashboard historie toont.
    """

    __tablename__ = "stat_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)   # created|transcribed|report|failed|feedback|download
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    source: Mapped[str | None] = mapped_column(String(12), nullable=True)           # upload|record
    audio_format: Mapped[str | None] = mapped_column(String(16), nullable=True)      # mp3|wav|webm|...
    audio_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)     # verwerkingstijd
    words: Mapped[int | None] = mapped_column(Integer, nullable=True)
    report_mode: Mapped[str | None] = mapped_column(String(12), nullable=True)       # volledig|secties|eigen|geen
    stars: Mapped[int | None] = mapped_column(Integer, nullable=True)                # feedback 1..5
    target: Mapped[str | None] = mapped_column(String(16), nullable=True)            # transcript|verslag|transcribe|report
    download_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)     # audio|transcript|report_docx|report_md
