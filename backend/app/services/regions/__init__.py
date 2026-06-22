"""Region registry — single source of truth for KATHA's 8 global markets.

KATHA is positioned as a universal OS for architects worldwide. Every
market needs (a) the right currency for cost output and (b) the right
building-code jurisdiction for compliance citations. This module is the
one place that maps a region to both, plus the locale/symbol used in the
UI.

Resolution model
----------------
- ``jurisdiction``  → primary ``building_standards.jurisdiction`` key the
  standards resolver should try first. The resolver already falls back to
  ``baseline`` (``international_ibc``) when a specific row is missing, so a
  region whose codes aren't fully seeded yet still validates against the
  international baseline instead of erroring.
- ``currency``      → ISO-4217 code used for cost output. Must exist in
  ``estimation.catalog.DEFAULT_CONVERSION_RATES`` so the FX layer can
  convert the INR-denominated rate-cards into the region's currency.

Demo-critical (CEO client demos, Dubai + Germany):
  * ``middle_east`` → AED + ``uae_dubai`` codes
  * ``europe``      → EUR + ``eu_eurocode`` codes (DIN for Germany)
  * ``india``       → INR + ``india_nbc`` (home market, fully seeded)

The other five regions route to the international baseline (IBC + ISO)
until their native codes are authored — the architecture is N-region
ready; only the *content* is staged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The international fallback jurisdiction. Seeded today (IBC 2021 / IECC).
BASELINE_JURISDICTION = "international_ibc"
DEFAULT_REGION = "india"


@dataclass(frozen=True)
class Region:
    key: str
    label: str
    # Standards
    jurisdiction: str
    # Currency / formatting
    currency: str
    currency_symbol: str
    locale: str
    # Whether this region's native codes are seeded with real values
    # (vs. routing to the international baseline). Drives an honest
    # "approximate / international baseline" badge in the UI.
    codes_seeded: bool = False
    # Human-facing note about the code basis (shown in compliance panel).
    code_basis: str = "International Building Code (IBC 2021) baseline"
    aliases: tuple[str, ...] = field(default_factory=tuple)


# ── The 8 markets ────────────────────────────────────────────────────────────
REGIONS: dict[str, Region] = {
    "india": Region(
        key="india",
        label="India",
        jurisdiction="india_nbc",
        currency="INR",
        currency_symbol="₹",
        locale="en-IN",
        codes_seeded=True,
        code_basis="National Building Code of India 2016 (NBC) + ECBC + IS codes",
        aliases=("in", "ind", "bharat"),
    ),
    "europe": Region(
        key="europe",
        label="Europe",
        jurisdiction="eu_eurocode",
        currency="EUR",
        currency_symbol="€",
        locale="de-DE",
        codes_seeded=True,
        code_basis="Eurocodes (EN 1990–1999) + DIN (Germany) + EPBD energy",
        aliases=("eu", "germany", "de", "deutschland", "europa"),
    ),
    "middle_east": Region(
        key="middle_east",
        label="Middle East (GCC)",
        jurisdiction="uae_dubai",
        currency="AED",
        currency_symbol="AED",
        locale="en-AE",
        codes_seeded=True,
        code_basis="UAE / Dubai Building Code + Estidama + Civil Defence fire code",
        aliases=("gcc", "uae", "dubai", "ae", "abu_dhabi"),
    ),
    "north_america": Region(
        key="north_america",
        label="North America",
        jurisdiction=BASELINE_JURISDICTION,
        currency="USD",
        currency_symbol="$",
        locale="en-US",
        codes_seeded=True,  # IBC 2021 + IECC are the native US codes
        code_basis="International Building Code (IBC 2021) + IECC + ADA",
        aliases=("us", "usa", "canada", "na"),
    ),
    "asia_pacific": Region(
        key="asia_pacific",
        label="Asia-Pacific",
        jurisdiction=BASELINE_JURISDICTION,
        currency="USD",
        currency_symbol="$",
        locale="en-SG",
        aliases=("apac", "asia", "singapore", "japan"),
    ),
    "latin_america": Region(
        key="latin_america",
        label="Latin America",
        jurisdiction=BASELINE_JURISDICTION,
        currency="USD",
        currency_symbol="$",
        locale="es-419",
        aliases=("latam", "brazil", "mexico"),
    ),
    "africa": Region(
        key="africa",
        label="Africa",
        jurisdiction=BASELINE_JURISDICTION,
        currency="USD",
        currency_symbol="$",
        locale="en-ZA",
        aliases=("za", "nigeria", "kenya"),
    ),
    "oceania": Region(
        key="oceania",
        label="Oceania",
        jurisdiction=BASELINE_JURISDICTION,
        currency="AUD",
        currency_symbol="A$",
        locale="en-AU",
        aliases=("australia", "au", "nz", "new_zealand"),
    ),
}

# Reverse lookup: alias / country → canonical region key.
_ALIAS_INDEX: dict[str, str] = {}
for _key, _region in REGIONS.items():
    _ALIAS_INDEX[_key] = _key
    for _alias in _region.aliases:
        _ALIAS_INDEX[_alias] = _key


def normalize_region(value: str | None) -> str:
    """Coerce any region key / alias / country name to a canonical key.

    Unknown / empty values fall back to :data:`DEFAULT_REGION` so the
    pipeline never has to guard against a missing region.
    """
    if not value:
        return DEFAULT_REGION
    token = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    return _ALIAS_INDEX.get(token, DEFAULT_REGION)


def get_region(value: str | None) -> Region:
    """Return the :class:`Region` for any key / alias, defaulting safely."""
    return REGIONS[normalize_region(value)]


def jurisdiction_for_region(value: str | None) -> str:
    """Primary standards jurisdiction for a region."""
    return get_region(value).jurisdiction


def currency_for_region(value: str | None) -> str:
    """ISO-4217 currency code for a region."""
    return get_region(value).currency


def list_regions() -> list[dict]:
    """Serialisable region catalogue for the frontend selector."""
    return [
        {
            "key": r.key,
            "label": r.label,
            "currency": r.currency,
            "currency_symbol": r.currency_symbol,
            "jurisdiction": r.jurisdiction,
            "code_basis": r.code_basis,
            "codes_seeded": r.codes_seeded,
            "locale": r.locale,
        }
        for r in REGIONS.values()
    ]


__all__ = [
    "Region",
    "REGIONS",
    "DEFAULT_REGION",
    "BASELINE_JURISDICTION",
    "normalize_region",
    "get_region",
    "jurisdiction_for_region",
    "currency_for_region",
    "list_regions",
]
