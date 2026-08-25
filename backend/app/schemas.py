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


class DiarizationSegmentOut(BaseModel):
    start: float | None = None
    end: float | None = None
    speaker: str | None = None      # stabiel label SPREKER_A/B/… (None = ongelabeld)
    text: str


class DiarizationOut(BaseModel):
    status: str                                          # queued | running | done | failed
    num_speakers: int | None = None                      # aantal gevonden sprekers
    speakers: list[str] = Field(default_factory=list)    # stabiele labels, op eerste spreekmoment
    segments: list[DiarizationSegmentOut] = Field(default_factory=list)
    # Per spreker een goed hoorbaar fragment [start, end] (langste aaneengesloten spraak).
    clips: dict[str, list[float]] = Field(default_factory=dict)


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
    # Aanwezig als er een diarisatie(-poging) voor deze sessie is; anders None.
    diarization: DiarizationOut | None = None


class RediarizeRequest(BaseModel):
    # Optioneel gevraagd aantal sprekers (leeg = pyannote bepaalt het zelf).
    participants: int | None = None


class CreateReportRequest(BaseModel):
    kinds: list[str] | None = None
    custom_prompt: str | None = None
    context: str | None = None
    # Sjabloon met vragen: als gezet, wordt in plaats van een verslag elke vraag beantwoord
    # o.b.v. het bronmateriaal. Vervangt kinds; de vragen gaan als DATA in de context.
    template: str | None = None
    # Woordenlijst/jargon: terminologie voor de juiste spelling in het verslag (DATA-blok in context).
    glossary: str | None = None
    # Alleen bij SPEAKER_NAMES_MODE=direct: koppeling label->naam (bv. {"SPREKER_A": "Jan"}).
    # In placeholder-modus worden deze GENEGEERD zodat namen niet in de database belanden.
    speaker_names: dict[str, str] | None = None


class UpdateReportRequest(BaseModel):
    # Handmatig bewerkte verslagtekst (Markdown).
    content: str


class FeedbackRequest(BaseModel):
    stars: int
    target: str | None = None   # "transcript" | "verslag"


class ConvertRequest(BaseModel):
    # Markdown -> docx, stateless (niets opgeslagen). Gebruikt voor client-side export met
    # ingevulde sprekernamen in placeholder-modus (namen belanden zo niet in de database).
    content: str
