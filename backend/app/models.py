"""ORM-modellen. BEWUST geen persoonsgegevens: alleen technische status,
paden en de door de gebruiker gevraagde inhoud (transcript/verslag).

De sessie-id is een hoge-entropie geheim token en is de enige sleutel tot de
data. Er is geen koppeling naar gebruikers, IP's of accounts.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
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
