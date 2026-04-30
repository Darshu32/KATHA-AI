"""Stage 3B — BuildingStandard ORM model sanity."""

from __future__ import annotations

from app.models.standards import BuildingStandard


def test_building_standards_table_registered():
    from app.database import Base

    assert "building_standards" in {t.name for t in Base.metadata.tables.values()}


def test_building_standard_has_convention_columns():
    cols = {c.name for c in BuildingStandard.__table__.columns}
    for required in (
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        "version",
        "is_current",
        "previous_version_id",
        "effective_from",
        "effective_to",
        "source",
        "source_ref",
        "created_by",
    ):
        assert required in cols, f"missing convention column {required!r}"


def test_building_standard_has_business_columns():
    cols = {c.name for c in BuildingStandard.__table__.columns}
    for required in (
        "slug",
        "category",
        "jurisdiction",
        "subcategory",
        "display_name",
        "notes",
        "data",
        "source_section",
        "source_doc",
    ):
        assert required in cols
