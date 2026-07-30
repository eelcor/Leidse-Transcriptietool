"""Pydantic request/response-schema's voor de API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CreateSessionResponse(BaseModel):
    id: str
    status: str


class SegmentOut(BaseModel):
    start: float | None = None
    end: float | None = None
    text: str


class SessionStatusOut(BaseModel):
    id: str
    status: str
    language: str
    error: str | None = None
    created_at: datetime
    processing_finished_at: datetime | None = None
    expires_at: datetime | None = None
    has_transcript: bool = False
    # Positie in de transcriptie-wachtrij (1 = eerstvolgende); alleen als status=queued.
    queue_position: int | None = None


class ReportOut(BaseModel):
    id: str
    status: str
    kinds: list[str] | None = None
    custom_prompt: str | None = None
    content: str | None = None
    error: str | None = None
    created_at: datetime
    # Positie in de verslag-wachtrij (1 = eerstvolgende); alleen als status=queued.
    queue_position: int | None = None


class SessionResultOut(BaseModel):
    id: str
    status: str
    language: str
    error: str | None = None
    transcript: str | None = None
    segments: list[SegmentOut] | None = None
    processing_finished_at: datetime | None = None
    expires_at: datetime | None = None
    reports: list[ReportOut] = Field(default_factory=list)


class CreateReportRequest(BaseModel):
    kinds: list[str] | None = None
    custom_prompt: str | None = None
    context: str | None = None


class UpdateReportRequest(BaseModel):
    # Handmatig bewerkte verslagtekst (Markdown).
    content: str


class FeedbackRequest(BaseModel):
    stars: int
    target: str | None = None   # "transcript" | "verslag"
