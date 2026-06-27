from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RawHit:
    name: Optional[str]
    url: Optional[str]
    snippet: str = ""
    source: str = "unknown"
    extra: dict = field(default_factory=dict)


@dataclass
class EnrichmentData:
    sectors: list[str] = field(default_factory=list)
    company_stage: Optional[str] = None
    company: Optional[str] = None       # company discovered while enriching
    education: list[str] = field(default_factory=list)
    other_links: list[str] = field(default_factory=list)
    source_url: Optional[str] = None
    confidence: float = 0.0


class DiscoverySource(ABC):
    name: str = "base"

    @abstractmethod
    def search(self, query: str, limit: int) -> list[RawHit]:
        ...


class EnrichmentProvider(ABC):
    name: str = "base"

    @abstractmethod
    def enrich(self, name: str, company: Optional[str], linkedin_url: Optional[str]) -> EnrichmentData:
        ...
