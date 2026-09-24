"""Project tag catalog and backend-owned workflow labels."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ProjectTaskTag, Task


PRESET_TAGS: tuple[tuple[str, str, str | None], ...] = (
    ("PR Raised", "system", "violet"),
    ("PR Reviewed", "system", "emerald"),
    ("Canvas", "system", "sky"),
    ("Bug", "preset", "rose"),
    ("Feature", "preset", "blue"),
    ("Research", "preset", "amber"),
    ("Release", "preset", "green"),
)
SYSTEM_TAG_NAMES = frozenset(name.casefold() for name, kind, _ in PRESET_TAGS if kind == "system")


def clean_name(value: str) -> str:
    return " ".join(value.strip().split())


async def ensure_catalog(db: AsyncSession, project_id: uuid.UUID) -> list[ProjectTaskTag]:
    """Persist presets and legacy task tags for an existing project."""
    # Serialize the first materialization for this project across workers;
    # otherwise two simultaneous first reads can race the unique constraint.
    await db.execute(select(Project.id).where(Project.id == project_id).with_for_update())
    existing = list(
        (
            await db.execute(
                select(ProjectTaskTag).where(ProjectTaskTag.project_id == project_id)
            )
        ).scalars()
    )
    by_name = {tag.normalized_name: tag for tag in existing}
    changed = False

    for name, kind, color in PRESET_TAGS:
        normalized = name.casefold()
        if normalized not in by_name:
            tag = ProjectTaskTag(
                project_id=project_id,
                name=name,
                normalized_name=normalized,
                kind=kind,
                color=color,
            )
            db.add(tag)
            by_name[normalized] = tag
            changed = True

    tasks = (
        await db.execute(select(Task.tags).where(Task.project_id == project_id))
    ).scalars()
    for task_tags in tasks:
        for raw_name in task_tags or []:
            name = clean_name(str(raw_name))
            normalized = name.casefold()
            if not name or normalized in by_name:
                continue
            tag = ProjectTaskTag(
                project_id=project_id,
                name=name[:32],
                normalized_name=normalized[:32],
                kind="custom",
            )
            db.add(tag)
            by_name[tag.normalized_name] = tag
            changed = True

    if changed:
        await db.flush()
    return sorted(by_name.values(), key=lambda tag: (tag.kind == "custom", tag.name.casefold()))


async def ensure_assignable_tags(
    db: AsyncSession, project_id: uuid.UUID, names: list[str]
) -> None:
    """Persist custom assignments; system labels can only be added by backend events."""
    catalog = await ensure_catalog(db, project_id)
    known = {tag.normalized_name: tag for tag in catalog}
    for name in names:
        normalized = name.casefold()
        tag = known.get(normalized)
        if normalized in SYSTEM_TAG_NAMES or (tag is not None and tag.kind == "system"):
            raise ValueError(f"'{name}' is managed by Muster and cannot be assigned manually")
        if tag is None:
            db.add(
                ProjectTaskTag(
                    project_id=project_id,
                    name=name,
                    normalized_name=normalized,
                    kind="custom",
                )
            )


async def add_system_tag(db: AsyncSession, task: Task, name: str) -> bool:
    """Attach a workflow label after its structured source of truth succeeds."""
    if name.casefold() not in SYSTEM_TAG_NAMES:
        raise ValueError(f"Unknown system tag: {name}")
    await ensure_catalog(db, task.project_id)
    tags = list(task.tags or [])
    if name.casefold() in {tag.casefold() for tag in tags}:
        return False
    tags.append(name)
    task.tags = tags
    return True
