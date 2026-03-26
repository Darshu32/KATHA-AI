"""Route registry — import all routers here."""

from app.routes.auth import router as auth_router
from app.routes.projects import router as projects_router
from app.routes.generation import router as generation_router
from app.routes.estimates import router as estimates_router
from app.routes.prompts import router as prompts_router

all_routers = [
    auth_router,
    projects_router,
    generation_router,
    estimates_router,
    prompts_router,
]
