"""Discover locally configured CLI models with a one-hour in-process cache."""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.db.models import AgentBackend

_TTL = timedelta(hours=1)
_DEFAULTS = {
    AgentBackend.claude_code: ["sonnet", "opus", "haiku"],
    AgentBackend.codex: ["gpt-5.6-codex", "gpt-5.4", "gpt-5.3-codex"],
}


@dataclass
class CachedCatalog:
    items: list[dict]
    refreshed_at: datetime
    discovery_error: str | None


_cache: dict[AgentBackend, CachedCatalog] = {}
_lock = asyncio.Lock()


async def get_catalog(backend: AgentBackend, force: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    cached = _cache.get(backend)
    if cached and not force and now - cached.refreshed_at < _TTL:
        return _serialize(backend, cached, cached=True)

    async with _lock:
        cached = _cache.get(backend)
        now = datetime.now(timezone.utc)
        if cached and not force and now - cached.refreshed_at < _TTL:
            return _serialize(backend, cached, cached=True)
        names, error = await asyncio.to_thread(_discover, backend)
        entry = CachedCatalog(
            items=[{"id": name, "label": _label(name), "backend": backend, "source": "local_cli"} for name in names],
            refreshed_at=now,
            discovery_error=error,
        )
        _cache[backend] = entry
        return _serialize(backend, entry, cached=False)


def _discover(backend: AgentBackend) -> tuple[list[str], str | None]:
    env_name = "MUSTER_CLAUDE_MODELS" if backend == AgentBackend.claude_code else "MUSTER_CODEX_MODELS"
    configured = [item.strip() for item in os.getenv(env_name, "").split(",") if item.strip()]
    found = set(configured)
    errors: list[str] = []

    try:
        if backend == AgentBackend.codex:
            cache_path = Path.home() / ".codex" / "models_cache.json"
            if cache_path.exists():
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                models = payload.get("models", []) if isinstance(payload, dict) else []
                for model in models:
                    if not isinstance(model, dict):
                        continue
                    slug = model.get("slug")
                    if isinstance(slug, str) and model.get("visibility", "list") == "list":
                        found.add(slug)
            config_path = Path.home() / ".codex" / "config.toml"
            if config_path.exists():
                match = re.search(r'^model\s*=\s*["\']([^"\']+)', config_path.read_text(encoding="utf-8"), re.MULTILINE)
                if match:
                    found.add(match.group(1))
        else:
            settings_path = Path.home() / ".claude" / "settings.json"
            if settings_path.exists():
                payload = json.loads(settings_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and isinstance(payload.get("model"), str):
                    found.add(payload["model"])
    except (OSError, ValueError, TypeError) as exc:
        errors.append(str(exc))

    found.update(_DEFAULTS[backend])
    return sorted(found), "; ".join(errors) or None


def _label(model_id: str) -> str:
    return model_id.replace("-", " ").replace("_", " ").title()


def _serialize(backend: AgentBackend, entry: CachedCatalog, cached: bool) -> dict:
    return {
        "backend": backend,
        "items": entry.items,
        "refreshed_at": entry.refreshed_at,
        "expires_at": entry.refreshed_at + _TTL,
        "cached": cached,
        "discovery_error": entry.discovery_error,
    }
