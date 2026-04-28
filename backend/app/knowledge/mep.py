"""MEP sizing rules — HVAC, electrical, plumbing.

Per BRD Layer 1B. References: ASHRAE 62.1, NEC / IS 732, NBC Part 9.
"""

from __future__ import annotations

# ── HVAC ─────────────────────────────────────────────────────────────────────
# Air changes per hour by use (ASHRAE 62.1 / NBC).
AIR_CHANGES_PER_HOUR: dict[str, float] = {
    "bedroom": 2.0,
    "living_room": 3.0,
    "kitchen": 10.0,         # exhaust driven
    "bathroom": 8.0,
    "office_general": 4.0,
    "conference_room": 8.0,
    "restaurant_dining": 10.0,
    "restaurant_kitchen": 15.0,
    "retail": 6.0,
    "hotel_room": 4.0,
    "gym": 10.0,
    "classroom": 6.0,
}

# CFM per person (fresh air / ventilation).
CFM_PER_PERSON: dict[str, float] = {
    "office": 15,
    "conference": 20,
    "classroom": 15,
    "restaurant": 20,
    "retail": 15,
    "residential": 10,
    "hospital_patient": 25,
    "gym": 20,
}

# Cooling load rule-of-thumb (TR per m^2, tropical India).
COOLING_LOAD_TR_PER_M2: dict[str, float] = {
    "residential": 1 / 13,     # ~ 1 TR / 13 m^2 (~140 sqft)
    "office_general": 1 / 9,
    "restaurant": 1 / 7,
    "retail": 1 / 10,
    "conference": 1 / 7,
    "server_room": 1 / 3,
}

# Duct sizing velocity targets (m/s).
DUCT_VELOCITY_M_S: dict[str, tuple[float, float]] = {
    "main_supply": (6.0, 9.0),
    "branch": (3.0, 5.0),
    "return": (4.0, 6.0),
    "residential": (3.0, 5.0),
}


def hvac_cfm(room_volume_m3: float, use_type: str) -> dict:
    """Total fresh-air CFM required for a room."""
    ach = AIR_CHANGES_PER_HOUR.get(use_type)
    if not ach:
        return {"error": f"Unknown use_type '{use_type}'"}
    cfm = (room_volume_m3 * 35.31 * ach) / 60.0  # m^3 -> ft^3, divide by 60 min
    return {"ach": ach, "cfm_total": round(cfm, 1), "use_type": use_type}


def cooling_tr(area_m2: float, use_type: str) -> dict:
    factor = COOLING_LOAD_TR_PER_M2.get(use_type)
    if not factor:
        return {"error": f"No cooling factor for '{use_type}'"}
    tr = area_m2 * factor
    return {"tonnage": round(tr, 2), "use_type": use_type}


# 1 ton of refrigeration = 12,000 BTU/hr (≈ 3.517 kW).
BTU_PER_TR: int = 12_000
KW_PER_TR: float = 3.517


def equipment_capacity(tonnage: float) -> dict:
    """Tonnage → BTU/hr and kW thermal."""
    return {
        "tonnage": round(float(tonnage), 2),
        "btu_per_hr": round(float(tonnage) * BTU_PER_TR, 0),
        "kw_thermal": round(float(tonnage) * KW_PER_TR, 2),
    }


# Equipment shortlist by tonnage band (Indian market standard sizes).
EQUIPMENT_BAND_TR: list[tuple[float, str]] = [
    (0.8,  "0.75 TR wall split"),
    (1.2,  "1.0 TR wall split"),
    (1.7,  "1.5 TR wall split"),
    (2.2,  "2.0 TR wall split / cassette"),
    (3.5,  "3.0 TR cassette / ducted"),
    (5.5,  "5.0 TR ducted / VRF indoor"),
    (8.5,  "7.5–8 TR VRF indoor"),
    (11.0, "10 TR VRF indoor"),
    (16.0, "15 TR rooftop / VRF"),
    (22.0, "20 TR rooftop / chiller"),
]


def equipment_shortlist(tonnage_required: float) -> dict:
    """Pick the smallest standard unit that meets the load."""
    for cap_tr, label in EQUIPMENT_BAND_TR:
        if tonnage_required <= cap_tr + 1e-6:
            return {"required_tr": round(tonnage_required, 2), "selected_tr": cap_tr, "type": label}
    return {
        "required_tr": round(tonnage_required, 2),
        "selected_tr": EQUIPMENT_BAND_TR[-1][0],
        "type": EQUIPMENT_BAND_TR[-1][1],
        "note": "Exceeds top band — split into multiple units or step up to chilled water.",
    }


# ── Ductwork sizing ─────────────────────────────────────────────────────────
# Round-duct diameter chart by CFM at residential / branch velocity (≈ 4 m/s).
# Q [CFM] = A [ft²] × V [fpm]; converted to mm.
DUCT_ROUND_DIAMETER_MM_BY_CFM: list[tuple[int, int]] = [
    (50,    150),
    (100,   200),
    (200,   250),
    (350,   300),
    (500,   350),
    (700,   400),
    (1000,  450),
    (1400,  500),
    (1900,  550),
    (2500,  600),
    (3500,  700),
    (5000,  800),
]


def duct_round_diameter(cfm: float) -> dict:
    for limit, dia in DUCT_ROUND_DIAMETER_MM_BY_CFM:
        if cfm <= limit:
            return {"cfm": round(cfm, 1), "diameter_mm": dia}
    return {
        "cfm": round(cfm, 1),
        "diameter_mm": DUCT_ROUND_DIAMETER_MM_BY_CFM[-1][1],
        "note": "Exceeds chart — split into parallel runs or step up to rectangular trunk.",
    }


def duct_rectangular_for_cfm(cfm: float, *, velocity_m_s: float = 5.0,
                             aspect_ratio: float = 2.0) -> dict:
    """Return W × H (mm) for a rectangular duct sized to the velocity target."""
    if cfm <= 0 or velocity_m_s <= 0:
        return {"error": "cfm and velocity must be positive"}
    cfm_per_m3s = 0.000471947
    area_m2 = (cfm * cfm_per_m3s) / velocity_m_s
    height_m = (area_m2 / aspect_ratio) ** 0.5
    width_m = height_m * aspect_ratio
    return {
        "cfm": round(cfm, 1),
        "velocity_m_s": velocity_m_s,
        "aspect_ratio": aspect_ratio,
        "area_m2": round(area_m2, 4),
        "width_mm": int(round(width_m * 1000 / 25) * 25),     # snap to 25 mm
        "height_mm": int(round(height_m * 1000 / 25) * 25),
    }


# Supply / return register coverage (CFM each, residential / light commercial).
REGISTER_CFM_RATING: dict[str, int] = {
    "supply_4x10": 80,
    "supply_4x12": 100,
    "supply_6x10": 130,
    "supply_6x12": 160,
    "return_grille_20x20": 600,
    "return_grille_24x24": 800,
}


def register_count(total_cfm: float, *, register_key: str = "supply_6x10") -> dict:
    rating = REGISTER_CFM_RATING.get(register_key)
    if not rating:
        return {"error": f"Unknown register '{register_key}'"}
    n = max(1, int(-(-total_cfm // rating)))  # ceil
    return {
        "total_cfm": round(total_cfm, 1),
        "register_type": register_key,
        "cfm_per_register": rating,
        "count": n,
        "spacing_rule": "supply registers along external/long walls; return central in ceiling or low side wall, ≥ 3 m from supply.",
    }


# ── Electrical ───────────────────────────────────────────────────────────────
LUX_LEVELS: dict[str, int] = {
    "bedroom_general": 100,
    "bedroom_reading": 300,
    "living_room_general": 150,
    "living_room_task": 400,
    "kitchen_general": 300,
    "kitchen_counter": 500,
    "bathroom": 200,
    "office_general": 500,
    "office_task": 750,
    "conference_room": 500,
    "corridor": 100,
    "staircase": 150,
    "restaurant_dining": 200,
    "retail_general": 500,
    "retail_display": 1000,
}

CIRCUIT_LOAD_W: dict[str, int] = {
    "lighting_circuit_max": 1500,
    "general_outlet_circuit_max": 2400,
    "kitchen_appliance_circuit_max": 3000,
    "ac_dedicated_1_5_ton": 2200,
    "geyser_dedicated": 3000,
    "oven_dedicated": 4000,
}

POWER_DENSITY_W_PER_M2: dict[str, int] = {
    "residential": 30,
    "office_general": 70,
    "office_high_tech": 120,
    "retail": 80,
    "restaurant": 100,
    "server_room": 800,
}


def lighting_circuits(area_m2: float, use: str = "residential") -> dict:
    density = POWER_DENSITY_W_PER_M2.get(use, 40)
    total_w = area_m2 * density
    n = max(1, int(total_w // CIRCUIT_LOAD_W["lighting_circuit_max"]) + 1)
    return {"total_load_w": int(total_w), "lighting_circuits": n, "density_w_m2": density}


# Luminaire catalogue — typical lumen output, wattage, mount, beam (LED, BIS-listed).
FIXTURE_CATALOGUE: dict[str, dict] = {
    "led_downlight_12w":   {"lumens": 1100, "watts": 12, "mount": "recessed_ceiling", "beam": "wide", "use": "ambient"},
    "led_downlight_18w":   {"lumens": 1700, "watts": 18, "mount": "recessed_ceiling", "beam": "wide", "use": "ambient"},
    "led_panel_36w":       {"lumens": 3600, "watts": 36, "mount": "recessed_ceiling", "beam": "wide", "use": "ambient"},
    "led_cob_spot_7w":     {"lumens":  650, "watts":  7, "mount": "track_or_recessed", "beam": "narrow", "use": "accent"},
    "led_cob_spot_15w":    {"lumens": 1400, "watts": 15, "mount": "track_or_recessed", "beam": "narrow", "use": "accent"},
    "led_strip_per_m_10w": {"lumens":  900, "watts": 10, "mount": "concealed_cove",   "beam": "diffuse", "use": "ambient"},
    "led_pendant_20w":     {"lumens": 1800, "watts": 20, "mount": "pendant",          "beam": "wide",   "use": "task"},
    "led_undercabinet_8w": {"lumens":  720, "watts":  8, "mount": "surface_under",    "beam": "wide",   "use": "task"},
    "led_wall_sconce_10w": {"lumens":  800, "watts": 10, "mount": "wall",             "beam": "wide",   "use": "ambient"},
    "led_vanity_bar_15w":  {"lumens": 1300, "watts": 15, "mount": "wall",             "beam": "wide",   "use": "task"},
}

# Indian wiring devices catalogue (IS 1293).
OUTLET_CATALOGUE: dict[str, dict] = {
    "5_15A_universal":       {"rating_a":  6, "phase": "single", "use": "general_outlet",  "circuit_load_w": 1500},
    "16A_three_pin":         {"rating_a": 16, "phase": "single", "use": "appliance",       "circuit_load_w": 3500},
    "20A_three_pin":         {"rating_a": 20, "phase": "single", "use": "ac_or_geyser",    "circuit_load_w": 4400},
    "32A_three_phase":       {"rating_a": 32, "phase": "three",  "use": "oven_or_chiller", "circuit_load_w": 22000},
    "data_rj45_cat6":        {"rating_a":  0, "phase": "low_v",  "use": "data",            "circuit_load_w": 0},
    "tv_coaxial":            {"rating_a":  0, "phase": "low_v",  "use": "tv",              "circuit_load_w": 0},
    "usb_a_c_combo_2.4a":    {"rating_a":  0, "phase": "elv",    "use": "usb_charge",      "circuit_load_w": 24},
}

# Outlet count rule of thumb (BIS / IS 732 + studio practice) — duplex outlets per room type.
OUTLET_COUNT_RULE: dict[str, dict] = {
    "bedroom":         {"general_per_m_wall": 0.30, "min_general": 4, "task_zones": 2},
    "living_room":     {"general_per_m_wall": 0.35, "min_general": 6, "task_zones": 3},
    "kitchen":         {"general_per_m_wall": 0.45, "min_general": 6, "task_zones": 4},
    "bathroom":        {"general_per_m_wall": 0.10, "min_general": 1, "task_zones": 1},
    "office_general":  {"general_per_m_wall": 0.40, "min_general": 4, "task_zones": 2},
    "conference_room": {"general_per_m_wall": 0.40, "min_general": 4, "task_zones": 1},
    "classroom":       {"general_per_m_wall": 0.30, "min_general": 4, "task_zones": 2},
    "restaurant_dining": {"general_per_m_wall": 0.20, "min_general": 4, "task_zones": 1},
    "restaurant_kitchen":{"general_per_m_wall": 0.50, "min_general": 8, "task_zones": 5},
    "retail":          {"general_per_m_wall": 0.30, "min_general": 4, "task_zones": 2},
    "hotel_room":      {"general_per_m_wall": 0.30, "min_general": 4, "task_zones": 2},
    "gym":             {"general_per_m_wall": 0.20, "min_general": 4, "task_zones": 1},
}

# Task-lighting recipe by use — zones, the catalogue fixture to drop, target lumens.
TASK_LIGHTING_RECIPE: dict[str, list[dict]] = {
    "bedroom": [
        {"zone": "bedside",   "fixture_key": "led_pendant_20w",     "target_lumens": 400, "count_default": 2},
        {"zone": "wardrobe",  "fixture_key": "led_undercabinet_8w", "target_lumens": 300, "count_default": 1},
    ],
    "living_room": [
        {"zone": "reading_chair", "fixture_key": "led_pendant_20w", "target_lumens": 600, "count_default": 1},
        {"zone": "tv_wall",       "fixture_key": "led_cob_spot_7w", "target_lumens": 300, "count_default": 2},
    ],
    "kitchen": [
        {"zone": "counter_run",  "fixture_key": "led_undercabinet_8w", "target_lumens": 500, "count_default": 3},
        {"zone": "island_pendants","fixture_key": "led_pendant_20w",   "target_lumens": 800, "count_default": 2},
    ],
    "bathroom": [
        {"zone": "vanity_mirror", "fixture_key": "led_vanity_bar_15w", "target_lumens": 600, "count_default": 1},
    ],
    "office_general": [
        {"zone": "desk",          "fixture_key": "led_pendant_20w", "target_lumens": 750, "count_default": 1},
    ],
    "conference_room": [
        {"zone": "table_pendant", "fixture_key": "led_pendant_20w", "target_lumens": 700, "count_default": 2},
    ],
    "classroom": [
        {"zone": "board_wash",    "fixture_key": "led_panel_36w",   "target_lumens": 800, "count_default": 1},
    ],
    "restaurant_dining": [
        {"zone": "table_pendant", "fixture_key": "led_pendant_20w", "target_lumens": 400, "count_default": 1},
    ],
    "restaurant_kitchen": [
        {"zone": "prep_counter",  "fixture_key": "led_undercabinet_8w", "target_lumens": 700, "count_default": 4},
    ],
    "retail": [
        {"zone": "display_wall",  "fixture_key": "led_cob_spot_15w", "target_lumens": 1000, "count_default": 4},
    ],
    "hotel_room": [
        {"zone": "bedside",       "fixture_key": "led_pendant_20w", "target_lumens": 400, "count_default": 2},
    ],
    "gym": [
        {"zone": "mirror_wall",   "fixture_key": "led_vanity_bar_15w", "target_lumens": 500, "count_default": 2},
    ],
}

# Spacing-to-mounting-height ratio (S/H) for ambient luminaires — IES guidance.
LIGHTING_LAYOUT_RULES: dict[str, float] = {
    "downlight_S_to_H_ratio_max": 1.2,    # spacing ≤ 1.2 × ceiling height for uniform wash
    "panel_S_to_H_ratio_max":     1.4,
    "uniformity_ratio_min":       0.6,    # E_min / E_avg
    "perimeter_offset_m":         0.6,    # first row 0.5–0.7 m from wall
}


def ambient_fixture_count(area_m2: float, lux_target: float, *, fixture_key: str = "led_downlight_18w") -> dict:
    """Pick how many ambient luminaires to hit a lux target (LLF 0.8, MF 0.7)."""
    spec = FIXTURE_CATALOGUE.get(fixture_key)
    if not spec or area_m2 <= 0 or lux_target <= 0:
        return {"error": "bad inputs", "fixture_key": fixture_key}
    light_loss_factor = 0.8
    maintenance_factor = 0.7
    effective_lumens = spec["lumens"] * light_loss_factor * maintenance_factor
    required_lumens = lux_target * area_m2
    n = max(1, int(-(-required_lumens // effective_lumens)))  # ceil
    return {
        "fixture_key": fixture_key,
        "lumens_per_fixture": spec["lumens"],
        "watts_per_fixture": spec["watts"],
        "count": n,
        "total_watts": n * spec["watts"],
        "total_lumens": n * spec["lumens"],
        "lux_design": round((n * effective_lumens) / area_m2, 0),
    }


def outlet_estimate(room_type: str, perimeter_m: float) -> dict:
    """Estimate the count of general / data / dedicated outlets for a room."""
    rule = OUTLET_COUNT_RULE.get(room_type) or OUTLET_COUNT_RULE.get("office_general")
    n_general = max(int(rule["min_general"]),
                    int(round(perimeter_m * rule["general_per_m_wall"])))
    return {
        "room_type": room_type,
        "perimeter_m": round(perimeter_m, 2),
        "general_outlets": n_general,
        "task_zones": rule["task_zones"],
    }


# ── Plumbing ─────────────────────────────────────────────────────────────────
# Drainage Fixture Units (DFU) per fixture.
DFU_PER_FIXTURE: dict[str, int] = {
    "water_closet": 4,
    "urinal": 2,
    "wash_basin": 1,
    "kitchen_sink": 2,
    "shower": 2,
    "bathtub": 2,
    "floor_drain": 1,
    "washing_machine": 2,
}

# Trap / pipe sizing by DFU total.
PIPE_SIZE_MM_BY_DFU: list[tuple[int, int]] = [
    (3, 50),
    (6, 65),
    (24, 75),
    (84, 100),
    (256, 125),
    (600, 150),
]

SLOPE_PER_METRE: dict[str, float] = {
    "horizontal_drain_min": 0.01,    # 1% = 1:100
    "horizontal_drain_preferred": 0.02,
    "vent_horizontal": 0.01,
}

WATER_DEMAND_LPM: dict[str, tuple[int, int]] = {
    "residential_per_person_per_day": (135, 200),  # litres/day
    "hotel_per_guest_per_day": (180, 300),
    "office_per_person_per_day": (45, 70),
    "restaurant_per_seat_per_day": (65, 100),
}


def pipe_size_for_dfu(total_dfu: int) -> dict:
    for limit, size in PIPE_SIZE_MM_BY_DFU:
        if total_dfu <= limit:
            return {"total_dfu": total_dfu, "pipe_size_mm": size}
    return {"total_dfu": total_dfu, "pipe_size_mm": PIPE_SIZE_MM_BY_DFU[-1][1], "note": "exceeds table; size up"}


# Water Supply Fixture Units (WSFU) — IPC 604.3, mixed cold + hot.
WSFU_PER_FIXTURE: dict[str, dict] = {
    "water_closet":   {"cold": 2.5, "hot": 0.0, "total": 2.5},   # tank type
    "urinal":         {"cold": 5.0, "hot": 0.0, "total": 5.0},   # flushometer
    "wash_basin":     {"cold": 0.5, "hot": 0.5, "total": 1.0},
    "kitchen_sink":   {"cold": 1.0, "hot": 1.0, "total": 1.5},
    "shower":         {"cold": 1.0, "hot": 1.0, "total": 2.0},
    "bathtub":        {"cold": 1.0, "hot": 1.0, "total": 2.0},
    "floor_drain":    {"cold": 0.0, "hot": 0.0, "total": 0.0},
    "washing_machine":{"cold": 1.5, "hot": 1.5, "total": 2.5},
}

# Hunter's curve (IPC table E103.3) — predominantly flush-tank systems. WSFU → GPM.
HUNTERS_CURVE_FLUSH_TANK: list[tuple[float, float]] = [
    (1,    3.0), (2,   5.0), (3,   6.5), (4,   8.0), (5,   9.4),
    (6,   10.7), (8,  13.0), (10, 15.0), (15, 19.0), (20, 23.0),
    (25,  27.0), (30, 30.5), (40, 36.0), (50, 41.0), (75, 53.0),
    (100, 64.0), (150, 84.0), (200, 102.0), (300, 134.0),
]
GPM_TO_LPM: float = 3.78541


def water_supply_demand_gpm(total_wsfu: float) -> dict:
    """WSFU → probable demand GPM via Hunter's curve (flush-tank)."""
    if total_wsfu <= 0:
        return {"total_wsfu": 0, "demand_gpm": 0.0, "demand_lpm": 0.0}
    if total_wsfu <= HUNTERS_CURVE_FLUSH_TANK[0][0]:
        gpm = HUNTERS_CURVE_FLUSH_TANK[0][1]
    else:
        gpm = HUNTERS_CURVE_FLUSH_TANK[-1][1]
        for (lo_w, lo_g), (hi_w, hi_g) in zip(
            HUNTERS_CURVE_FLUSH_TANK, HUNTERS_CURVE_FLUSH_TANK[1:]
        ):
            if total_wsfu <= hi_w:
                gpm = lo_g + (hi_g - lo_g) * (total_wsfu - lo_w) / (hi_w - lo_w)
                break
    return {
        "total_wsfu": round(total_wsfu, 2),
        "demand_gpm": round(gpm, 2),
        "demand_lpm": round(gpm * GPM_TO_LPM, 2),
        "curve": "hunter_flush_tank",
    }


# Supply main / branch sizing by GPM (CPVC/PEX, 8 ft/s ceiling, 5 fps preferred).
SUPPLY_PIPE_SIZE_MM_BY_GPM: list[tuple[float, int]] = [
    (4,   15),   # 1/2"
    (8,   20),   # 3/4"
    (15,  25),   # 1"
    (30,  32),   # 1-1/4"
    (50,  40),   # 1-1/2"
    (90,  50),   # 2"
    (160, 65),   # 2-1/2"
    (260, 80),   # 3"
]


def supply_pipe_size_for_gpm(gpm: float) -> dict:
    for limit, size in SUPPLY_PIPE_SIZE_MM_BY_GPM:
        if gpm <= limit:
            return {"gpm": round(gpm, 2), "pipe_size_mm": size}
    return {
        "gpm": round(gpm, 2),
        "pipe_size_mm": SUPPLY_PIPE_SIZE_MM_BY_GPM[-1][1],
        "note": "exceeds table; size up to 100 mm or split runs",
    }


# P-trap diameters per fixture (IPC table 1002.1, mm).
TRAP_SIZE_MM_PER_FIXTURE: dict[str, dict] = {
    "water_closet":    {"trap_mm": 75,  "trap_type": "integral_water_closet", "seal_mm": 50},
    "urinal":          {"trap_mm": 50,  "trap_type": "P_trap",                "seal_mm": 50},
    "wash_basin":      {"trap_mm": 32,  "trap_type": "P_trap",                "seal_mm": 50},
    "kitchen_sink":    {"trap_mm": 40,  "trap_type": "P_trap",                "seal_mm": 50},
    "shower":          {"trap_mm": 50,  "trap_type": "P_trap",                "seal_mm": 50},
    "bathtub":         {"trap_mm": 40,  "trap_type": "P_trap",                "seal_mm": 50},
    "floor_drain":     {"trap_mm": 50,  "trap_type": "P_trap_with_grate",     "seal_mm": 50},
    "washing_machine": {"trap_mm": 50,  "trap_type": "standpipe_P_trap",      "seal_mm": 50},
}

# S-traps are prohibited under IS 1742 / IPC 1002.3 (siphon risk) — flag, do not specify.
TRAP_NOTES: dict[str, str] = {
    "s_trap_status": "PROHIBITED — IS 1742 / IPC 1002.3 disallow S-traps; specify P-trap with vent.",
    "min_seal_mm": "50 mm (2\") water seal minimum",
    "max_developed_length_m": "1.0 m from fixture outlet to trap weir",
}

# Slope requirement — keep both metric and imperial (1/4" per foot ≈ 2.08 %).
SLOPE_REQUIREMENT: dict[str, dict] = {
    "horizontal_drain_min": {
        "ratio": 0.01,                    # 1 % = 1:100
        "imperial": "1/8 inch per foot",
        "metric_mm_per_m": 10,
    },
    "horizontal_drain_preferred": {
        "ratio": 0.02,                    # 2 % = 1:50
        "imperial": "1/4 inch per foot",
        "metric_mm_per_m": 25,
    },
    "vent_horizontal": {
        "ratio": 0.01,
        "imperial": "1/8 inch per foot back to drain",
        "metric_mm_per_m": 10,
    },
}

# Vent sizing — IPC 906.1 / NBC Part 9 stack vent table.
# (max DFU on stack, max developed length m, vent diameter mm)
VENT_STACK_SIZE_BY_DFU: list[tuple[int, int, int]] = [
    (8,    15,  32),    # 1-1/4"
    (10,   30,  40),    # 1-1/2"
    (24,   60,  50),    # 2"
    (84,   90,  75),    # 3"
    (256, 180, 100),    # 4"
    (600, 300, 125),    # 5"
]

VENT_RULES: dict[str, str] = {
    "stack_vent_min_above_roof_mm": "300 mm above roof; 600 mm if used as a walking surface",
    "individual_vent_max_distance": "trap-to-vent distance ≤ 6 × pipe diameter (≈ 1.5 m for 250 mm trap arm at 50 mm pipe)",
    "circuit_vent_dfu_max": "10 DFU per circuit-vented branch; relief vent required for stacks > 10 storeys",
    "loop_vent_use": "battery of 2–8 fixtures on a single horizontal branch — vent loops back to vent stack",
    "vent_terminal_clearance": "≥ 3 m from any opening; ≥ 600 mm above any operable window within 3 m",
}


def vent_size_for_dfu(total_dfu: int, developed_length_m: float = 0.0) -> dict:
    for cap_dfu, max_len, vent_mm in VENT_STACK_SIZE_BY_DFU:
        if total_dfu <= cap_dfu and developed_length_m <= max_len:
            return {
                "total_dfu": total_dfu,
                "developed_length_m": round(developed_length_m, 1),
                "vent_size_mm": vent_mm,
                "max_length_m_for_size": max_len,
            }
    cap_dfu, max_len, vent_mm = VENT_STACK_SIZE_BY_DFU[-1]
    return {
        "total_dfu": total_dfu,
        "developed_length_m": round(developed_length_m, 1),
        "vent_size_mm": vent_mm,
        "max_length_m_for_size": max_len,
        "note": "exceeds table; step up to 150 mm or shorten developed length",
    }


def fixture_water_supply_summary(fixtures: list[str]) -> dict:
    """Roll up WSFU + GPM demand from a fixture list."""
    cold = hot = total = 0.0
    rows: list[dict] = []
    for f in fixtures:
        spec = WSFU_PER_FIXTURE.get(f)
        if not spec:
            continue
        cold += spec["cold"]
        hot += spec["hot"]
        total += spec["total"]
        rows.append({"fixture": f, **spec})
    demand = water_supply_demand_gpm(total)
    return {
        "fixtures": rows,
        "wsfu_cold": round(cold, 2),
        "wsfu_hot": round(hot, 2),
        "wsfu_total": round(total, 2),
        "demand_gpm": demand["demand_gpm"],
        "demand_lpm": demand["demand_lpm"],
        "supply_main_pipe_size_mm": supply_pipe_size_for_gpm(demand["demand_gpm"])["pipe_size_mm"],
    }


# ── System cost per m² (major MEP systems, indicative INR ranges) ────────────
# Baseline for Tier-1 Indian metros, mid-spec. Used by cost/estimation stage
# and surfaced in the architect brief for early budgeting.
SYSTEM_COST_INR_PER_M2: dict[str, dict] = {
    "hvac_split_residential": {
        "range": (1200, 2200),
        "notes": "Wall-mounted splits + ducting; excludes mains power",
    },
    "hvac_vrf_commercial": {
        "range": (3500, 6500),
        "notes": "VRF outdoor + indoor units, refrigerant piping, controls",
    },
    "hvac_chilled_water_large": {
        "range": (5500, 9000),
        "notes": "Chiller, AHUs, ducting, pumping; viable above ~2000 m²",
    },
    "electrical_residential": {
        "range": (900, 1600),
        "notes": "Wiring, distribution board, fixtures, points — mid-spec",
    },
    "electrical_commercial": {
        "range": (1800, 3200),
        "notes": "Higher power density, UPS rough-in, BMS-ready",
    },
    "plumbing_residential": {
        "range": (700, 1300),
        "notes": "CPVC supply + PVC/UPVC drainage; excludes fixtures",
    },
    "plumbing_commercial": {
        "range": (1400, 2400),
        "notes": "Stacked toilet cores, booster pumping, water treatment",
    },
    "fire_fighting_residential": {
        "range": (400, 800),
        "notes": "Sprinklers + wet-riser for high-rise; excluded for low-rise",
    },
    "fire_fighting_commercial": {
        "range": (900, 1600),
        "notes": "Sprinkler network, hydrants, alarm + detection",
    },
    "low_voltage_commercial": {
        "range": (600, 1400),
        "notes": "Data, access control, CCTV, PA, BMS",
    },
}


def system_cost_estimate(system_key: str, area_m2: float) -> dict:
    """Rough order-of-magnitude system cost for an area.

    Returned ranges are multiplied by the area; callers should apply a
    regional price index (see knowledge.regional_materials) on top.
    """
    spec = SYSTEM_COST_INR_PER_M2.get(system_key)
    if not spec:
        return {"error": f"No cost band for system '{system_key}'"}
    lo, hi = spec["range"]
    return {
        "system": system_key,
        "area_m2": area_m2,
        "rate_inr_m2": {"low": lo, "high": hi},
        "total_inr": {"low": round(lo * area_m2, 0), "high": round(hi * area_m2, 0)},
        "notes": spec["notes"],
    }
