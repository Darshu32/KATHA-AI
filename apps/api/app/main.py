from fastapi import FastAPI

from app.routes.projects import router as projects_router

app = FastAPI(
    title="KATHA AI API",
    version="0.1.0",
    description="Backend foundation for the KATHA AI architecture platform.",
)

app.include_router(projects_router)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}

