from typing import Literal

from pydantic import BaseModel, Field


class StyleProfile(BaseModel):
    primary: str
    secondary: list[str] = Field(default_factory=list)


class SiteInfo(BaseModel):
    unit: Literal["metric", "imperial"] = "metric"
    location: str | None = None
    climate_zone: str | None = None


class AssetBundle(BaseModel):
    render_2d: list[str] = Field(default_factory=list)
    scene_3d: list[str] = Field(default_factory=list)
    masks: list[str] = Field(default_factory=list)
    render_prompt_2d: str = ""
    render_prompt_3d: str = ""


class DesignGraph(BaseModel):
    project_id: str
    version: int = 1
    design_type: Literal["interior", "architecture"] = "interior"
    style: StyleProfile
    site: SiteInfo = Field(default_factory=SiteInfo)
    spaces: list[dict] = Field(default_factory=list)
    geometry: list[dict] = Field(default_factory=list)
    objects: list[dict] = Field(default_factory=list)
    materials: list[dict] = Field(default_factory=list)
    lighting: list[dict] = Field(default_factory=list)
    constraints: list[dict] = Field(default_factory=list)
    estimation: dict = Field(default_factory=dict)
    assets: AssetBundle = Field(default_factory=AssetBundle)


def build_starter_graph(project_id: str, prompt: str) -> DesignGraph:
    return DesignGraph(
        project_id=project_id,
        style=StyleProfile(primary="Warm Contemporary", secondary=["starter"]),
        spaces=[
            {
                "id": "space_001",
                "name": "Main Studio Space",
                "prompt": prompt,
            }
        ],
        constraints=[
            {
                "id": "constraint_001",
                "type": "starter_prompt",
                "value": prompt,
            }
        ],
        estimation={
            "status": "pending",
            "assumptions": [
                "Quantities will be computed after geometry is defined."
            ],
        },
    )

