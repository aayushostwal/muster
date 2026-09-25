"""Discovery and snapshot import coverage for local Claude and Codex capabilities."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import capability_imports, registry
from app.db.session import get_db
from app.services.capability_imports import discover_capabilities


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _source_home(tmp_path: Path) -> Path:
    _write(
        tmp_path / ".claude" / "agents" / "reviewer.md",
        "---\nname: Reviewer\ndescription: Reviews changes\nmodel: sonnet\n"
        "tools: Bash, Read, Grep\n---\n"
        "Review changes for correctness and security.\n",
    )
    _write(
        tmp_path / ".claude" / "skills" / "release" / "SKILL.md",
        "---\nname: Release\ndescription: Prepare releases\n---\n"
        "Validate the release, changelog, and rollback plan.\n",
    )
    _write(tmp_path / ".claude" / "skills" / "release" / "checklist.md", "supporting file")
    _write(
        tmp_path / ".claude" / "settings.json",
        json.dumps(
            {
                "mcpServers": {
                    "issues": {
                        "command": "npx",
                        "args": ["issue-server"],
                        "env": {"SECRET_TOKEN": "never-show-this"},
                    }
                }
            }
        ),
    )
    _write(
        tmp_path / ".codex" / "skills" / "deploy" / "SKILL.md",
        "---\nname: Deploy\ndescription: Deploy safely\n---\n"
        "Use staged rollout and verify health checks.\n",
    )
    _write(
        tmp_path / ".codex" / "reviewer.toml",
        'model = "gpt-5.3-codex"\nmodel_reasoning_effort = "high"\n'
        'developer_instructions = "Review implementation risks."\n',
    )
    _write(
        tmp_path / ".codex" / "config.toml",
        '[agents.reviewer]\ndescription = "Codex reviewer"\nconfig_file = "reviewer.toml"\n\n'
        '[mcp_servers.docs]\nurl = "https://mcp.example.test"\n'
        'bearer_token_env_var = "DOCS_TOKEN"\n',
    )
    return tmp_path


def test_discovery_normalizes_sources_and_redacts_secret_values(tmp_path: Path):
    result = discover_capabilities(_source_home(tmp_path))

    assert {(item.source_runtime, item.resource_type) for item in result.items} == {
        ("claude", "agent"),
        ("claude", "skill"),
        ("claude", "mcp"),
        ("codex", "agent"),
        ("codex", "skill"),
        ("codex", "mcp"),
    }
    issue_server = next(item for item in result.items if item.name == "issues")
    assert issue_server.payload["config"]["env"]["SECRET_TOKEN"] == "never-show-this"
    assert "never-show-this" not in json.dumps(issue_server.preview)
    assert issue_server.preview["environment_keys"] == ["SECRET_TOKEN"]
    release = next(item for item in result.items if item.name == "Release")
    assert release.warnings
    reviewer = next(item for item in result.items if item.name == "Reviewer")
    assert reviewer.payload["config"]["tools"] == ["Bash", "Read", "Grep"]


def test_discovery_includes_enabled_plugin_agents_and_skills_only(tmp_path: Path):
    claude_root = tmp_path / ".claude" / "plugins" / "cache" / "nexus" / "nexus" / "1.35.0"
    _write(
        claude_root / "skills" / "incident" / "SKILL.md",
        "---\nname: Nexus Incident\ndescription: Handle incidents\n---\nStabilize and investigate.\n",
    )
    _write(
        claude_root / "agents" / "reviewer.md",
        "---\nname: Nexus Reviewer\ndescription: Reviews production changes\n---\nReview safely.\n",
    )
    _write(
        claude_root / ".mcp.json",
        json.dumps(
            {
                "mcpServers": {
                    "slack": {
                        "type": "http",
                        "url": "https://mcp.slack.test/mcp",
                        "oauth": {"clientId": "managed-by-claude"},
                    }
                }
            }
        ),
    )
    disabled_claude_root = (
        tmp_path / ".claude" / "plugins" / "cache" / "disabled" / "disabled" / "1.0.0"
    )
    _write(
        disabled_claude_root / ".mcp.json",
        json.dumps(
            {
                "mcpServers": {
                    "disabled-connector": {"url": "https://disabled.example.test/mcp"}
                }
            }
        ),
    )
    _write(
        tmp_path / ".claude" / "plugins" / "installed_plugins.json",
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "nexus@nexus-marketplace": [
                        {
                            "scope": "user",
                            "installPath": str(claude_root),
                            "version": "1.35.0",
                        }
                    ],
                    "disabled@claude-plugins-official": [
                        {
                            "scope": "user",
                            "installPath": str(disabled_claude_root),
                            "version": "1.0.0",
                        }
                    ],
                },
            }
        ),
    )
    _write(
        tmp_path / ".claude" / "settings.json",
        json.dumps(
            {
                "enabledPlugins": {
                    "nexus@nexus-marketplace": True,
                    "disabled@claude-plugins-official": False,
                }
            }
        ),
    )

    codex_root = tmp_path / ".codex" / "plugins" / "nexus"
    _write(
        codex_root / "skills" / "planning" / "SKILL.md",
        "---\nname: Nexus Planning\ndescription: Plan execution\n---\nProduce an execution plan.\n",
    )
    _write(
        codex_root / "agents" / "architect.md",
        "---\nname: Nexus Architect\ndescription: Maps architecture\n---\nMap system boundaries.\n",
    )
    disabled_root = tmp_path / ".codex" / "plugins" / "disabled"
    _write(
        disabled_root / "skills" / "hidden" / "SKILL.md",
        "---\nname: Disabled Skill\n---\nDo not discover.\n",
    )
    _write(
        tmp_path / ".codex" / "plugins" / "cache" / "unused-market" / "stale" / "1.0" / "skills" / "old" / "SKILL.md",
        "---\nname: Stale Skill\n---\nDo not discover.\n",
    )
    _write(
        tmp_path / ".codex" / "config.toml",
        '[plugins."nexus@codex-marketplace-global"]\nenabled = true\n\n'
        '[plugins."disabled@marketplace"]\nenabled = false\n',
    )

    result = discover_capabilities(tmp_path)
    by_name = {item.name: item for item in result.items}

    assert {
        "Nexus Incident",
        "Nexus Reviewer",
        "Nexus Planning",
        "Nexus Architect",
        "slack",
    } <= by_name.keys()
    assert "Disabled Skill" not in by_name
    assert "Stale Skill" not in by_name
    assert "disabled-connector" not in by_name
    assert by_name["Nexus Incident"].source_scope == "plugin"
    assert by_name["Nexus Incident"].source_metadata["plugin"] == "nexus@nexus-marketplace"
    assert by_name["Nexus Reviewer"].payload["backend"] == "claude_code"
    assert by_name["Nexus Architect"].payload["backend"] == "codex"
    assert by_name["Nexus Planning"].preview["plugin"] == "nexus@codex-marketplace-global"
    assert by_name["slack"].source_scope == "plugin"
    assert by_name["slack"].source_metadata["plugin"] == "nexus@nexus-marketplace"
    assert by_name["slack"].payload["config"]["url"] == "https://mcp.slack.test/mcp"
    assert by_name["slack"].warnings == [
        "OAuth authorization state is managed by Claude and is not copied into Muster"
    ]
    assert result.warnings == []


def _build_app(override_get_db) -> FastAPI:
    app = FastAPI()
    app.include_router(capability_imports.router, prefix="/api")
    app.include_router(registry.router, prefix="/api")
    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.mark.asyncio
async def test_import_is_idempotent_and_resyncs_changes(
    override_get_db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = _source_home(tmp_path)
    monkeypatch.setattr(
        capability_imports,
        "discover_capabilities",
        lambda: discover_capabilities(home),
    )
    app = _build_app(override_get_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        discovery = await client.get("/api/capability-imports/discover")
        assert discovery.status_code == 200
        candidates = discovery.json()["items"]
        assert len(candidates) == 6
        assert all("never-show-this" not in json.dumps(item) for item in candidates)

        imported = await client.post(
            "/api/capability-imports",
            json={"candidate_ids": [item["candidate_id"] for item in candidates]},
        )
        assert imported.status_code == 200
        assert {item["action"] for item in imported.json()["items"]} == {"created"}

        repeated = await client.post(
            "/api/capability-imports",
            json={"candidate_ids": [item["candidate_id"] for item in candidates]},
        )
        assert repeated.status_code == 200
        assert {item["action"] for item in repeated.json()["items"]} == {"unchanged"}

        manifest = home / ".claude" / "skills" / "release" / "SKILL.md"
        manifest.write_text(manifest.read_text() + "\nAlways verify the rollback.\n")
        changed = await client.get("/api/capability-imports/discover")
        release = next(item for item in changed.json()["items"] if item["name"] == "Release")
        assert release["status"] == "updated"
        updated = await client.post(
            "/api/capability-imports", json={"candidate_ids": [release["candidate_id"]]}
        )
        assert updated.status_code == 200
        assert updated.json()["items"][0]["action"] == "updated"

        skills = await client.get("/api/skills")
        synced = next(item for item in skills.json()["items"] if item["name"] == "Release")
        assert "Always verify the rollback" in synced["instructions"]


@pytest.mark.asyncio
async def test_import_resolves_existing_name_collision(
    override_get_db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = _source_home(tmp_path)
    monkeypatch.setattr(
        capability_imports,
        "discover_capabilities",
        lambda: discover_capabilities(home),
    )
    app = _build_app(override_get_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        existing = await client.post(
            "/api/skills",
            json={"name": "Release", "instructions": "Existing local skill"},
        )
        assert existing.status_code == 201
        discovery = (await client.get("/api/capability-imports/discover")).json()["items"]
        release = next(item for item in discovery if item["name"] == "Release")
        assert release["target_name"] == "Release (Claude)"
        response = await client.post(
            "/api/capability-imports", json={"candidate_ids": [release["candidate_id"]]}
        )
        assert response.status_code == 200
        assert response.json()["items"][0]["name"] == "Release (Claude)"
