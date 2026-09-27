import { describe, expect, it } from "vitest";

import { collectSkillTags, filterRegistryResources, normalizeSkillTags } from "./registry";
import type { AgentProfile, DirectoryResource, GlobalMcpServer, GlobalTool, Skill } from "./types";

const timestamps = { created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" };

describe("skill tags", () => {
  it("normalizes whitespace and case-insensitive duplicates", () => {
    expect(normalizeSkillTags([" Review ", "review", "release   safety", ""])).toEqual({
      tags: ["Review", "release safety"],
      error: null,
    });
  });

  it("rejects excessive tag length and count", () => {
    expect(normalizeSkillTags(["x".repeat(33)]).error).toContain("32");
    expect(normalizeSkillTags(Array.from({ length: 13 }, (_, index) => `tag-${index}`))).toMatchObject({
      tags: expect.any(Array),
      error: expect.stringContaining("12"),
    });
  });
});

describe("registry filtering", () => {
  const skills: Skill[] = [
    { id: "s1", name: "Release", description: "Ship safely", instructions: "Validate rollback", tags: ["deploy", "safety"], enabled: true, ...timestamps },
    { id: "s2", name: "Reviewer", description: null, instructions: "Inspect code", tags: ["quality"], enabled: false, ...timestamps },
  ];

  it("searches detailed content and applies status and tag filters", () => {
    expect(filterRegistryResources(skills, "skills", "rollback", "all", []).map((item) => item.id)).toEqual(["s1"]);
    expect(filterRegistryResources(skills, "skills", "", "disabled", []).map((item) => item.id)).toEqual(["s2"]);
    expect(filterRegistryResources(skills, "skills", "", "all", ["SAFETY"]).map((item) => item.id)).toEqual(["s1"]);
    expect(collectSkillTags(skills)).toEqual(["deploy", "quality", "safety"]);
  });

  it("searches portable agent prompt content", () => {
    const agents: AgentProfile[] = [{
      id: "a1", name: "Architect", description: "Designs systems", system_prompt: "Map service boundaries", config: {}, enabled: true, ...timestamps,
    }];
    expect(filterRegistryResources(agents, "agents", "boundaries", "enabled", [])).toHaveLength(1);
    expect(filterRegistryResources(agents, "agents", "missing", "all", [])).toHaveLength(0);
    expect(collectSkillTags(agents)).toEqual([]);
  });

  it("searches connector, tool, and directory configuration", () => {
    const connector: GlobalMcpServer = {
      id: "m1", name: "Docs", description: null, config: { transport: "http", url: "https://mcp.example.test", args: [], env: {} }, enabled: true, ...timestamps,
    };
    const tool: GlobalTool = {
      id: "t1", name: "Search", description: null, config: { backend: "all", decision: "allow", claude_pattern: "Grep", codex_prefix: ["rg"] }, enabled: true, ...timestamps,
    };
    const directory: DirectoryResource = {
      id: "d1", name: "Workspace", path: "/workspace/muster", description: null, ...timestamps,
    };

    expect(filterRegistryResources([connector], "mcp", "example.test", "all", [])).toEqual([connector]);
    expect(filterRegistryResources([tool], "tools", "rg", "all", [])).toEqual([tool]);
    expect(filterRegistryResources([directory], "directories", "/workspace", "all", [])).toEqual([directory]);
    expect(filterRegistryResources(skills, "skills", "", "all", ["missing"])).toEqual([]);
  });
});
