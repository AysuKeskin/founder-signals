from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from .base import DiscoverySource, EnrichmentData, EnrichmentProvider, RawHit

_BUCKETS = [
    {  # Türkiye
        "first": ["Ahmet", "Elif", "Mehmet", "Zeynep", "Can", "Ayse", "Emre",
                  "Selin", "Burak", "Deniz", "Cem", "Ece", "Mert", "Irem"],
        "last": ["Yilmaz", "Demir", "Kaya", "Sahin", "Celik", "Aydin", "Ozturk",
                 "Arslan", "Dogan", "Kilic"],
        "cities": ["Istanbul, Türkiye", "Ankara, Türkiye", "Izmir, Türkiye"],
    },
    {  # CEE (Poland / Czechia / Baltics / Romania)
        "first": ["Jakub", "Anna", "Piotr", "Katarzyna", "Tomas", "Eva", "Andrei",
                  "Ioana", "Marek", "Lukas", "Kristine", "Mihai", "Agnieszka"],
        "last": ["Kowalski", "Novak", "Nowak", "Popescu", "Horvath", "Kcovacs",
                 "Tamm", "Berzins", "Wisniewski", "Ionescu"],
        "cities": ["Warsaw, Poland", "Prague, Czechia", "Tallinn, Estonia",
                   "Bucharest, Romania", "Vilnius, Lithuania", "Riga, Latvia"],
    },
    {  # Caucasus (Georgia / Armenia / Azerbaijan)
        "first": ["Giorgi", "Nino", "Levan", "Tamar", "Aram", "Ani", "Davit",
                  "Elnur", "Leyla", "Vahagn", "Mariam", "Rustam"],
        "last": ["Beridze", "Kapanadze", "Sargsyan", "Hakobyan", "Mammadov",
                 "Aliyev", "Gelashvili", "Petrosyan", "Guliyev"],
        "cities": ["Tbilisi, Georgia", "Yerevan, Armenia", "Baku, Azerbaijan",
                   "Batumi, Georgia"],
    },
]

_ROLES = ["Founder & CEO", "Co-Founder", "Founder", "Co-Founder & CTO",
          "Founding Partner", "Co-Founder & CEO"]
_SECTORS = ["Fintech", "SaaS", "Healthtech", "AI/ML", "E-commerce", "Logistics",
            "Climate", "Gaming", "Cybersecurity", "Edtech", "Proptech", "Mobility"]
_COMPANY_SUFFIX = ["Labs", "AI", "Tech", "io", "Systems", "Works", "Hub", "Cloud"]
_STAGES = ["pre-seed", "seed", "Series A", "bootstrapped", "Series B"]


def _h(*parts: str) -> int:
    return int(hashlib.sha1("|".join(parts).encode()).hexdigest(), 16)


def _person(i: int) -> RawHit:
    bucket = _BUCKETS[i % len(_BUCKETS)]
    first = bucket["first"][_h("first", str(i)) % len(bucket["first"])]
    last = bucket["last"][_h("last", str(i)) % len(bucket["last"])]
    city = bucket["cities"][_h("city", str(i)) % len(bucket["cities"])]
    role = _ROLES[_h("role", str(i)) % len(_ROLES)]
    sector = _SECTORS[_h("sector", str(i)) % len(_SECTORS)]
    suffix = _COMPANY_SUFFIX[_h("suf", str(i)) % len(_COMPANY_SUFFIX)]
    company = f"{last}{suffix}"
    name = f"{first} {last}"
    handle = f"{first}-{last}".lower().replace(" ", "-")
    vanity_hash = hashlib.sha1(f"slug{i}".encode()).hexdigest()[:8]
    url = f"https://www.linkedin.com/in/{handle}-{vanity_hash}"
    snippet = f"{name} - {role} at {company} | {sector} | {city}"
    return RawHit(
        name=name, url=url, snippet=snippet, source="synthetic",
        extra={"role": role, "company": company, "sector": sector,
               "city": city, "stage": _STAGES[_h("stage", str(i)) % len(_STAGES)]},
    )


_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "founders_seed.json"


def _load_seeds() -> list[dict]:
    try:
        return json.loads(_FIXTURE.read_text(encoding="utf-8"))
    except Exception:
        return []


_SEEDS: list[dict] = _load_seeds()
_REAL_POOL: list[RawHit] = [
    RawHit(name=s.get("name"), url=s.get("url"),
           snippet=s.get("snippet", ""), source="cached")
    for s in _SEEDS if s.get("url")
]
_REAL_ENRICH: dict[str, dict] = {s["url"]: s for s in _SEEDS if s.get("url")}
USING_REAL_SEEDS: bool = len(_REAL_POOL) >= 1

_SYNTH_POOL: list[RawHit] = [_person(i) for i in range(180)]

_POOL: list[RawHit] = _REAL_POOL if USING_REAL_SEEDS else _SYNTH_POOL


class CachedDiscoverySource(DiscoverySource):
    name = "cached"

    def search(self, query: str, limit: int) -> list[RawHit]:
        offset = _h("q", query) % len(_POOL)
        rotated = _POOL[offset:] + _POOL[:offset]
        return rotated[:limit]


class CachedEnrichmentProvider(EnrichmentProvider):
    name = "cached"

    def enrich(self, name: str, company: Optional[str],
               linkedin_url: Optional[str]) -> EnrichmentData:
        if USING_REAL_SEEDS:
            rec = _REAL_ENRICH.get(linkedin_url or "", {})
            return EnrichmentData(
                sectors=rec.get("sectors") or [],
                company_stage=rec.get("company_stage"),
                company=rec.get("company"),
                other_links=rec.get("other_links") or [],
                source_url="web://search" if rec.get("sectors") else None,
                confidence=float(rec.get("enrich_confidence") or 0.0),
            )

        key = linkedin_url or name or ""
        i = _h("enrich", key)
        sector = _SECTORS[i % len(_SECTORS)]
        return EnrichmentData(
            sectors=[sector],
            company_stage=_STAGES[i % len(_STAGES)],
            education=["Technical University"],
            other_links=[f"https://{(company or 'startup').lower()}.com"],
            source_url="synthetic://enrichment",
            confidence=0.7,
        )
