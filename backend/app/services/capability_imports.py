"""Read-only discovery of user capabilities from Claude Code and Codex."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import tomllib
from typing import Any, Literal

import yaml


CapabilityKind = Literal["agent", "skill", "mcp"]
SourceRuntime = Literal["claude", "codex"]
_MAX_TEXT_BYTES = 1_000_000
_MAX_CONFIG_BYTES = 20_000_000


@dataclass(frozen=True, slots=True)
class DiscoveredCapability:
    resource_type: CapabilityKind
    source_runtime: SourceRuntime
    source_scope: str
    source_locator: str
    name: str
    description: str | None
    payload: dict[str, Any]
    preview: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    source_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def candidate_id(self) -> str:
        identity = (
            f"{self.source_runtime}:{self.resource_type}:{self.source_locator}:{self.checksum}"
        )
        return hashlib.sha256(identity.encode()).hexdigest()

    @property
    def checksum(self) -> str:
        serialized = json.dumps(self.payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    items: list[DiscoveredCapability]
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class PluginRoot:
    runtime: SourceRuntime
    plugin_id: str
    root: Path
    version: str | None = None


def _display_path(path: Path, home: Path) -> str:
    try:
        return f"~/{path.resolve().relative_to(home.resolve()).as_posix()}"
    except ValueError:
        return str(path.resolve())


def _read_text(path: Path, limit: int = _MAX_TEXT_BYTES) -> str:
    if path.stat().st_size > limit:
        raise ValueError(f"file exceeds the {limit // 1_000_000 or 1} MB import limit")
    return path.read_text(encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(_read_text(path, _MAX_CONFIG_BYTES))
    if not isinstance(value, dict):
        raise ValueError("top-level JSON value must be an object")
    return value


def _read_toml(path: Path) -> dict[str, Any]:
    value = tomllib.loads(_read_text(path, _MAX_CONFIG_BYTES))
    if not isinstance(value, dict):
        raise ValueError("top-level TOML value must be a table")
    return value


def _markdown_document(path: Path) -> tuple[dict[str, Any], str]:
    text = _read_text(path)
    if not text.startswith("---"):
        return {}, text.strip()
    lines = text.splitlines()
    try:
        closing = lines.index("---", 1)
    except ValueError:
        return {}, text.strip()
    metadata = yaml.safe_load("\n".join(lines[1:closing])) or {}
    if not isinstance(metadata, dict):
        raise ValueError("YAML front matter must be an object")
    return metadata, "\n".join(lines[closing + 1 :]).strip()


def _string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items() if item is not None}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _agent_tool_list(value: Any) -> list[str]:
    """Normalize Claude agent frontmatter's list or comma-separated tool syntax."""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _normalize_mcp(raw: Any) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(raw, dict):
        return None, ["MCP configuration is not an object"]
    warnings: list[str] = []
    command = raw.get("command")
    url = raw.get("url")
    raw_type = str(raw.get("type") or "").lower()
    if command:
        config: dict[str, Any] = {
            "transport": "stdio",
            "command": str(command),
            "args": _string_list(raw.get("args")),
            "env": _string_map(raw.get("env")),
            "headers": {},
        }
    elif url:
        transport = "sse" if raw_type == "sse" else "http"
        config = {
            "transport": transport,
            "url": str(url),
            "args": [],
            "env": {},
            "headers": _string_map(raw.get("headers") or raw.get("http_headers")),
        }
        if raw.get("bearer_token_env_var"):
            config["bearer_token_env_var"] = str(raw["bearer_token_env_var"])
        env_headers = raw.get("env_http_headers")
        if isinstance(env_headers, dict):
            for header, env_name in env_headers.items():
                config["headers"][str(header)] = f"${{{env_name}}}"
    else:
        return None, ["MCP configuration has neither a command nor a URL"]
    if raw.get("disabled") is True or raw.get("enabled") is False:
        warnings.append("The source MCP is disabled; Muster will import it enabled")
    if raw.get("oauth") is not None:
        warnings.append(
            "OAuth authorization state is managed by Claude and is not copied into Muster"
        )
    return config, warnings


def _mcp_preview(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "transport": config["transport"],
        "command": config.get("command"),
        "url": config.get("url"),
        "argument_count": len(config.get("args") or []),
        "environment_keys": sorted((config.get("env") or {}).keys()),
        "header_keys": sorted((config.get("headers") or {}).keys()),
        "uses_bearer_token_env": bool(config.get("bearer_token_env_var")),
    }


def _skill_candidates(
    home: Path,
    runtime: SourceRuntime,
    root: Path,
    *,
    source_scope: str = "user",
    origin_metadata: dict[str, Any] | None = None,
) -> tuple[list[DiscoveredCapability], list[str]]:
    items: list[DiscoveredCapability] = []
    warnings: list[str] = []
    if not root.is_dir():
        return items, warnings
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        manifests = [path for path in directory.iterdir() if path.is_file() and path.name.lower() == "skill.md"]
        if not manifests:
            continue
        manifest = manifests[0]
        locator = _display_path(manifest, home)
        try:
            metadata, instructions = _markdown_document(manifest)
            if not instructions:
                raise ValueError("SKILL.md has no instruction body")
            name = str(metadata.get("name") or directory.name).strip()
            description = str(metadata.get("description") or "").strip() or None
            support_files = [path for path in directory.rglob("*") if path.is_file() and path != manifest]
            item_warnings = []
            if support_files:
                item_warnings.append(
                    f"{len(support_files)} supporting file(s) are referenced by path and are not copied into the instruction snapshot"
                )
            preview = {
                "instruction_characters": len(instructions),
                "supporting_files": len(support_files),
            }
            if origin_metadata and origin_metadata.get("plugin"):
                preview["plugin"] = origin_metadata["plugin"]
            items.append(
                DiscoveredCapability(
                    resource_type="skill",
                    source_runtime=runtime,
                    source_scope=source_scope,
                    source_locator=locator,
                    name=name,
                    description=description,
                    payload={"name": name, "description": description, "instructions": instructions, "enabled": True},
                    preview=preview,
                    warnings=item_warnings,
                    source_metadata={
                        "manifest": locator,
                        "supporting_files": len(support_files),
                        **(origin_metadata or {}),
                    },
                )
            )
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
            warnings.append(f"Could not read {locator}: {exc}")
    return items, warnings


def _markdown_agents(
    home: Path,
    runtime: SourceRuntime,
    root: Path,
    *,
    source_scope: str = "user",
    origin_metadata: dict[str, Any] | None = None,
) -> tuple[list[DiscoveredCapability], list[str]]:
    items: list[DiscoveredCapability] = []
    warnings: list[str] = []
    if not root.is_dir():
        return items, warnings
    for path in sorted(root.glob("*.md")):
        locator = _display_path(path, home)
        try:
            metadata, prompt = _markdown_document(path)
            if not prompt:
                raise ValueError("agent file has no prompt body")
            name = str(metadata.get("name") or path.stem).strip()
            description = str(metadata.get("description") or "").strip() or None
            model = metadata.get("model")
            if model in {None, "inherit"}:
                model = None
            thinking = str(metadata.get("effort") or "medium").lower()
            if thinking not in {"low", "medium", "high", "xhigh", "max"}:
                thinking = "medium"
            portable_config = {
                key: (
                    _agent_tool_list(metadata[key])
                    if key in {"tools", "disallowedTools"}
                    else metadata[key]
                )
                for key in ("tools", "disallowedTools", "permissionMode", "maxTurns")
                if key in metadata
            }
            items.append(
                DiscoveredCapability(
                    resource_type="agent",
                    source_runtime=runtime,
                    source_scope=source_scope,
                    source_locator=locator,
                    name=name,
                    description=description,
                    payload={
                        "name": name,
                        "description": description,
                        "backend": "claude_code" if runtime == "claude" else "codex",
                        "system_prompt": prompt,
                        "model": str(model) if model else None,
                        "thinking_level": thinking,
                        "config": portable_config,
                        "enabled": True,
                    },
                    preview={
                        "backend": "claude_code" if runtime == "claude" else "codex",
                        "model": model,
                        "thinking_level": thinking,
                        "configured_tools": metadata.get("tools") or [],
                    },
                    source_metadata={"file": locator, **(origin_metadata or {})},
                )
            )
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
            warnings.append(f"Could not read {locator}: {exc}")
    return items, warnings


def _codex_agents(home: Path, config: dict[str, Any], config_path: Path) -> tuple[list[DiscoveredCapability], list[str]]:
    items: list[DiscoveredCapability] = []
    warnings: list[str] = []
    agents = config.get("agents")
    if not isinstance(agents, dict):
        return items, warnings
    for name, definition in sorted(agents.items()):
        if not isinstance(definition, dict):
            continue
        locator = f"{_display_path(config_path, home)}#agents.{name}"
        try:
            description = str(definition.get("description") or "").strip() or None
            role_config: dict[str, Any] = {}
            config_file = definition.get("config_file")
            role_path: Path | None = None
            if config_file:
                raw_role_path = str(config_file)
                role_path = (
                    home / raw_role_path.removeprefix("~/")
                    if raw_role_path.startswith("~/")
                    else Path(raw_role_path)
                )
                if not role_path.is_absolute():
                    role_path = config_path.parent / role_path
                role_config = _read_toml(role_path)
            prompt = str(
                role_config.get("developer_instructions")
                or role_config.get("instructions")
                or role_config.get("system_prompt")
                or description
                or f"Act as the {name} specialist."
            ).strip()
            thinking = str(role_config.get("model_reasoning_effort") or "medium").lower()
            if thinking not in {"low", "medium", "high", "xhigh", "max"}:
                thinking = "medium"
            model = role_config.get("model")
            ignored = {"developer_instructions", "instructions", "system_prompt", "model", "model_reasoning_effort"}
            portable_config = {key: value for key, value in role_config.items() if key not in ignored}
            items.append(
                DiscoveredCapability(
                    resource_type="agent",
                    source_runtime="codex",
                    source_scope="user",
                    source_locator=locator,
                    name=str(name),
                    description=description,
                    payload={
                        "name": str(name),
                        "description": description,
                        "backend": "codex",
                        "system_prompt": prompt,
                        "model": str(model) if model else None,
                        "thinking_level": thinking,
                        "config": portable_config,
                        "enabled": True,
                    },
                    preview={"backend": "codex", "model": model, "thinking_level": thinking},
                    source_metadata={
                        "config": _display_path(config_path, home),
                        "config_file": _display_path(role_path, home) if role_path else None,
                    },
                )
            )
        except (OSError, UnicodeError, ValueError, tomllib.TOMLDecodeError) as exc:
            warnings.append(f"Could not read {locator}: {exc}")
    return items, warnings


def _mcp_candidates(
    home: Path,
    runtime: SourceRuntime,
    configs: list[tuple[Path, dict[str, Any]]],
    *,
    source_scope: str = "user",
    origin_metadata: dict[str, Any] | None = None,
) -> tuple[list[DiscoveredCapability], list[str]]:
    selected: dict[str, tuple[Path, Any]] = {}
    for path, config in configs:
        servers = config.get("mcpServers") if runtime == "claude" else config.get("mcp_servers")
        if isinstance(servers, dict):
            for name, raw in servers.items():
                selected[str(name)] = (path, raw)
    items: list[DiscoveredCapability] = []
    warnings: list[str] = []
    for name, (path, raw) in sorted(selected.items()):
        locator = f"{_display_path(path, home)}#{'mcpServers' if runtime == 'claude' else 'mcp_servers'}.{name}"
        config, item_warnings = _normalize_mcp(raw)
        if config is None:
            warnings.append(f"Could not import {locator}: {'; '.join(item_warnings)}")
            continue
        items.append(
            DiscoveredCapability(
                resource_type="mcp",
                source_runtime=runtime,
                source_scope=source_scope,
                source_locator=locator,
                name=name,
                description=(
                    f"Imported from {runtime.title()} plugin {origin_metadata['plugin']}"
                    if origin_metadata and origin_metadata.get("plugin")
                    else f"Imported from {runtime.title()} user configuration"
                ),
                payload={"name": name, "description": f"Imported from {runtime.title()}", "config": config, "enabled": True},
                preview=_mcp_preview(config),
                warnings=item_warnings,
                source_metadata={
                    "config": _display_path(path, home),
                    **(origin_metadata or {}),
                },
            )
        )
    return items, warnings


def _claude_plugin_roots(
    home: Path, enabled_plugins: dict[str, Any] | None = None
) -> tuple[list[PluginRoot], list[str]]:
    registry_path = home / ".claude" / "plugins" / "installed_plugins.json"
    if not registry_path.is_file():
        return [], []
    try:
        registry = _read_json(registry_path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return [], [f"Could not read {_display_path(registry_path, home)}: {exc}"]

    plugins = registry.get("plugins")
    if not isinstance(plugins, dict):
        return [], [f"Could not read {_display_path(registry_path, home)}: plugins must be an object"]

    roots: list[PluginRoot] = []
    seen: set[Path] = set()
    warnings: list[str] = []
    for plugin_id, installs in sorted(plugins.items()):
        if enabled_plugins and enabled_plugins.get(str(plugin_id)) is False:
            continue
        if not isinstance(installs, list):
            continue
        user_installs = [
            install
            for install in installs
            if isinstance(install, dict) and install.get("scope", "user") == "user"
        ]
        user_installs.sort(
            key=lambda install: str(
                install.get("lastUpdated") or install.get("installedAt") or ""
            ),
            reverse=True,
        )
        for install in user_installs[:1]:
            raw_path = install.get("installPath")
            if not raw_path:
                continue
            root = Path(str(raw_path))
            if not root.is_absolute():
                root = registry_path.parent / root
            try:
                resolved = root.resolve()
            except OSError as exc:
                warnings.append(f"Could not resolve Claude plugin {plugin_id}: {exc}")
                continue
            if resolved in seen:
                continue
            if not resolved.is_dir():
                warnings.append(
                    f"Claude plugin {plugin_id} is registered but {_display_path(root, home)} is unavailable"
                )
                continue
            seen.add(resolved)
            roots.append(
                PluginRoot(
                    runtime="claude",
                    plugin_id=str(plugin_id),
                    root=resolved,
                    version=str(install["version"]) if install.get("version") else None,
                )
            )
    return roots, warnings


def _codex_plugin_roots(
    home: Path, config: dict[str, Any]
) -> tuple[list[PluginRoot], list[str]]:
    configured = config.get("plugins")
    if not isinstance(configured, dict):
        return [], []

    plugins_dir = home / ".codex" / "plugins"
    cache_dir = plugins_dir / "cache"
    roots: list[PluginRoot] = []
    warnings: list[str] = []
    seen: set[Path] = set()
    for plugin_id, options in sorted(configured.items()):
        enabled = options.get("enabled", True) if isinstance(options, dict) else options is not False
        if not enabled:
            continue
        plugin_name = str(plugin_id).split("@", 1)[0]
        if not plugin_name or Path(plugin_name).name != plugin_name:
            warnings.append(f"Codex plugin identifier is invalid: {plugin_id}")
            continue

        direct_root = plugins_dir / plugin_name
        candidates = [direct_root] if direct_root.is_dir() else []
        if not candidates and cache_dir.is_dir():
            candidates = [
                path
                for path in cache_dir.glob(f"*/{plugin_name}/*")
                if path.is_dir()
            ]
            candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        if not candidates:
            warnings.append(f"Codex plugin {plugin_id} is enabled but its installed package is unavailable")
            continue

        resolved = candidates[0].resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        roots.append(
            PluginRoot(
                runtime="codex",
                plugin_id=str(plugin_id),
                root=resolved,
                version=resolved.name if resolved.parent.name == plugin_name else None,
            )
        )
    return roots, warnings


def _plugin_capabilities(
    home: Path, roots: list[PluginRoot]
) -> tuple[list[DiscoveredCapability], list[str]]:
    items: list[DiscoveredCapability] = []
    warnings: list[str] = []
    for plugin in roots:
        origin_metadata = {
            "plugin": plugin.plugin_id,
            "plugin_version": plugin.version,
            "plugin_root": _display_path(plugin.root, home),
        }
        discovered, errors = _skill_candidates(
            home,
            plugin.runtime,
            plugin.root / "skills",
            source_scope="plugin",
            origin_metadata=origin_metadata,
        )
        items.extend(discovered)
        warnings.extend(errors)
        discovered, errors = _markdown_agents(
            home,
            plugin.runtime,
            plugin.root / "agents",
            source_scope="plugin",
            origin_metadata=origin_metadata,
        )
        items.extend(discovered)
        warnings.extend(errors)
        mcp_path = plugin.root / ".mcp.json"
        if plugin.runtime == "claude" and mcp_path.is_file():
            try:
                mcp_config = _read_json(mcp_path)
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
                warnings.append(
                    f"Could not read {_display_path(mcp_path, home)}: {exc}"
                )
            else:
                discovered, errors = _mcp_candidates(
                    home,
                    "claude",
                    [(mcp_path, mcp_config)],
                    source_scope="plugin",
                    origin_metadata=origin_metadata,
                )
                items.extend(discovered)
                warnings.extend(errors)
    return items, warnings


def discover_capabilities(home: Path | None = None) -> DiscoveryResult:
    home = (home or Path.home()).resolve()
    items: list[DiscoveredCapability] = []
    warnings: list[str] = []

    for runtime, root in (
        ("claude", home / ".claude" / "skills"),
        ("codex", home / ".codex" / "skills"),
    ):
        discovered, errors = _skill_candidates(home, runtime, root)
        items.extend(discovered)
        warnings.extend(errors)

    discovered, errors = _markdown_agents(
        home, "claude", home / ".claude" / "agents"
    )
    items.extend(discovered)
    warnings.extend(errors)

    claude_configs: list[tuple[Path, dict[str, Any]]] = []
    claude_settings: dict[str, Any] = {}
    for path in (home / ".claude.json", home / ".claude" / "settings.json"):
        if path.is_file():
            try:
                config = _read_json(path)
                claude_configs.append((path, config))
                if path.name == "settings.json":
                    claude_settings = config
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
                warnings.append(f"Could not read {_display_path(path, home)}: {exc}")

    enabled_plugins = claude_settings.get("enabledPlugins")
    claude_plugin_roots, errors = _claude_plugin_roots(
        home, enabled_plugins if isinstance(enabled_plugins, dict) else None
    )
    warnings.extend(errors)
    discovered, errors = _plugin_capabilities(home, claude_plugin_roots)
    items.extend(discovered)
    warnings.extend(errors)

    discovered, errors = _mcp_candidates(home, "claude", claude_configs)
    items.extend(discovered)
    warnings.extend(errors)

    codex_path = home / ".codex" / "config.toml"
    codex_config: dict[str, Any] = {}
    if codex_path.is_file():
        try:
            codex_config = _read_toml(codex_path)
        except (OSError, UnicodeError, ValueError, tomllib.TOMLDecodeError) as exc:
            warnings.append(f"Could not read {_display_path(codex_path, home)}: {exc}")
    discovered, errors = _codex_agents(home, codex_config, codex_path)
    items.extend(discovered)
    warnings.extend(errors)
    discovered, errors = _mcp_candidates(home, "codex", [(codex_path, codex_config)] if codex_config else [])
    items.extend(discovered)
    warnings.extend(errors)

    codex_plugin_roots, errors = _codex_plugin_roots(home, codex_config)
    warnings.extend(errors)
    discovered, errors = _plugin_capabilities(home, codex_plugin_roots)
    items.extend(discovered)
    warnings.extend(errors)

    items.sort(key=lambda item: (item.resource_type, item.name.lower(), item.source_runtime))
    return DiscoveryResult(items=items, warnings=warnings)
