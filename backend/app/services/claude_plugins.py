"""Find literal native plugin MCP namespaces for unattended allow rules."""
from __future__ import annotations

import json
from pathlib import Path

from app.services.capability_imports import _claude_plugin_roots


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def mcp_names(project_directory: str | None, home: Path | None = None) -> tuple[str, ...]:
    home = home or Path.home()
    enabled: dict = {}
    paths = [home / ".claude" / "settings.json"]
    if project_directory:
        paths += [Path(project_directory) / ".claude" / name
                  for name in ("settings.json", "settings.local.json")]
    for path in paths:
        value = _json(path).get("enabledPlugins")
        if isinstance(value, dict):
            enabled.update(value)
    roots, _ = _claude_plugin_roots(home, enabled)
    names: set[str] = set()
    for plugin in roots:
        manifest = _json(plugin.root / ".claude-plugin" / "plugin.json")
        if enabled.get(plugin.plugin_id, manifest.get("defaultEnabled", True)) is False:
            continue
        plugin_name = manifest.get("name") or plugin.plugin_id.split("@", 1)[0]
        configs = [_json(plugin.root / ".mcp.json")]
        extra = manifest.get("mcpServers")
        for entry in extra if isinstance(extra, list) else [extra]:
            if isinstance(entry, dict):
                configs.append(entry)
            elif isinstance(entry, str):
                path = (plugin.root / entry).resolve()
                if path.is_relative_to(plugin.root.resolve()) and path.suffix == ".json":
                    configs.append(_json(path))
        for config in configs:
            servers = config.get("mcpServers", config)
            if isinstance(servers, dict):
                for server, definition in servers.items():
                    if isinstance(definition, dict) and not definition.get("disabled") and definition.get("enabled", True):
                        names.add(f"plugin_{plugin_name}_{server}")
    return tuple(sorted(names))
