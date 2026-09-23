from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AgentBackend,
    AgentProfile,
    CapabilityImport,
    DirectoryResource,
    GlobalMcpServer,
    Project,
    ProjectCapabilityOverride,
    Skill,
)
from app.db.session import get_db
from app.schemas.registry import (
    AgentProfileCreate,
    AgentProfileRead,
    AgentProfileUpdate,
    CapabilityOverridePut,
    CapabilityRead,
    DirectoryResourceCreate,
    DirectoryResourceRead,
    DirectoryResourceUpdate,
    GlobalMcpCreate,
    GlobalMcpRead,
    GlobalMcpUpdate,
    ModelCatalog,
    SkillCreate,
    SkillRead,
    SkillUpdate,
)
from app.services.model_catalog import get_catalog

router = APIRouter(tags=["global-registry"])


async def _commit(db: AsyncSession, resource, conflict: str):
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=conflict) from exc
    await db.refresh(resource)
    return resource


async def _get_or_404(db: AsyncSession, model, resource_id: uuid.UUID, label: str):
    resource = await db.get(model, resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return resource


async def _delete_capability_metadata(
    db: AsyncSession, resource_type: str, resource_id: uuid.UUID
) -> None:
    await db.execute(
        delete(CapabilityImport).where(
            CapabilityImport.resource_type == resource_type,
            CapabilityImport.resource_id == resource_id,
        )
    )
    await db.execute(
        delete(ProjectCapabilityOverride).where(
            ProjectCapabilityOverride.resource_type == resource_type,
            ProjectCapabilityOverride.resource_id == resource_id,
        )
    )


@router.get("/directories")
async def list_global_directories(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(DirectoryResource).order_by(DirectoryResource.name))).scalars().all()
    return {"items": [DirectoryResourceRead.model_validate(row) for row in rows]}


@router.post("/directories", status_code=201, response_model=DirectoryResourceRead)
async def create_global_directory(body: DirectoryResourceCreate, db: AsyncSession = Depends(get_db)):
    resource = DirectoryResource(**body.model_dump())
    db.add(resource)
    return await _commit(db, resource, "A directory with this path already exists")


@router.patch("/directories/{resource_id}", response_model=DirectoryResourceRead)
async def update_global_directory(resource_id: uuid.UUID, body: DirectoryResourceUpdate, db: AsyncSession = Depends(get_db)):
    resource = await _get_or_404(db, DirectoryResource, resource_id, "Directory")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(resource, key, value)
    return await _commit(db, resource, "A directory with this path already exists")


@router.delete("/directories/{resource_id}", status_code=204)
async def delete_global_directory(resource_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    resource = await _get_or_404(db, DirectoryResource, resource_id, "Directory")
    await db.delete(resource)
    await db.commit()


@router.get("/mcp-servers")
async def list_global_mcp(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(GlobalMcpServer).order_by(GlobalMcpServer.name))).scalars().all()
    return {"items": [GlobalMcpRead.model_validate(row) for row in rows]}


@router.post("/mcp-servers", status_code=201, response_model=GlobalMcpRead)
async def create_global_mcp(body: GlobalMcpCreate, db: AsyncSession = Depends(get_db)):
    data = body.model_dump()
    data["config"] = body.config.model_dump()
    resource = GlobalMcpServer(**data)
    db.add(resource)
    return await _commit(db, resource, "An MCP server with this name already exists")


@router.patch("/mcp-servers/{resource_id}", response_model=GlobalMcpRead)
async def update_global_mcp(resource_id: uuid.UUID, body: GlobalMcpUpdate, db: AsyncSession = Depends(get_db)):
    resource = await _get_or_404(db, GlobalMcpServer, resource_id, "MCP server")
    data = body.model_dump(exclude_unset=True)
    if body.config is not None:
        data["config"] = body.config.model_dump()
    for key, value in data.items():
        setattr(resource, key, value)
    return await _commit(db, resource, "An MCP server with this name already exists")


@router.delete("/mcp-servers/{resource_id}", status_code=204)
async def delete_global_mcp(resource_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    resource = await _get_or_404(db, GlobalMcpServer, resource_id, "MCP server")
    await _delete_capability_metadata(db, "mcp", resource_id)
    await db.delete(resource)
    await db.commit()


@router.get("/agents")
async def list_agents(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AgentProfile).order_by(AgentProfile.name))).scalars().all()
    return {"items": [AgentProfileRead.model_validate(row) for row in rows]}


@router.post("/agents", status_code=201, response_model=AgentProfileRead)
async def create_agent(body: AgentProfileCreate, db: AsyncSession = Depends(get_db)):
    resource = AgentProfile(**body.model_dump())
    db.add(resource)
    return await _commit(db, resource, "An agent with this name already exists")


@router.patch("/agents/{resource_id}", response_model=AgentProfileRead)
async def update_agent(resource_id: uuid.UUID, body: AgentProfileUpdate, db: AsyncSession = Depends(get_db)):
    resource = await _get_or_404(db, AgentProfile, resource_id, "Agent")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(resource, key, value)
    return await _commit(db, resource, "An agent with this name already exists")


@router.delete("/agents/{resource_id}", status_code=204)
async def delete_agent(resource_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    resource = await _get_or_404(db, AgentProfile, resource_id, "Agent")
    await _delete_capability_metadata(db, "agent", resource_id)
    await db.delete(resource)
    await db.commit()


@router.get("/skills")
async def list_skills(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Skill).order_by(Skill.name))).scalars().all()
    return {"items": [SkillRead.model_validate(row) for row in rows]}


@router.post("/skills", status_code=201, response_model=SkillRead)
async def create_skill(body: SkillCreate, db: AsyncSession = Depends(get_db)):
    resource = Skill(**body.model_dump())
    db.add(resource)
    return await _commit(db, resource, "A skill with this name already exists")


@router.patch("/skills/{resource_id}", response_model=SkillRead)
async def update_skill(resource_id: uuid.UUID, body: SkillUpdate, db: AsyncSession = Depends(get_db)):
    resource = await _get_or_404(db, Skill, resource_id, "Skill")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(resource, key, value)
    return await _commit(db, resource, "A skill with this name already exists")


@router.delete("/skills/{resource_id}", status_code=204)
async def delete_skill(resource_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    resource = await _get_or_404(db, Skill, resource_id, "Skill")
    await _delete_capability_metadata(db, "skill", resource_id)
    await db.delete(resource)
    await db.commit()


_CAPABILITY_MODELS = {
    "mcp": GlobalMcpServer,
    "agent": AgentProfile,
    "skill": Skill,
}


@router.get("/projects/{project_id}/capabilities/{resource_type}")
async def list_project_capabilities(project_id: uuid.UUID, resource_type: str, db: AsyncSession = Depends(get_db)):
    if await db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    model = _CAPABILITY_MODELS.get(resource_type)
    if model is None:
        raise HTTPException(status_code=422, detail="Unknown capability type")
    resources = (await db.execute(select(model).order_by(model.name))).scalars().all()
    overrides = (await db.execute(select(ProjectCapabilityOverride).where(ProjectCapabilityOverride.project_id == project_id, ProjectCapabilityOverride.resource_type == resource_type))).scalars().all()
    by_id = {row.resource_id: row for row in overrides}
    items = []
    for resource in resources:
        override = by_id.get(resource.id)
        global_enabled = resource.enabled
        config = dict(getattr(resource, "config", {}) or {})
        if override:
            config.update(override.config_override or {})
        items.append(CapabilityRead(resource_type=resource_type, resource_id=resource.id, name=resource.name, description=resource.description, enabled=override.enabled if override else global_enabled, global_enabled=global_enabled, config=config))
    return {"items": items}


@router.put("/projects/{project_id}/capabilities/{resource_type}/{resource_id}", response_model=CapabilityRead)
async def put_project_capability(project_id: uuid.UUID, resource_type: str, resource_id: uuid.UUID, body: CapabilityOverridePut, db: AsyncSession = Depends(get_db)):
    model = _CAPABILITY_MODELS.get(resource_type)
    if model is None:
        raise HTTPException(status_code=422, detail="Unknown capability type")
    if await db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    resource = await _get_or_404(db, model, resource_id, "Capability")
    result = await db.execute(select(ProjectCapabilityOverride).where(ProjectCapabilityOverride.project_id == project_id, ProjectCapabilityOverride.resource_type == resource_type, ProjectCapabilityOverride.resource_id == resource_id))
    override = result.scalar_one_or_none()
    if override is None:
        override = ProjectCapabilityOverride(project_id=project_id, resource_type=resource_type, resource_id=resource_id)
        db.add(override)
    override.enabled = body.enabled
    override.config_override = body.config_override
    await db.commit()
    config = dict(getattr(resource, "config", {}) or {})
    config.update(body.config_override)
    return CapabilityRead(resource_type=resource_type, resource_id=resource.id, name=resource.name, description=resource.description, enabled=body.enabled, global_enabled=resource.enabled, config=config)


@router.get("/models/{backend}", response_model=ModelCatalog)
async def list_models(backend: AgentBackend, refresh: bool = Query(False)):
    return await get_catalog(backend, force=refresh)
