from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor

from ..logging_utils import RunLogger
from ..schema import FieldValue, Profile, ProfileError, Stage, ToolResult, stage_status
from ..sources.web_enrich import _detect_stage, sectors_from_text
from ..store import Store

_ROLE_RE = re.compile(
    r"\b(co[-\s]?founder(?:\s*&?\s*(?:ceo|cto|coo))?|founder(?:\s*&?\s*(?:ceo|cto|coo))?"
    r"|founding partner|ceo|cto)\b", re.I)
_EXPERIENCE_RE = re.compile(
    r"(?:deneyim|experience|erfahrung)\s*:\s*([^·|,\n]+)", re.I)
_COMPANY_RE = re.compile(
    r"(?:\bat\s+|@\s*)([A-ZÇĞİÖŞÜ0-9][\w&.\-]*(?:\s+[A-ZÇĞİÖŞÜ0-9][\w&.\-]*){0,2})")
_LOCATION_FIELD_RE = re.compile(r"(?:konum|location|standort)\s*:\s*([^·|,\n]+)", re.I)


def _clean_location(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    if not (2 <= len(s) <= 40) or not s[0].isalpha() or "{" in s or "." in s:
        return None
    return s
_LOCATION_RE = re.compile(
    r"\b(Istanbul|İstanbul|Ankara|Izmir|İzmir|Bursa|Antalya|Warsaw|Krakow|Wroclaw|"
    r"Prague|Brno|Tallinn|Riga|Vilnius|Bucharest|Cluj|Sofia|Tbilisi|Batumi|Yerevan|"
    r"Baku|Kyiv|Lviv|Budapest|Bratislava|Zagreb|Belgrade|Ljubljana)\b", re.I)
_HEADLINE_SPLIT = re.compile(r"\s*[|•·]\s*|\.\s+|\s·\s")

_HL_ROLE = re.compile(
    r"\b(co[-\s]?founder|founder|founding|ceo|cto|coo|owner|kurucu|girişimci|partner|"
    r"advisor|head|lead|manager|director|builder|entrepreneur|investor|consultant)\b", re.I)
_NOT_COMPANY_LOC = {
    "türkiye", "turkey", "istanbul", "i̇stanbul", "ankara", "izmir", "i̇zmir", "bursa",
    "antalya", "kağıthane", "georgia", "poland", "romania", "estonia", "armenia",
    "azerbaijan", "ukraine", "bulgaria", "tbilisi", "warsaw", "konum",
}
_NOT_COMPANY_GEN = {
    "startup", "startups", "ai", "ml", "saas", "tech", "technology", "engineer",
    "engineering", "founder", "cofounder", "ceo", "cto", "coo", "entrepreneur",
    "builder", "developer", "company", "ventures", "venture", "capital", "world",
    "cup", "global", "solutions", "consultant", "advisor", "investor", "freelance",
    "student", "scout", "co", "and", "the", "stealth", "pc", "fintech", "healthtech", "logistics",
    "gaming", "edtech", "proptech", "mobility", "climate", "cybersecurity",
    "ecommerce", "payments", "biotech", "energy", "member", "board", "cio", "cmo",
    "cfo", "former", "head", "vp", "president", "manager", "director", "lead",
    "mentor", "expert", "specialist", "professional",
    "smmm", "ymm", "av", "dr", "uzm", "prof", "doç", "müşavir", "muhasebeci",
}
_HARD_NOT_COMPANY = {
    "addict", "enthusiast", "lover", "fan", "geek", "nerd", "passionate",
    "hobbyist", "dreamer", "thinker", "freak", "junkie", "obsessed",
}


def _real_company(s: str | None, name: str | None) -> str | None:
    s = _clean_company(s, name)
    if not s:
        return None
    s = re.sub(r"\s*(şirketinde|şirketi|firmasında)\s*$", "", s, flags=re.I).strip()
    toks = re.findall(r"[a-zçğıöşüâîû]+", s.lower())
    if not toks or any(t in _NOT_COMPANY_LOC for t in toks):
        return None
    if any(t in _HARD_NOT_COMPANY for t in toks):
        return None
    if all(t in _NOT_COMPANY_GEN for t in toks):
        return None
    return s


_FOUNDER_ROLE = re.compile(r"founder|ceo|cto|coo|owner|kurucu|girişimci", re.I)
_HL_CONNECTOR = re.compile(r"(?:\bat\s+|@\s*|\bof\s+)(.+)", re.I)


def _company_from_headline(headline: str, name: str | None) -> str | None:
    parts = re.split(r"\s+[-–—]\s+", headline, maxsplit=1)
    if len(parts) < 2:
        return None
    rest = parts[1].strip()
    roles = list(_HL_ROLE.finditer(rest))
    if roles:
        # Some snippets are "Name - Company Founder"; take the text before the role.
        c = _real_company(rest[: roles[0].start()], name)
        if c:
            return c
        if _FOUNDER_ROLE.search(roles[-1].group(0)):
            # Others are "Founder at Company" or "Co-Founder of Company".
            after = rest[roles[-1].end():]
            cm = _HL_CONNECTOR.search(after)
            if cm:
                tail = cm.group(1)
            elif after.lstrip().startswith(","):
                return None
            else:
                tail = after.lstrip()
            tail = re.split(r"\s*[|·,]\s*", tail)[0]
            return _real_company(" ".join(tail.split()[:3]), name)
    elif ("@" not in rest and not re.search(r"\b(?:at|of)\b", rest, re.I)
          and 1 <= len(rest.split()) <= 3):
        return _real_company(rest.split("|")[0], name)
    return None


def _clean_company(s: str | None, name: str | None = None) -> str | None:
    if not s:
        return None
    s = s.strip(" .,-–—&|/")
    s = re.split(r"\s[-–—]", s)[0].strip(" .,-–—&|/")
    if not (2 <= len(s) <= 40) or any(c.isdigit() for c in s):
        return None
    first_tok = re.sub(r"[^a-zçğıöşü]", "", s.lower().split()[0]) if s.split() else ""
    if first_tok in {"i", "im", "we", "my", "our", "the", "a", "an"}:
        return None
    if name:
        c = re.sub(r"[^a-z]", "", s.lower())
        for tok in name.lower().split():
            t = re.sub(r"[^a-z]", "", tok)
            if len(t) >= 4 and t in c:
                return None
    return s


def _extract_one(p: Profile) -> Profile:
    snippet = p.raw_snippet or ""
    # Search results often glue several profiles together after "..."; keep the first one.
    first = re.split(r"\.{2,}|…", snippet)[0].strip()

    headline = _HEADLINE_SPLIT.split(first)[0].strip()
    if len(headline) > 3:
        p.headline = FieldValue(value=headline[:140], source="extract", confidence=0.5)

    role_m = _ROLE_RE.search(headline)
    if role_m:
        p.current_role = FieldValue(value=role_m.group(0).title(),
                                    source="extract", confidence=0.6)

    company, source, conf = None, None, 0.5
    # Prefer LinkedIn's labelled experience field; headline patterns are noisier.
    exp_m = _EXPERIENCE_RE.search(first)
    if exp_m:
        company = _real_company(exp_m.group(1), p.full_name.value)
        source, conf = "extract:experience", 0.7
    if not company:
        company = _company_from_headline(headline, p.full_name.value)
        source, conf = "extract:headline", 0.65
    if not company:
        for comp_m in _COMPANY_RE.finditer(headline):
            company = _real_company(comp_m.group(1), p.full_name.value)
            if company:
                source, conf = "extract", 0.55
                break
    if company:
        p.current_company = FieldValue(value=company, source=source, confidence=conf)

    field_m = _LOCATION_FIELD_RE.search(snippet)
    loc_val = _clean_location(field_m.group(1)) if field_m else None
    if loc_val:
        p.location_raw = FieldValue(value=loc_val, source="extract:location", confidence=0.7)
    else:
        loc_m = _LOCATION_RE.search(snippet)
        if loc_m:
            p.location_raw = FieldValue(value=loc_m.group(1), source="extract", confidence=0.5)

    secs = sectors_from_text(first)
    if secs:
        p.sectors = FieldValue(value=secs, source="extract", confidence=0.5)
    stg = _detect_stage(first)
    if stg:
        p.company_stage = FieldValue(value=stg, source="extract", confidence=0.6)

    p.mark_stage(Stage.EXTRACT)
    return p


def _regex_complete(p: Profile) -> bool:
    return bool(p.current_company.value
                and p.current_role.value
                and (isinstance(p.sectors.value, list) and p.sectors.value))


def _overlay_llm(p: Profile, name: str, snippet: str, cfg) -> None:
    from ..sources.llm_extract import extract_fields_llm, llm_available
    if not llm_available(cfg):
        return
    f = extract_fields_llm(name, snippet, cfg)
    if not f:
        return
    # In auto mode regex keeps its values and the LLM only fills gaps.
    fill_only = getattr(cfg, "extract_mode", "") == "auto"

    if f.company and not (fill_only and p.current_company.value):
        p.current_company = FieldValue(value=f.company, source="extract:llm", confidence=0.8)
    if f.role and not (fill_only and p.current_role.value):
        p.current_role = FieldValue(value=f.role, source="extract:llm", confidence=0.8)
    if f.city and not (fill_only and p.location_raw.value):
        p.location_raw = FieldValue(value=f.city, source="extract:llm", confidence=0.8)
    if f.sectors:
        existing = p.sectors.value if isinstance(p.sectors.value, list) else []
        p.sectors = FieldValue(value=sorted(set(existing) | set(f.sectors)),
                               source="extract:llm", confidence=0.8)
    if f.company_stage and not (fill_only and p.company_stage.value):
        p.company_stage = FieldValue(value=f.company_stage.lower(),
                                     source="extract:llm", confidence=0.7)


def run_extract(store: Store, logger: RunLogger,
                only_pending: bool = True, cfg=None) -> ToolResult[dict]:
    start = time.monotonic()
    profiles = store.needing_stage(Stage.EXTRACT) if only_pending else store.all()
    processed, errors = 0, 0
    with logger.stage(Stage.EXTRACT.value, candidates=len(profiles)):
        for p in profiles:
            try:
                _extract_one(p)
                processed += 1
            except Exception as exc:  # noqa: BLE001
                errors += 1
                p.add_error(ProfileError(stage=Stage.EXTRACT, code="parse_failed",
                                         message=repr(exc)))

        if cfg is not None:
            from ..sources.llm_extract import llm_available
            if llm_available(cfg):
                targets = profiles
                if getattr(cfg, "extract_mode", "") == "auto":
                    targets = [p for p in profiles if not _regex_complete(p)]
                workers = getattr(cfg, "llm_workers", 8)
                logger.log("llm_overlay", profiles=len(targets), workers=workers,
                           mode=getattr(cfg, "extract_mode", ""))
                if targets:
                    with ThreadPoolExecutor(max_workers=workers) as pool:
                        list(pool.map(lambda p: _overlay_llm(
                            p, p.full_name.value or "", p.raw_snippet or "", cfg), targets))

        for p in profiles:
            store.upsert(p)
    elapsed = int((time.monotonic() - start) * 1000)
    status = stage_status(candidates=len(profiles), processed=processed, errors=errors)
    return ToolResult(status=status, stage=Stage.EXTRACT,
                      data={"processed": processed, "errors": errors},
                      count=processed, run_id=logger.run_id, elapsed_ms=elapsed,
                      message=f"extracted {processed} profiles")
