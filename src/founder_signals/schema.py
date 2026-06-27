from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Region(str, Enum):
    TURKIYE = "turkiye"
    CEE = "cee"
    CAUCASUS = "caucasus"
    OTHER = "other"
    UNKNOWN = "unknown"


class Status(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    ERROR = "error"
    SKIPPED = "skipped"


def stage_status(candidates: int, processed: int, errors: int) -> "Status":
    if candidates == 0:
        return Status.OK
    if processed == 0:
        return Status.ERROR
    return Status.PARTIAL if errors else Status.OK


class Stage(str, Enum):
    DISCOVER = "discover"
    EXTRACT = "extract"
    NORMALIZE = "normalize"
    ENRICH = "enrich"
    RANK = "rank"
    EXPORT = "export"
    GRAPH = "graph"


class FieldValue(BaseModel):
    value: Any
    source: str = "unknown"
    source_url: Optional[str] = None
    confidence: float = 0.0
    extracted_at: str = Field(default_factory=_utcnow)
    note: Optional[str] = None

    @classmethod
    def empty(cls) -> "FieldValue":
        return cls(value=None, confidence=0.0)


class ProfileError(BaseModel):
    stage: Stage
    code: str
    message: str
    retryable: bool = True
    at: str = Field(default_factory=_utcnow)


class Profile(BaseModel):
    id: str
    linkedin_url: Optional[str] = None

    full_name: FieldValue = Field(default_factory=FieldValue.empty)
    headline: FieldValue = Field(default_factory=FieldValue.empty)
    current_company: FieldValue = Field(default_factory=FieldValue.empty)
    current_role: FieldValue = Field(default_factory=FieldValue.empty)
    is_founder: FieldValue = Field(default_factory=FieldValue.empty)

    location_raw: FieldValue = Field(default_factory=FieldValue.empty)
    city: FieldValue = Field(default_factory=FieldValue.empty)
    country: FieldValue = Field(default_factory=FieldValue.empty)
    region: FieldValue = Field(default_factory=FieldValue.empty)

    sectors: FieldValue = Field(default_factory=FieldValue.empty)
    company_stage: FieldValue = Field(default_factory=FieldValue.empty)
    education: FieldValue = Field(default_factory=FieldValue.empty)
    other_links: FieldValue = Field(default_factory=FieldValue.empty)

    raw_snippet: Optional[str] = None
    source_urls: list[str] = Field(default_factory=list)
    errors: list[ProfileError] = Field(default_factory=list)
    overall_confidence: float = 0.0
    rank_score: Optional[float] = None
    stages_done: list[Stage] = Field(default_factory=list)
    first_seen: str = Field(default_factory=_utcnow)
    last_updated: str = Field(default_factory=_utcnow)

    def touch(self) -> None:
        self.last_updated = _utcnow()

    def mark_stage(self, stage: Stage) -> None:
        if stage not in self.stages_done:
            self.stages_done.append(stage)
        self.touch()

    def add_error(self, error: ProfileError) -> None:
        self.errors.append(error)
        self.touch()

    def field_items(self) -> list[tuple[str, FieldValue]]:
        names = [
            "full_name", "headline", "current_company", "current_role",
            "is_founder", "location_raw", "city", "country", "region",
            "sectors", "company_stage", "education", "other_links",
        ]
        return [(n, getattr(self, n)) for n in names]


T = TypeVar("T")


class ToolResult(BaseModel, Generic[T]):
    status: Status
    stage: Stage
    data: Optional[T] = None
    count: int = 0
    errors: list[ProfileError] = Field(default_factory=list)
    provenance: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    run_id: Optional[str] = None
    message: Optional[str] = None
    elapsed_ms: Optional[int] = None

    @classmethod
    def ok(cls, stage: Stage, data: T, **kw: Any) -> "ToolResult[T]":
        count = len(data) if isinstance(data, (list, dict)) else (1 if data is not None else 0)
        return cls(status=Status.OK, stage=stage, data=data, count=count, **kw)

    @classmethod
    def error(cls, stage: Stage, message: str, errors: Optional[list[ProfileError]] = None, **kw: Any) -> "ToolResult[T]":
        return cls(status=Status.ERROR, stage=stage, message=message, errors=errors or [], **kw)
