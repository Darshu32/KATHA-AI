from fastapi import APIRouter
from pydantic import BaseModel

from app.prompts.design_graph import DESIGN_GRAPH_SYSTEM_PROMPT

router = APIRouter(prefix="/prompts", tags=["prompts"])


class PromptTemplateResponse(BaseModel):
    key: str
    content: str


@router.get("/design-graph", response_model=PromptTemplateResponse)
def get_design_graph_prompt() -> PromptTemplateResponse:
    return PromptTemplateResponse(
        key="design_graph_system_prompt",
        content=DESIGN_GRAPH_SYSTEM_PROMPT,
    )
