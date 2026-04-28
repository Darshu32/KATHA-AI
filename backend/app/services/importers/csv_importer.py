"""CSV importer — parse + classify columns by header keywords.

Detects which kind of data this CSV likely represents (material
pricing, supplier list, project constraint table, fixture schedule,
budget) by matching column headers against a controlled keyword set.
"""

from __future__ import annotations

import csv
import io
from typing import Any


HEADER_KEYWORDS: dict[str, list[str]] = {
    "material_pricing": ["material", "price", "rate", "cost", "unit"],
    "supplier_list":    ["supplier", "vendor", "contact", "lead time"],
    "project_constraint": ["constraint", "limit", "min", "max"],
    "fixture_schedule": ["fixture", "qty", "quantity", "manufacturer", "model"],
    "budget_parameters": ["budget", "allocation", "category", "cap"],
    "client_specs": ["spec", "requirement", "preference", "client"],
}


def _classify(headers: list[str]) -> list[str]:
    lowered = [h.lower() for h in headers]
    matches: list[str] = []
    for kind, keywords in HEADER_KEYWORDS.items():
        if any(any(k in h for h in lowered) for k in keywords):
            matches.append(kind)
    return matches


def parse(filename: str, payload: bytes) -> dict[str, Any]:
    text = payload.decode("utf-8-sig", errors="ignore")
    warnings: list[str] = []
    if not text.strip():
        return {
            "format": "csv",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": "Empty CSV.",
            "extracted": {},
            "warnings": ["File body is empty."],
        }
    # Sniff delimiter.
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ","
        warnings.append("Could not sniff delimiter; assumed ','.")

    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = [r for r in reader if r]
    if not rows:
        return {
            "format": "csv",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": "CSV has no rows.",
            "extracted": {},
            "warnings": ["File contains no rows."],
        }
    headers = [h.strip() for h in rows[0]]
    body = rows[1:]
    sample_rows = body[:10]
    return {
        "format": "csv",
        "filename": filename,
        "size_bytes": len(payload),
        "summary": (
            f"CSV: {len(body)} data row(s); {len(headers)} column(s); "
            f"delimiter '{delim}'."
        ),
        "extracted": {
            "delimiter": delim,
            "headers": headers,
            "row_count": len(body),
            "kinds_detected": _classify(headers),
            "sample_rows": [dict(zip(headers, row)) for row in sample_rows],
        },
        "warnings": warnings,
    }
