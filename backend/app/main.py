from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.routes import (
    artifacts,
    capability_imports,
    cron,
    directories,
    mcp_servers,
    projects,
    registry,
    secrets as secrets_routes,
    tasks,
    tools,
    ws,
)
from app.services.cron_scheduler import scheduler, sync_jobs_from_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    scheduler.start()
    sync_jobs_from_db()
    yield
    scheduler.shutdown()


app = FastAPI(title="Muster", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api")
app.include_router(registry.router, prefix="/api")
app.include_router(capability_imports.router, prefix="/api")
app.include_router(directories.router, prefix="/api")
app.include_router(mcp_servers.router, prefix="/api")
app.include_router(tools.router, prefix="/api")
app.include_router(tools.task_router, prefix="/api")
app.include_router(artifacts.router, prefix="/api")
app.include_router(secrets_routes.router, prefix="/api")
app.include_router(cron.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(ws.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
