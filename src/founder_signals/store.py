from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path
from typing import Iterable, Optional

from .schema import Profile, Stage


def profile_id(linkedin_url: Optional[str], name: Optional[str] = None,
               company: Optional[str] = None) -> str:
    if linkedin_url:
        key = _normalize_url(linkedin_url)
    else:
        key = f"{(name or '').strip().lower()}|{(company or '').strip().lower()}"
    return "p_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _fold_diacritics(s: str) -> str:
    s = s.replace("ı", "i").replace("İ", "i")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _normalize_url(url: str) -> str:
    u = url.strip().lower().rstrip("/")
    u = u.split("?")[0]
    u = u.replace("http://", "https://")
    u = re.sub(r"^https://[a-z0-9-]+\.linkedin\.com", "https://linkedin.com", u)
    return _fold_diacritics(u)


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    id            TEXT PRIMARY KEY,
                    linkedin_url  TEXT,
                    region        TEXT,
                    stages_done   TEXT,
                    rank_score    REAL,
                    confidence    REAL,
                    data          TEXT NOT NULL,
                    last_updated  TEXT
                )
                """
            )
            conn.commit()

    def upsert(self, profile: Profile) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO profiles (id, linkedin_url, region, stages_done,
                                      rank_score, confidence, data, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    linkedin_url=excluded.linkedin_url,
                    region=excluded.region,
                    stages_done=excluded.stages_done,
                    rank_score=excluded.rank_score,
                    confidence=excluded.confidence,
                    data=excluded.data,
                    last_updated=excluded.last_updated
                """,
                (
                    profile.id,
                    profile.linkedin_url,
                    profile.region.value if profile.region.value else None,
                    json.dumps([s.value for s in profile.stages_done]),
                    profile.rank_score,
                    profile.overall_confidence,
                    profile.model_dump_json(),
                    profile.last_updated,
                ),
            )
            conn.commit()

    def upsert_many(self, profiles: Iterable[Profile]) -> int:
        n = 0
        for p in profiles:
            self.upsert(p)
            n += 1
        return n

    def get(self, pid: str) -> Optional[Profile]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT data FROM profiles WHERE id=?", (pid,)).fetchone()
            return Profile.model_validate_json(row["data"]) if row else None

    def all(self) -> list[Profile]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT data FROM profiles").fetchall()
            return [Profile.model_validate_json(r["data"]) for r in rows]

    def needing_stage(self, stage: Stage) -> list[Profile]:
        return [p for p in self.all() if stage not in p.stages_done]

    def ranked(self, limit: Optional[int] = None) -> list[Profile]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT data FROM profiles WHERE rank_score IS NOT NULL "
                "ORDER BY rank_score DESC"
            ).fetchall()
        profiles = [Profile.model_validate_json(r["data"]) for r in rows]
        return profiles[:limit] if limit else profiles

    def count(self) -> int:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) AS c FROM profiles").fetchone()["c"]

    def clear(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM profiles")
            conn.commit()
