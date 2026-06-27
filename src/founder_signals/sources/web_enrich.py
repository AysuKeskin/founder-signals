from __future__ import annotations

import re
from typing import Optional

from .base import EnrichmentData, EnrichmentProvider

_SECTOR_KEYWORDS = {
    "fintech": "Fintech", "payments": "Fintech", "saas": "SaaS",
    "health": "Healthtech", "biotech": "Healthtech", "medtech": "Healthtech",
    "ai": "AI/ML", "machine learning": "AI/ML", "ecommerce": "E-commerce",
    "e-commerce": "E-commerce", "logistics": "Logistics", "climate": "Climate",
    "energy": "Climate", "cleantech": "Climate", "gaming": "Gaming",
    "security": "Cybersecurity", "cyber": "Cybersecurity",
    "edtech": "Edtech", "education": "Edtech", "proptech": "Proptech",
    "real estate": "Proptech", "mobility": "Mobility",
    "blockchain": "Crypto/Web3", "crypto": "Crypto/Web3", "web3": "Crypto/Web3",
    "defi": "Crypto/Web3", "insurtech": "Insurtech", "agritech": "Agritech",
    "agtech": "Agritech", "foodtech": "Foodtech", "robotics": "Robotics",
    "deeptech": "Deeptech", "deep tech": "Deeptech", "marketplace": "Marketplace",
    "hrtech": "HRtech", "legaltech": "Legaltech", "iot": "IoT",
}
_LINK_RE = re.compile(r"https?://[^\s\"'<>]+")
_COMPANY_RE = re.compile(
    r"(?:\bat\s+|@)([A-Z0-9][\w&.\-]*(?:\s+[A-Z0-9][\w&.\-]*){0,2})")


def _clean_company(s: str | None, name: str | None = None) -> str | None:
    if not s:
        return None
    s = s.strip(" .,-")
    if not (2 <= len(s) <= 40) or any(c.isdigit() for c in s):
        return None
    if name:
        c = re.sub(r"[^a-z]", "", s.lower())
        for tok in name.lower().split():
            t = re.sub(r"[^a-z]", "", tok)
            if len(t) >= 4 and t in c:
                return None
    return s


def _detect_company(text: str, name: str | None = None) -> str | None:
    first = re.split(r"\.{2,}|…", text)[0]   # first result chunk = top hit
    for m in _COMPANY_RE.finditer(first):
        cand = _clean_company(m.group(1), name)
        if cand:
            return cand
    return None

def sectors_from_text(text: str) -> list[str]:
    low = text.lower()
    out = set()
    for k, v in _SECTOR_KEYWORDS.items():
        if (re.search(rf"\b{re.escape(k)}\b", low) if len(k) <= 3 else k in low):
            out.add(v)
    return sorted(out)


_STAGE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("stealth",          re.compile(r"\bstealth\b", re.I)),
    ("ipo",              re.compile(r"\b(ipo|went public|publicly listed|nasdaq|nyse)\b", re.I)),
    ("acquired",         re.compile(r"\b(acquired by|acquisition by|exited to)\b", re.I)),
    ("series d+",        re.compile(r"\bseries\s+[d-f]\b", re.I)),
    ("series c",         re.compile(r"\bseries\s+c\b", re.I)),
    ("series b",         re.compile(r"\bseries\s+b\b", re.I)),
    ("series a",         re.compile(r"\bseries\s+a\b", re.I)),
    ("pre-seed",         re.compile(r"\bpre[-\s]?seed\b", re.I)),
    ("seed",             re.compile(r"\bseed(?:\s+(?:round|stage|funded|funding))?\b", re.I)),
    ("bootstrapped",     re.compile(r"\bbootstrapp?ed\b", re.I)),
    ("accelerator-backed", re.compile(
        r"\b(y[\s-]?combinator|yc\s+[wsf]\d{2}|techstars|500\s+(?:startups|global)|"
        r"backed by 500|startup\s+wise\s+guys|antler|plug\s+and\s+play|"
        r"entrepreneur first|gradient ventures)\b", re.I)),
    ("funded",           re.compile(
        r"\b(raised|secured|closed|landed)\b[^.]{0,30}\$\s?\d|\b\$\s?\d+(?:\.\d+)?\s?[mkb]\b"
        r"|\b(pre[-\s]?series|seed\s+investment|venture[-\s]?backed|vc[-\s]?backed)\b", re.I)),
]


def _detect_stage(text: str) -> str | None:
    for label, pat in _STAGE_PATTERNS:
        if pat.search(text):
            return label
    return None


class WebEnrichmentProvider(EnrichmentProvider):
    name = "web_enrich"

    def __init__(self, timeout_s: float = 12.0, rate_limit_s: float = 1.2,
                 user_agent: str = "founder-signals-research/0.1"):
        self.timeout_s = timeout_s
        self.rate_limit_s = rate_limit_s
        self.user_agent = user_agent

    def enrich(self, name: str, company: Optional[str],
               linkedin_url: Optional[str]) -> EnrichmentData:
        text = self._gather_text(name, company)
        if not text:
            return EnrichmentData(confidence=0.0)

        sectors = sectors_from_text(text)
        stage = _detect_stage(text)
        discovered_company = company or _detect_company(text, name)
        links = _LINK_RE.findall(text)[:3]
        signal = bool(sectors) + bool(stage) + bool(links)
        return EnrichmentData(
            sectors=sectors,
            company_stage=stage,
            company=discovered_company,
            other_links=links,
            source_url="web://search",
            confidence=min(0.3 + 0.2 * signal, 0.9),
        )

    def _gather_text(self, name: str, company: Optional[str]) -> str:
        try:
            from ddgs import DDGS
        except Exception:  # pragma: no cover
            return ""
        query = f'"{name}" {company or ""} founder startup'.strip()
        try:
            chunks: list[str] = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=5):
                    chunks.append(f"{r.get('title','')} {r.get('body','')}")
            return "\n".join(chunks)
        except Exception:
            return ""
