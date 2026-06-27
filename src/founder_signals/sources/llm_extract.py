from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Optional

from ..config import Config


class _Throttle:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next = 0.0
        self._interval = 1.0

    def configure(self, rpm: int) -> None:
        self._interval = 60.0 / max(rpm, 1)

    def wait(self) -> None:
        with self._lock:
            # One shared throttle keeps concurrent workers under the provider RPM.
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self._interval
        delay = slot - time.monotonic()
        if delay > 0:
            time.sleep(delay)


_throttle = _Throttle()

_SYSTEM = (
    "You extract structured facts about ONE person from a LinkedIn search "
    "snippet. Return ONLY compact JSON, no prose."
)

_PROMPT = """From the snippet below, extract facts about "{name}" (the FIRST person
mentioned — ignore other people glued into the text).

Return JSON with exactly these keys:
- "company": the company they currently lead/work at, or null. Use the real
  company name only — never a job title, a hobby, a location, or a generic phrase
  like "AI Startup".
- "role": their current role/title, or null.
- "city": their city, or null; never a country/region.
- "sectors": array of sector tags from this set only (or []): ["Fintech","SaaS",
  "Healthtech","AI/ML","E-commerce","Logistics","Climate","Gaming","Cybersecurity",
  "Edtech","Proptech","Mobility","Crypto/Web3","Insurtech","Agritech","Robotics"].
- "is_founder": true if THIS person is a founder/co-founder/owner of their own
  company, else false.
- "company_stage": funding stage if the snippet states it, else null — one of
  ["pre-seed","seed","series a","series b","series c","bootstrapped",
  "accelerator-backed","funded","stealth","acquired","ipo"]. Don't guess.

Snippet:
{snippet}
"""


@dataclass
class LLMFields:
    company: Optional[str] = None
    role: Optional[str] = None
    city: Optional[str] = None
    sectors: Optional[list] = None
    is_founder: Optional[bool] = None
    company_stage: Optional[str] = None


def llm_available(cfg: Config) -> bool:
    return bool(cfg.llm_api_key) and cfg.extract_mode in ("llm", "auto")


def extract_fields_llm(name: str, snippet: str, cfg: Config) -> Optional[LLMFields]:
    if not cfg.llm_api_key:
        return None
    try:
        import httpx
    except Exception:  # pragma: no cover
        return None

    payload = {
        "model": cfg.llm_model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _PROMPT.format(name=name, snippet=snippet[:1200])},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    url = f"{cfg.llm_base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {cfg.llm_api_key}"}
    _throttle.configure(getattr(cfg, "llm_rpm", 60))
    for attempt in range(4):
        _throttle.wait()
        try:
            resp = httpx.post(url, headers=headers, json=payload,
                              timeout=cfg.request_timeout_s)
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(2.0 * (attempt + 1))
                continue
            resp.raise_for_status()
            return _parse(resp.json()["choices"][0]["message"]["content"])
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return None


def _parse(content: str) -> Optional[LLMFields]:
    try:
        d = json.loads(content)
    except Exception:
        return None
    sectors = d.get("sectors")
    # Treat bad shapes as missing fields; extraction should degrade, not fail the run.
    return LLMFields(
        company=_str_or_none(d.get("company")),
        role=_str_or_none(d.get("role")),
        city=_str_or_none(d.get("city")),
        sectors=sectors if isinstance(sectors, list) else None,
        is_founder=d.get("is_founder") if isinstance(d.get("is_founder"), bool) else None,
        company_stage=_str_or_none(d.get("company_stage")),
    )


def _str_or_none(v) -> Optional[str]:
    if not isinstance(v, str):
        return None
    v = v.strip()
    return v or None
