from __future__ import annotations

import re

from .schema import Region

_COUNTRY_REGION: dict[str, Region] = {}

_TURKIYE = ["turkiye", "türkiye", "turkey"]
_CEE = [
    "poland", "czechia", "czech republic", "slovakia", "hungary", "romania",
    "bulgaria", "slovenia", "croatia", "serbia", "bosnia and herzegovina",
    "bosnia", "montenegro", "north macedonia", "macedonia", "albania", "kosovo",
    "estonia", "latvia", "lithuania", "ukraine", "moldova", "belarus",
]
_CAUCASUS = ["georgia", "armenia", "azerbaijan"]

for _c in _TURKIYE:
    _COUNTRY_REGION[_c] = Region.TURKIYE
for _c in _CEE:
    _COUNTRY_REGION[_c] = Region.CEE
for _c in _CAUCASUS:
    _COUNTRY_REGION[_c] = Region.CAUCASUS

_CITY_COUNTRY: dict[str, str] = {
    # Türkiye
    "istanbul": "turkiye", "ankara": "turkiye", "izmir": "turkiye",
    "bursa": "turkiye", "antalya": "turkiye", "kocaeli": "turkiye",
    # Poland
    "warsaw": "poland", "warszawa": "poland", "krakow": "poland",
    "kraków": "poland", "wroclaw": "poland", "gdansk": "poland",
    # Czechia / Slovakia / Hungary
    "prague": "czechia", "praha": "czechia", "brno": "czechia",
    "bratislava": "slovakia", "budapest": "hungary",
    # Romania / Bulgaria
    "bucharest": "romania", "cluj": "romania", "cluj-napoca": "romania",
    "sofia": "bulgaria",
    # Baltics
    "tallinn": "estonia", "tartu": "estonia", "riga": "latvia",
    "vilnius": "lithuania", "kaunas": "lithuania",
    # Ukraine / Moldova
    "kyiv": "ukraine", "kiev": "ukraine", "lviv": "ukraine",
    "kharkiv": "ukraine", "chisinau": "moldova",
    # Balkans
    "zagreb": "croatia", "belgrade": "serbia", "ljubljana": "slovenia",
    "sarajevo": "bosnia", "skopje": "north macedonia", "tirana": "albania",
    # Caucasus
    "tbilisi": "georgia", "batumi": "georgia", "yerevan": "armenia",
    "baku": "azerbaijan",
}


def resolve_region(location_raw: str | None) -> tuple[str | None, str | None, Region]:
    if not location_raw:
        return None, None, Region.UNKNOWN

    raw = location_raw.strip()
    text = raw.lower()
    looks_us = any(m in text for m in _US_MARKERS)

    for country, region in _COUNTRY_REGION.items():
        if _has_word(text, country):
            # Avoid treating the US state as the country.
            if country == "georgia" and looks_us:
                continue
            city = _first_city_token(raw)
            if city and city.lower() in _COUNTRY_REGION:
                city = None
            return city, country, region

    for city, country in _CITY_COUNTRY.items():
        if _has_word(text, city):
            return city.title(), country, _COUNTRY_REGION.get(country, Region.UNKNOWN)

    return _first_city_token(raw), None, Region.OTHER


_US_MARKERS = ("united states", "usa", ", us", "u.s.", "atlanta")


def _has_word(text: str, word: str) -> bool:
    return re.search(r"\b" + re.escape(word) + r"\b", text) is not None


def _first_city_token(text: str) -> str | None:
    # Use the original-case text and title-case it so "i̇stanbul" -> "İstanbul".
    head = text.split(",")[0].strip()
    return head.title() if head else None


_CC_REGION: dict[str, tuple[str, Region]] = {
    "tr": ("turkiye", Region.TURKIYE),
    "pl": ("poland", Region.CEE), "cz": ("czechia", Region.CEE),
    "sk": ("slovakia", Region.CEE), "hu": ("hungary", Region.CEE),
    "ro": ("romania", Region.CEE), "bg": ("bulgaria", Region.CEE),
    "si": ("slovenia", Region.CEE), "hr": ("croatia", Region.CEE),
    "rs": ("serbia", Region.CEE), "ee": ("estonia", Region.CEE),
    "lv": ("latvia", Region.CEE), "lt": ("lithuania", Region.CEE),
    "ua": ("ukraine", Region.CEE), "md": ("moldova", Region.CEE),
    "ge": ("georgia", Region.CAUCASUS), "am": ("armenia", Region.CAUCASUS),
    "az": ("azerbaijan", Region.CAUCASUS),
}

_OUT_OF_SCOPE_CC = {
    "in", "us", "uk", "gb", "de", "fr", "es", "it", "nl", "be", "ch", "at",
    "se", "no", "dk", "fi", "ie", "pt", "ru", "ca", "au", "br", "mx", "jp",
    "cn", "hk", "kr", "il", "eg", "ng", "za", "pk", "id", "my", "th", "vn",
    "ph", "sg", "ae", "sa", "qa", "kw", "gr",
}

_LINKEDIN_CC_RE = re.compile(r"https?://([a-z]{2})\.linkedin\.com/", re.I)


def region_from_linkedin_url(url: str | None) -> tuple[str | None, Region]:
    if not url:
        return None, Region.UNKNOWN
    m = _LINKEDIN_CC_RE.search(url)
    if not m:
        return None, Region.UNKNOWN
    cc = m.group(1).lower()
    if cc in _CC_REGION:
        return _CC_REGION[cc]
    if cc in _OUT_OF_SCOPE_CC:
        return cc.upper(), Region.OTHER
    return None, Region.UNKNOWN


def in_scope(region: Region) -> bool:
    return region in (Region.TURKIYE, Region.CEE, Region.CAUCASUS)
