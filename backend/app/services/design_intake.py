"""Utilities for parsing and validating design intake payloads."""

import re
from typing import Any

DIMENSIONS_PATTERN = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*(ft|feet|m|meter|meters)?\s*$",
    re.IGNORECASE,
)


def parse_dimensions_input(value: Any) -> dict[str, Any]:
    """
    Accept legacy string dimensions or the newer structured object and normalize both
    into the internal JSON shape used by the design intake pipeline.
    """
    if isinstance(value, str):
        match = DIMENSIONS_PATTERN.fullmatch(value.strip())
        if not match:
            raise ValueError("Dimensions must follow the format '10x12 ft'")

        length, width, unit = match.groups()
        return {
            "length": float(length),
            "width": float(width),
            "unit": "ft" if unit is None or unit.lower() in {"ft", "feet"} else "m",
        }

    if isinstance(value, dict):
        normalized = {
            "length": value.get("length"),
            "width": value.get("width"),
            "unit": value.get("unit"),
        }
        if isinstance(normalized["unit"], str):
            normalized["unit"] = normalized["unit"].strip().lower()
        return normalized

    raise ValueError("Dimensions must be provided as '10x12 ft' or a structured object")


def validate_requirements_text(value: str) -> None:
    if not value.strip():
        raise ValueError("Requirements must not be empty")
    if len(value.strip()) < 20:
        raise ValueError("Requirements must be at least 20 characters long")
