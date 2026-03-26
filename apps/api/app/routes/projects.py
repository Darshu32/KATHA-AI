from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.models.design_graph import DesignGraph, build_starter_graph

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    prompt: str = Field(min_length=10, max_length=3000)


class ProjectCreateResponse(BaseModel):
    id: str
    name: str
    status: str
    design_graph: DesignGraph


@router.post("", response_model=ProjectCreateResponse)
def create_project(payload: ProjectCreateRequest) -> ProjectCreateResponse:
    project_id = "proj_001"
    return ProjectCreateResponse(
        id=project_id,
        name=payload.name,
        status="draft",
        design_graph=build_starter_graph(project_id=project_id, prompt=payload.prompt),
    )


@router.get("/starter-graph", response_model=DesignGraph)
def get_starter_graph() -> DesignGraph:
    return build_starter_graph(
        project_id="proj_starter",
        prompt="Design a warm, material-rich living space with room to evolve.",
    )

