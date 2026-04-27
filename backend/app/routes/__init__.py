"""Route registry — import all routers here."""

from app.routes.architecture import router as architecture_router
from app.routes.auth import router as auth_router
from app.routes.brief import router as brief_router
from app.routes.chat import router as chat_router
from app.routes.design import router as design_router
from app.routes.diagrams import router as diagrams_router
from app.routes.drawings import router as drawings_router
from app.routes.estimates import router as estimates_router
from app.routes.generation import router as generation_router
from app.routes.parametric import router as parametric_router
from app.routes.prompts import router as prompts_router
from app.routes.projects import router as projects_router
from app.routes.specs import router as specs_router
from app.routes.working_drawings import router as working_drawings_router

all_routers = [
    architecture_router,
    auth_router,
    brief_router,
    chat_router,
    design_router,
    diagrams_router,
    drawings_router,
    projects_router,
    generation_router,
    estimates_router,
    parametric_router,
    prompts_router,
    specs_router,
    working_drawings_router,
]
