from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ObservationKind(str, Enum):
    price = "price"
    fundamental = "fundamental"
    news = "news"
    macro = "macro"
    filing = "filing"
    sentiment = "sentiment"


class ThesisStatus(str, Enum):
    active = "active"
    strengthened = "strengthened"
    weakened = "weakened"
    broken = "broken"
    closed = "closed"


class Observation(BaseModel):
    """A point-in-time fact.

    ``published_at`` is when the world could have known it.
    ``observed_at`` is when Janus actually ingested it.
    ``valid_from`` / ``valid_to`` describe the fact's own validity window.
    """

    id: str
    entity_id: str
    kind: ObservationKind
    source: str
    published_at: datetime
    observed_at: datetime = Field(default_factory=utcnow)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    value: dict[str, Any]
    unit: Optional[str] = None
    confidence: float = 1.0
    raw_hash: str
    raw_uri: Optional[str] = None


class Thesis(BaseModel):
    """A belief with explicit assumptions and falsifiers."""

    id: str
    entity_id: str
    persona_id: Optional[str] = None
    horizon: str
    statement: str
    assumptions: list[str] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    falsifiers: list[str] = Field(default_factory=list)
    status: ThesisStatus = ThesisStatus.active
    created_at: datetime = Field(default_factory=utcnow)
    as_of: datetime


class Prediction(BaseModel):
    """An ex-ante forecast. Predictions are immutable once recorded."""

    id: str
    thesis_id: str
    target: str
    horizon: str
    probability: Optional[float] = None
    quantiles: dict[str, float] = Field(default_factory=dict)
    model_version: str
    features_hash: str
    created_at: datetime = Field(default_factory=utcnow)
    as_of: datetime
    outcome_id: Optional[str] = None


class Outcome(BaseModel):
    """The ex-post result of a prediction."""

    id: str
    prediction_id: str
    realized_value: dict[str, Any]
    realized_at: datetime
    source: str
    score: Optional[float] = None


class Persona(BaseModel):
    """A structured investment taste, not a prompt role-play."""

    id: str
    name: str
    profile: dict[str, float]
    weights: dict[str, float]
    rules: dict[str, Any] = Field(default_factory=dict)
    version: str = "0.1.0"
    created_at: datetime = Field(default_factory=utcnow)


class Review(BaseModel):
    """A debrief: attribution, calibration, and lessons."""

    id: str
    prediction_id: str
    attribution: dict[str, float]
    calibration: Optional[float] = None
    lessons: str = ""
    created_at: datetime = Field(default_factory=utcnow)
