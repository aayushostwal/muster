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


def _skill_candidates(home: Path, runtime: SourceRuntime, root: Path) -> tuple[list[DiscoveredCapability], list[str]]:
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
            items.append(
                DiscoveredCapability(
                    resource_type="skill",
                    source_runtime=runtime,
                    source_scope="user",
                    source_locator=locator,
                    name=name,
                    description=description,
                    payload={"name": name, "description": description, "instructions": instructions, "enabled": True},
                    preview={"instruction_characters": len(instructions), "supporting_files": len(support_files)},
                    warnings=item_warnings,
                    source_metadata={"manifest": locator, "supporting_files": len(support_files)},
                )
            )
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
            warnings.append(f"Could not read {locator}: {exc}")
    return items, warnings


def _claude_agents(home: Path) -> tuple[list[DiscoveredCapability], list[str]]:
    root = home / ".claude" / "agents"
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
                key: metadata[key]
                for key in ("tools", "disallowedTools", "permissionMode", "maxTurns")
                if key in metadata
            }
            items.append(
                DiscoveredCapability(
                    resource_type="agent",
                    source_runtime="claude",
                    source_scope="user",
                    source_locator=locator,
                    name=name,
                    description=description,
                    payload={
                        "name": name,
                        "description": description,
                        "backend": "claude_code",
                        "system_prompt": prompt,
                        "model": str(model) if model else None,
                        "thinking_level": thinking,
                        "config": portable_config,
                        "enabled": True,
                    },
                    preview={
                        "backend": "claude_code",
                        "model": model,
                        "thinking_level": thinking,
                        "configured_tools": metadata.get("tools") or [],
                    },
                    source_metadata={"file": locator},
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
                source_scope="user",
                source_locator=locator,
                name=name,
                description=f"Imported from {runtime.title()} user configuration",
                payload={"name": name, "description": f"Imported from {runtime.title()}", "config": config, "enabled": True},
                preview=_mcp_preview(config),
                warnings=item_warnings,
                source_metadata={"config": _display_path(path, home)},
            )
        )
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

    discovered, errors = _claude_agents(home)
    items.extend(discovered)
    warnings.extend(errors)

    claude_configs: list[tuple[Path, dict[str, Any]]] = []
    for path in (home / ".claude.json", home / ".claude" / "settings.json"):
        if path.is_file():
            try:
                claude_configs.append((path, _read_json(path)))
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
                warnings.append(f"Could not read {_display_path(path, home)}: {exc}")
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

    items.sort(key=lambda item: (item.resource_type, item.name.lower(), item.source_runtime))
    return DiscoveryResult(items=items, warnings=warnings)
