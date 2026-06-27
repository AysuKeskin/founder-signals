from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["FS_SOURCE"] = "cached"

from founder_signals.config import Config  # noqa: E402
from founder_signals.logging_utils import make_logger  # noqa: E402
from founder_signals.pipeline import runner  # noqa: E402
from founder_signals.regions import (  # noqa: E402
    Region, in_scope, region_from_linkedin_url, resolve_region,
)
from founder_signals.schema import FieldValue, Profile  # noqa: E402
from founder_signals.sources.cached import CachedDiscoverySource  # noqa: E402
from founder_signals.store import Store, profile_id  # noqa: E402


@pytest.fixture()
def cfg(tmp_path: Path) -> Config:
    os.environ["FS_SOURCE"] = "cached"
    os.environ["FS_DATA_DIR"] = str(tmp_path)
    c = Config()
    c.ensure_dirs()
    return c


def test_dotenv_loads_and_shell_wins(tmp_path, monkeypatch):
    from founder_signals.config import _load_dotenv
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("FS_DEMO_A=from_env\nFS_DEMO_B=from_env\n")
    monkeypatch.setenv("FS_DEMO_B", "from_shell")
    _load_dotenv()
    assert os.environ["FS_DEMO_A"] == "from_env"
    assert os.environ["FS_DEMO_B"] == "from_shell"


@pytest.mark.parametrize("loc,expected", [
    ("Istanbul, Türkiye", Region.TURKIYE),
    ("Warsaw, Poland", Region.CEE),
    ("Tbilisi", Region.CAUCASUS),
    ("Yerevan, Armenia", Region.CAUCASUS),
    ("San Francisco, USA", Region.OTHER),
    ("", Region.UNKNOWN),
])
def test_resolve_region(loc, expected):
    _city, _country, region = resolve_region(loc)
    assert region == expected


@pytest.mark.parametrize("url,expected", [
    ("https://tr.linkedin.com/in/someone", Region.TURKIYE),
    ("https://pl.linkedin.com/in/someone", Region.CEE),
    ("https://ge.linkedin.com/in/someone", Region.CAUCASUS),
    ("https://in.linkedin.com/in/someone", Region.OTHER),
    ("https://de.linkedin.com/in/someone", Region.OTHER),
    ("https://www.linkedin.com/in/someone", Region.UNKNOWN),
    (None, Region.UNKNOWN),
])
def test_region_from_linkedin_url(url, expected):
    _country, region = region_from_linkedin_url(url)
    assert region == expected


def test_in_scope():
    assert in_scope(Region.TURKIYE)
    assert in_scope(Region.CEE)
    assert in_scope(Region.CAUCASUS)
    assert not in_scope(Region.OTHER)
    assert not in_scope(Region.UNKNOWN)


def test_profile_id_is_stable_and_dedupes():
    a = profile_id("https://www.linkedin.com/in/jane-doe/")
    b = profile_id("http://linkedin.com/in/jane-doe?trk=foo")
    c = profile_id("https://tr.linkedin.com/in/jane-doe")
    assert a == b == c


def test_profile_id_folds_turkish_chars():
    ascii_id = profile_id("https://tr.linkedin.com/in/murat-caliskan-8319441ab")
    turkish_id = profile_id("https://tr.linkedin.com/in/murat-çalışkan-8319441ab")
    other = profile_id("https://tr.linkedin.com/in/murat-çalışkan-6566b7156")
    assert ascii_id == turkish_id
    assert other != ascii_id


@pytest.mark.parametrize("loc,expected", [
    ("Georgian Bay, Canada", Region.OTHER),
    ("Atlanta, Georgia, USA", Region.OTHER),
    ("Tbilisi, Georgia", Region.CAUCASUS),
])
def test_region_word_boundary_and_us_guard(loc, expected):
    _city, _country, region = resolve_region(loc)
    assert region == expected


@pytest.mark.parametrize("loc,country", [
    ("Turkey", "turkey"),
    ("Türkiye", "türkiye"),
    ("Armenia", "armenia"),
])
def test_country_only_location_is_not_a_city(loc, country):
    city, resolved_country, region = resolve_region(loc)
    assert city is None
    assert resolved_country == country
    assert region != Region.UNKNOWN


def test_city_country_location_keeps_city():
    city, country, region = resolve_region("Istanbul, Turkey")
    assert city == "Istanbul"
    assert country == "turkey"
    assert region == Region.TURKIYE


def test_store_upsert_idempotent(cfg):
    store = Store(cfg.store_path)
    p = Profile(id="p_test", full_name=FieldValue(value="X", confidence=0.5))
    store.upsert(p)
    store.upsert(p)
    assert store.count() == 1


def test_cached_replays_recorded_enrichment():
    from founder_signals.sources import cached
    if not cached.USING_REAL_SEEDS:
        pytest.skip("no recorded seed fixture present")
    prov = cached.CachedEnrichmentProvider()
    enriched = 0
    for url, rec in list(cached._REAL_ENRICH.items())[:50]:
        data = prov.enrich(rec.get("name") or "", rec.get("company"), url)
        assert data.sectors == (rec.get("sectors") or [])
        assert data.company_stage == rec.get("company_stage")
        enriched += bool(data.sectors)
    assert enriched > 0


@pytest.mark.parametrize("text,expected", [
    ("closed a Series A funding round", "series a"),
    ("backed by Y Combinator (YC W23)", "accelerator-backed"),
    ("Backed By 500 Startups", "accelerator-backed"),
    ("the startup raised $2.5M", "funded"),
    ("bootstrapped and profitable", "bootstrapped"),
    ("Co-Founder & CTO @ Semender AI", None),
])
def test_stage_detection_widened(text, expected):
    from founder_signals.sources.web_enrich import _detect_stage
    assert _detect_stage(text) == expected


def test_cached_source_deterministic():
    s1 = CachedDiscoverySource().search("fintech istanbul", 10)
    s2 = CachedDiscoverySource().search("fintech istanbul", 10)
    assert [h.url for h in s1] == [h.url for h in s2]
    assert len(s1) == 10


@pytest.mark.parametrize("snippet,expected", [
    ("Mert Akdemir - Founder & CEO @ Luximora", "Luximora"),
    ("Büşra Koçak - Co-Founder & CTO @ Semender AI", "Semender AI"),
    ("Kadir Bulut - AI Startup Factory @ İş Bank Group", "İş Bank Group"),
    ("Hasan Çağrı Güngör - Finis AI & Dashy Digital co-Founder", "Finis AI & Dashy Digital"),
    ("Okan Tübek - Ogan AI", "Ogan AI"),
    ("Kadir Nezih Elgun - eTaşın", "eTaşın"),
    ("Karol Kucharski - CEO & Co-Founder of Gaming Network", "Gaming Network"),
    ("Cankat Tigin Öztemiz - CEO & Founder @gamegine", "gamegine"),
    ("Özge Akgül Altmışdört - Co- Founder Manya Consulting", "Manya Consulting"),
    ("Someone - Head of Marketing", None),
    ("Vilmar Vella - Co-Founder | Deneyim: ReadyCode Ltd · Konum: Izmir", "ReadyCode Ltd"),
    ("Bora Altun - İstanbul, Türkiye", None),
    ("Mario Skočić - AI Startup", None),
    ("Vusal Ibrahimli - Co-Founder | Deneyim: Stealth AI Startup", None),
    ("Adrian M - SaaS Founder, Agency Owner, Basketball Addict", None),
    ("Berker Yenal - Co-Founder | Deneyim: QberX — QRegu", "QberX"),
])
def test_company_extraction_patterns(snippet, expected):
    from founder_signals.pipeline.extract import _extract_one
    p = Profile(id="p_c", raw_snippet=snippet)
    p.full_name = FieldValue(value=snippet.split(" - ")[0], confidence=0.6)
    _extract_one(p)
    assert p.current_company.value == expected


def test_llm_extractor_parses_and_is_off_by_default(cfg):
    from founder_signals.sources.llm_extract import _parse, llm_available

    assert llm_available(cfg) is False

    f = _parse('{"company":"Acme AI","role":"Co-Founder","city":"İstanbul",'
               '"sectors":["AI/ML"],"is_founder":true}')
    assert f.company == "Acme AI" and f.role == "Co-Founder"
    assert f.city == "İstanbul" and f.sectors == ["AI/ML"] and f.is_founder is True

    assert _parse("not json") is None
    bad = _parse('{"company":123,"sectors":"AI"}')
    assert bad.company is None and bad.sectors is None


def test_full_pipeline_produces_100(cfg):
    store = Store(cfg.store_path)
    logger = make_logger(cfg.runs_dir, echo=False)
    result = runner.run_all(cfg, store, logger, target=100)
    assert result.count == 100

    validation = runner.validate_export(cfg.exports_dir / "founders.json", target=100)
    checks = validation.data["checks"]
    assert checks["count_ok"]
    assert checks["all_valid_schema"]
    assert checks["all_in_scope"]
    assert checks["all_named"]


def test_linkedin_provider_satisfies_contract(cfg):
    import os as _os

    from founder_signals.sources.base import EnrichmentProvider
    from founder_signals.sources.linkedin_provider import LinkedInProfileProvider
    from founder_signals.sources.registry import enrichment_provider

    prov = LinkedInProfileProvider(api_key=None)
    assert isinstance(prov, EnrichmentProvider)

    _os.environ["FS_ENRICH"] = "linkedin"
    selected = enrichment_provider(Config())
    assert isinstance(selected, LinkedInProfileProvider)
    _os.environ["FS_ENRICH"] = "auto"

    with pytest.raises(NotImplementedError):
        prov.enrich("Jane", "Acme", "https://linkedin.com/in/jane")


def test_ranking_zeros_out_of_scope():
    from founder_signals.pipeline.rank import score_profile
    p = Profile(id="p_oos")
    p.region = FieldValue(value="other", confidence=0.5)
    assert score_profile(p) == 0.0


@pytest.mark.parametrize("headline,expected", [
    ("Co-Founder & CEO at Acme", True),
    ("Kurucu Ortak @ Startup", True),
    ("Kurucu | Fintech", True),
    ("Owner at BrewShot", True),
    ("Girişimci | SaaS", True),
    ("Product Specialist @ Taptoweb", False),
    ("General Partner at Firstpoint VC", False),
])
def test_founder_detection_multilingual(headline, expected):
    from founder_signals.pipeline.normalize import _is_founder
    p = Profile(id="p_f")
    p.headline = FieldValue(value=headline, confidence=0.5)
    assert _is_founder(p) is expected


def test_ranking_prefers_earlier_stage():
    from founder_signals.pipeline.rank import score_profile

    def founder_at(stage):
        p = Profile(id=f"p_{stage}")
        p.region = FieldValue(value="turkiye", confidence=0.7)
        p.is_founder = FieldValue(value=True, confidence=0.7)
        p.current_company = FieldValue(value="Acme", confidence=0.6)
        p.company_stage = FieldValue(value=stage, confidence=0.6)
        return p

    assert score_profile(founder_at("pre-seed")) > score_profile(founder_at("series b"))
    assert score_profile(founder_at("seed")) > score_profile(founder_at("acquired"))


def test_ranking_prefers_founder_over_nonfounder():
    from founder_signals.pipeline.rank import score_profile
    founder = Profile(id="p_a")
    founder.region = FieldValue(value="turkiye", confidence=0.7)
    founder.is_founder = FieldValue(value=True, confidence=0.7)
    non = Profile(id="p_b")
    non.region = FieldValue(value="turkiye", confidence=0.7)
    non.is_founder = FieldValue(value=False, confidence=0.7)
    assert score_profile(founder) > score_profile(non)


def _founder(pid, name, company, sectors, region="turkiye"):
    p = Profile(id=pid)
    p.full_name = FieldValue(value=name, confidence=0.7)
    p.current_company = FieldValue(value=company, confidence=0.6)
    p.region = FieldValue(value=region, confidence=0.7)
    p.sectors = FieldValue(value=sectors, confidence=0.7)
    p.rank_score = 0.8
    return p


def test_graph_builds_nodes_and_edges():
    from founder_signals.pipeline.graph import build_graph
    profiles = [
        _founder("p1", "Ada A", "AcmeAI", ["AI/ML", "Fintech"]),
        _founder("p2", "Bora B", "BetaAI", ["AI/ML"]),
        _founder("p3", "Ceyda C", "GammaPay", ["Fintech"], region="cee"),
    ]
    g = build_graph(profiles)
    assert g["stats"]["founders"] == 3
    assert g["stats"]["companies"] == 3
    cluster_sectors = {c["sector"] for c in g["clusters"]}
    assert "AI/ML" in cluster_sectors and "Fintech" in cluster_sectors
    assert any(e["rel"] == "FOUNDED" for e in g["edges"])
    assert any(e["rel"] == "IN_SECTOR" for e in g["edges"])


def test_connections_finds_shared_sector(cfg):
    from founder_signals.pipeline.graph import connections
    store = Store(cfg.store_path)
    store.upsert(_founder("p1", "Ada A", "AcmeAI", ["AI/ML"]))
    store.upsert(_founder("p2", "Bora B", "BetaAI", ["AI/ML"]))
    store.upsert(_founder("p3", "Ceyda C", "GammaPay", ["Fintech"]))
    res = connections(store, "p1")
    names = {c["name"] for c in res.data["connections"]}
    assert "Bora B" in names
    assert "Ceyda C" not in names


def test_diff_detects_new_and_dropped(cfg, tmp_path):
    import json

    from founder_signals.pipeline.history import run_diff

    def export(records):
        path = cfg.exports_dir / "founders.json"
        path.write_text(json.dumps(records), encoding="utf-8")
        return path

    def rec(pid, name):
        return {"id": pid, "linkedin_url": f"https://linkedin.com/in/{pid}",
                "full_name": {"value": name}, "region": {"value": "turkiye"},
                "rank_score": 0.8}

    logger = make_logger(cfg.runs_dir, echo=False)
    export([rec("a", "Ada"), rec("b", "Bora")])
    first = run_diff(cfg.exports_dir / "founders.json", cfg.history_dir, logger, commit=True)
    assert first.data["baseline"] is True

    export([rec("a", "Ada"), rec("c", "Ceyda")])
    second = run_diff(cfg.exports_dir / "founders.json", cfg.history_dir, logger)
    new_names = {n["name"] for n in second.data["new"]}
    dropped_names = {n["name"] for n in second.data["dropped"]}
    assert new_names == {"Ceyda"}
    assert dropped_names == {"Bora"}
    assert second.data["retained_count"] == 1
    assert second.data["committed"] is False  


def test_diff_baseline_anchored_to_capture_not_replay(cfg):
    import json

    from founder_signals.pipeline.history import run_diff, snapshot_fixture
    from founder_signals.store import profile_id

    old_fixture = cfg.exports_dir / "fixture_old.json"
    old_fixture.write_text(json.dumps([
        {"name": "Ada", "url": "https://linkedin.com/in/ada", "region": "turkiye"},
        {"name": "Bora", "url": "https://linkedin.com/in/bora", "region": "cee"},
    ]), encoding="utf-8")
    n = snapshot_fixture(old_fixture, cfg.history_dir)
    assert n == 2

    def rec(name, url):
        return {"id": profile_id(url), "linkedin_url": url,
                "full_name": {"value": name}, "region": {"value": "turkiye"},
                "rank_score": 0.8}
    (cfg.exports_dir / "founders.json").write_text(json.dumps([
        rec("Ada", "https://linkedin.com/in/ada"),
        rec("Bora", "https://linkedin.com/in/bora"),
    ]), encoding="utf-8")

    logger = make_logger(cfg.runs_dir, echo=False)
    res = run_diff(cfg.exports_dir / "founders.json", cfg.history_dir, logger)
    assert len(res.data["new"]) == 0
    assert len(res.data["dropped"]) == 0
    assert res.data["retained_count"] == 2
