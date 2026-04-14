"""Static price catalog and versioned defaults for the estimation engine."""

from __future__ import annotations

from decimal import Decimal

CURRENCY = "INR"
DEFAULT_ESTIMATE_VERSION = "v1"
DEFAULT_CATALOG_VERSION = "v2"
DEFAULT_CATALOG_LAST_UPDATED = "2026-03-28T00:00:00Z"

MATERIAL_RATES: dict[str, Decimal] = {
    "paint": Decimal("18"),
    "wallpaper": Decimal("58"),
    "tile_ceramic": Decimal("92"),
    "tile_marble": Decimal("240"),
    "hardwood": Decimal("280"),
    "laminate": Decimal("115"),
    "carpet": Decimal("84"),
    "concrete": Decimal("36"),
    "brick": Decimal("65"),
    "glass": Decimal("210"),
    "fabric": Decimal("115"),
    "wood_panel": Decimal("175"),
    "stone_natural": Decimal("320"),
    "plaster": Decimal("26"),
    "metal": Decimal("410"),
    "default": Decimal("95"),
}

FURNITURE_RATES: dict[str, Decimal] = {
    "sofa": Decimal("25000"),
    "table": Decimal("12000"),
    "chair": Decimal("4500"),
    "bed": Decimal("32000"),
    "desk": Decimal("14000"),
    "shelf": Decimal("9000"),
    "bookshelf": Decimal("16000"),
    "cabinet": Decimal("18000"),
    "wardrobe": Decimal("42000"),
    "dining_table": Decimal("28000"),
    "coffee_table": Decimal("9000"),
    "tv_unit": Decimal("22000"),
    "rug": Decimal("6500"),
    "default": Decimal("15000"),
}

FIXTURE_RATES: dict[str, Decimal] = {
    "door": Decimal("9000"),
    "window": Decimal("7500"),
    "light_fixture": Decimal("3500"),
    "fan": Decimal("4200"),
    "switch_board": Decimal("450"),
    "outlet": Decimal("280"),
    "default": Decimal("2500"),
}

SERVICE_RATES: dict[str, Decimal] = {
    "design_consultation": Decimal("35"),
    "site_supervision": Decimal("22"),
    "project_management": Decimal("18"),
}

LABOR_RATES: dict[str, Decimal] = {
    "finishing_labor": Decimal("72"),
    "installation_labor": Decimal("48"),
    "carpentry_labor": Decimal("55"),
}

MISC_RATES: dict[str, Decimal] = {
    "logistics": Decimal("0.02"),
    "contingency": Decimal("0.03"),
}

QUALITY_MULTIPLIERS: dict[str, Decimal] = {
    "economy": Decimal("0.90"),
    "budget": Decimal("0.95"),
    "standard": Decimal("1.00"),
    "premium": Decimal("1.18"),
    "luxury": Decimal("1.35"),
}

STYLE_MULTIPLIERS: dict[str, Decimal] = {
    "budget": Decimal("0.92"),
    "standard": Decimal("1.00"),
    "modern": Decimal("1.03"),
    "contemporary": Decimal("1.05"),
    "minimalist": Decimal("0.98"),
    "traditional": Decimal("1.08"),
    "rustic": Decimal("1.06"),
    "industrial": Decimal("1.02"),
    "scandinavian": Decimal("1.04"),
    "bohemian": Decimal("1.07"),
    "premium": Decimal("1.15"),
    "luxury": Decimal("1.28"),
}

REGIONAL_PRICE_INDEX: dict[str, Decimal] = {
    "bangalore": Decimal("1.10"),
    "bengaluru": Decimal("1.10"),
    "mumbai": Decimal("1.18"),
    "delhi": Decimal("1.12"),
    "new delhi": Decimal("1.12"),
    "gurgaon": Decimal("1.11"),
    "hyderabad": Decimal("1.05"),
    "pune": Decimal("1.04"),
    "chennai": Decimal("1.03"),
    "kolkata": Decimal("1.02"),
    "ahmedabad": Decimal("1.01"),
    "default": Decimal("1.00"),
}

DEFAULT_MARKET_VARIATION = Decimal("0.03")
DEFAULT_TAX_RATE = Decimal("0.18")
DEFAULT_DISCOUNT_RATE = Decimal("0.00")
DEFAULT_CONFIDENCE_SCORE = Decimal("0.85")
DEFAULT_COST_PER_SQFT_FALLBACK = Decimal("1500")
SUPPORTED_CURRENCIES = ("INR", "USD", "EUR")
DEFAULT_CONVERSION_RATES: dict[str, Decimal] = {
    "INR": Decimal("1.00"),
    "USD": Decimal("0.012"),
    "EUR": Decimal("0.011"),
}
DEFAULT_PRICING_CONFIG = {
    "material_multipliers": {key: "1.00" for key in MATERIAL_RATES},
    "style_multipliers": {key: str(value) for key, value in STYLE_MULTIPLIERS.items()},
    "quality_multipliers": {key: str(value) for key, value in QUALITY_MULTIPLIERS.items()},
    "regional_price_index": {key: str(value) for key, value in REGIONAL_PRICE_INDEX.items()},
    "market_variation_default": str(DEFAULT_MARKET_VARIATION),
    "tax_default": str(DEFAULT_TAX_RATE),
    "discount_default": str(DEFAULT_DISCOUNT_RATE),
}

FURNITURE_TYPES = set(FURNITURE_RATES) - {"default"}
FIXTURE_TYPES = set(FIXTURE_RATES) - {"default"}
