from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentBackend, AgentProfile, CapabilityImport, GlobalMcpServer, Skill
from app.db.session import get_db
from app.schemas.capability_import import (
    CapabilityDiscoveryResponse,
    CapabilityImportPreview,
    CapabilityImportRequest,
    CapabilityImportResponse,
    CapabilityImportResultItem,
)
from app.services.capability_imports import DiscoveredCapability, discover_capabilities

router = APIRouter(prefix="/capability-imports", tags=["capability-imports"])

_MODELS = {"agent": AgentProfile, "skill": Skill, "mcp": GlobalMcpServer}
_SOURCE_LABELS = {"claude": "Claude", "codex": "Codex"}


async def _existing_names(db: AsyncSession) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for resource_type, model in _MODELS.items():
        rows = (await db.execute(select(model.name))).scalars().all()
        result[resource_type] = set(rows)
    return result


def _available_name(candidate: DiscoveredCapability, names: set[str]) -> str:
    if candidate.name not in names:
        return candidate.name
    suffix = _SOURCE_LABELS[candidate.source_runtime]
    proposed = f"{candidate.name} ({suffix})"
    counter = 2
    while proposed in names:
        proposed = f"{candidate.name} ({suffix} {counter})"
        counter += 1
    return proposed


async def _record_for(db: AsyncSession, candidate: DiscoveredCapability) -> CapabilityImport | None:
    result = await db.execute(
        select(CapabilityImport).where(
            CapabilityImport.source_runtime == candidate.source_runtime,
            CapabilityImport.resource_type == candidate.resource_type,
            CapabilityImport.source_locator == candidate.source_locator,
        )
    )
    return result.scalar_one_or_none()


async def _preview_items(db: AsyncSession) -> CapabilityDiscoveryResponse:
    discovery = discover_capabilities()
    names = await _existing_names(db)
    previews: list[CapabilityImportPreview] = []
    for candidate in discovery.items:
        record = await _record_for(db, candidate)
        resource = await db.get(_MODELS[candidate.resource_type], record.resource_id) if record else None
        if record and resource:
            target_name = resource.name
            status = "unchanged" if record.source_checksum == candidate.checksum else "updated"
        else:
            target_name = _available_name(candidate, names[candidate.resource_type])
        if not record or not resource:
            status = "new"
        names[candidate.resource_type].add(target_name)
        item_warnings = list(candidate.warnings)
        if target_name != candidate.name:
            item_warnings.append(f'Will import as "{target_name}" because the original name is already in use')
        previews.append(
            CapabilityImportPreview(
                candidate_id=candidate.candidate_id,
                resource_type=candidate.resource_type,
                source_runtime=candidate.source_runtime,
                source_scope=candidate.source_scope,
                source_locator=candidate.source_locator,
                name=candidate.name,
                target_name=target_name,
                description=candidate.description,
                status=status,
                preview=candidate.preview,
                warnings=item_warnings,
            )
        )
    return CapabilityDiscoveryResponse(items=previews, warnings=discovery.warnings)


def _create_resource(candidate: DiscoveredCapability, target_name: str):
    payload = candidate.payload
    if candidate.resource_type == "agent":
        return AgentProfile(
            name=target_name,
            description=payload["description"],
            backend=AgentBackend(payload["backend"]),
            system_prompt=payload["system_prompt"],
            model=payload["model"],
            thinking_level=payload["thinking_level"],
            config=payload["config"],
            enabled=True,
        )
    if candidate.resource_type == "skill":
        return Skill(
            name=target_name,
            description=payload["description"],
            instructions=payload["instructions"],
            enabled=True,
        )
    return GlobalMcpServer(
        name=target_name,
        description=payload["description"],
        config=payload["config"],
        enabled=True,
    )


def _update_resource(resource, candidate: DiscoveredCapability) -> None:
    payload = candidate.payload
    resource.description = payload["description"]
    if candidate.resource_type == "agent":
        resource.backend = AgentBackend(payload["backend"])
        resource.system_prompt = payload["system_prompt"]
        resource.model = payload["model"]
        resource.thinking_level = payload["thinking_level"]
        resource.config = payload["config"]
    elif candidate.resource_type == "skill":
        resource.instructions = payload["instructions"]
    else:
        resource.config = payload["config"]


async def _import_candidates(
    db: AsyncSession,
    candidates: list[DiscoveredCapability],
) -> CapabilityImportResponse:
    names = await _existing_names(db)
    results: list[CapabilityImportResultItem] = []
    now = datetime.now(timezone.utc)
    for candidate in candidates:
        record = await _record_for(db, candidate)
        resource = await db.get(_MODELS[candidate.resource_type], record.resource_id) if record else None
        if record and resource and record.source_checksum == candidate.checksum:
            action = "unchanged"
        elif resource:
            _update_resource(resource, candidate)
            action = "updated"
        else:
            target_name = _available_name(candidate, names[candidate.resource_type])
            resource = _create_resource(candidate, target_name)
            db.add(resource)
            await db.flush()
            names[candidate.resource_type].add(target_name)
            action = "created"

        if record is None:
            record = CapabilityImport(
                resource_type=candidate.resource_type,
                resource_id=resource.id,
                source_runtime=candidate.source_runtime,
                source_scope=candidate.source_scope,
                source_locator=candidate.source_locator,
                source_checksum=candidate.checksum,
                source_metadata=candidate.source_metadata,
                synced_at=now,
            )
            db.add(record)
        else:
            record.resource_id = resource.id
            record.source_checksum = candidate.checksum
            record.source_metadata = candidate.source_metadata
            record.synced_at = now
        await db.flush()
        results.append(
            CapabilityImportResultItem(
                import_id=record.id,
                resource_type=candidate.resource_type,
                resource_id=resource.id,
                name=resource.name,
                action=action,
            )
        )
    await db.commit()
    return CapabilityImportResponse(items=results)


@router.get("/discover", response_model=CapabilityDiscoveryResponse)
async def discover_imports(db: AsyncSession = Depends(get_db)):
    return await _preview_items(db)


@router.post("", response_model=CapabilityImportResponse)
async def import_capabilities(body: CapabilityImportRequest, db: AsyncSession = Depends(get_db)):
    discovery = discover_capabilities()
    by_id = {item.candidate_id: item for item in discovery.items}
    missing = sorted(set(body.candidate_ids) - by_id.keys())
    if missing:
        raise HTTPException(status_code=409, detail="One or more source capabilities changed; refresh discovery")
    ordered = [by_id[candidate_id] for candidate_id in dict.fromkeys(body.candidate_ids)]
    return await _import_candidates(db, ordered)


@router.post("/{import_id}/sync", response_model=CapabilityImportResponse)
async def sync_capability(import_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    record = await db.get(CapabilityImport, import_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Capability import not found")
    discovery = discover_capabilities()
    candidate = next(
        (
            item
            for item in discovery.items
            if item.source_runtime == record.source_runtime
            and item.resource_type == record.resource_type
            and item.source_locator == record.source_locator
        ),
        None,
    )
    if candidate is None:
        raise HTTPException(status_code=409, detail="The source capability no longer exists")
    return await _import_candidates(db, [candidate])
