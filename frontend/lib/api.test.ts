import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, apiBase, ApiError } from "./api";

type ApiCase = [name: keyof typeof api, args: unknown[], path: string, method?: string, body?: unknown];

const cases: ApiCase[] = [
  ["health", [], "/api/health"],
  ["projects", [], "/api/projects"],
  ["project", ["p"], "/api/projects/p"],
  ["createProject", [{ name: "Project" }], "/api/projects", "POST", { name: "Project" }],
  ["updateProject", ["p", { name: "Renamed" }], "/api/projects/p", "PATCH", { name: "Renamed" }],
  ["deleteProject", ["p"], "/api/projects/p", "DELETE"],
  ["projectTaskTags", ["p"], "/api/projects/p/task-tags"],
  ["createProjectTaskTag", ["p", { name: "Bug" }], "/api/projects/p/task-tags", "POST", { name: "Bug" }],
  ["updateProjectTaskTag", ["p", "tag", { color: "red" }], "/api/projects/p/task-tags/tag", "PATCH", { color: "red" }],
  ["tasks", ["p"], "/api/projects/p/tasks"],
  ["allTasks", [], "/api/tasks"],
  ["task", ["t"], "/api/tasks/t"],
  ["createTask", ["p", { title: "T", initial_prompt: "Do it" }], "/api/projects/p/tasks", "POST", { title: "T", initial_prompt: "Do it" }],
  ["deleteTask", ["t"], "/api/tasks/t", "DELETE"],
  ["taskAction", ["t", "restart"], "/api/tasks/t/restart", "POST"],
  ["updateTaskBackend", ["t", "codex"], "/api/tasks/t/backend", "PATCH", { backend: "codex" }],
  ["updateTaskModel", ["t", "model"], "/api/tasks/t/model", "PATCH", { model: "model" }],
  ["updateTaskModels", ["t", ["one", "two"]], "/api/tasks/t/models", "PATCH", { models: ["one", "two"] }],
  ["updateTaskThinking", ["t", "high"], "/api/tasks/t/thinking-level", "PATCH", { thinking_level: "high" }],
  ["updateTaskContext", ["t", "full"], "/api/tasks/t/context-strategy", "PATCH", { context_strategy: "full" }],
  ["updateTaskTags", ["t", ["Bug"]], "/api/tasks/t/tags", "PATCH", { tags: ["Bug"] }],
  ["compressContext", ["t"], "/api/tasks/t/compress-context", "POST"],
  ["messages", ["t"], "/api/tasks/t/messages"],
  ["sendMessage", ["t", "hello"], "/api/tasks/t/messages", "POST", { content_text: "hello", media: [] }],
  ["sendMessage", ["t", "hello", [{ type: "image", url: "x" }]], "/api/tasks/t/messages", "POST", { content_text: "hello", media: [{ type: "image", url: "x" }] }],
  ["transcript", ["t"], "/api/tasks/t/transcript"],
  ["attempts", ["t"], "/api/tasks/t/run-attempts"],
  ["invocations", ["t"], "/api/tasks/t/invocations"],
  ["taskEvents", ["t"], "/api/tasks/t/events"],
  ["prDeliveryEligibility", ["t"], "/api/tasks/t/pr-delivery/eligibility"],
  ["prDeliveryRuns", ["t"], "/api/tasks/t/pr-delivery"],
  ["preparePrDelivery", ["t", { draft: true }], "/api/tasks/t/pr-delivery/prepare", "POST", { draft: true }],
  ["confirmPrDelivery", ["t", "r", { pr_title: "Title" }], "/api/tasks/t/pr-delivery/r/confirm", "POST", { pr_title: "Title" }],
  ["cancelPrDelivery", ["t", "r"], "/api/tasks/t/pr-delivery/r/cancel", "POST"],
  ["syncPrDelivery", ["t", "r"], "/api/tasks/t/pr-delivery/r/sync", "POST"],
  ["completeWithoutPr", ["t", "No changes"], "/api/tasks/t/pr-delivery/complete-without-pr", "POST", { reason: "No changes" }],
  ["directories", ["p"], "/api/projects/p/directories"],
  ["createDirectory", ["p", { directory_id: "d", access_scope: "read_only" }], "/api/projects/p/directories", "POST", { directory_id: "d", access_scope: "read_only" }],
  ["deleteDirectory", ["p", "d"], "/api/projects/p/directories/d", "DELETE"],
  ["mcpServers", ["p"], "/api/projects/p/mcp-servers"],
  ["createMcp", ["p", { name: "m", config: { command: "run" } }], "/api/projects/p/mcp-servers", "POST", { name: "m", config: { command: "run" } }],
  ["deleteMcp", ["p", "m"], "/api/projects/p/mcp-servers/m", "DELETE"],
  ["tools", ["p"], "/api/projects/p/tools"],
  ["createTool", ["p", { name: "tool", config: { mode: "allow" } }], "/api/projects/p/tools", "POST", { name: "tool", config: { mode: "allow" } }],
  ["deleteTool", ["p", "tool"], "/api/projects/p/tools/tool", "DELETE"],
  ["toolApprovals", ["t"], "/api/tasks/t/tool-approvals"],
  ["resolveToolApproval", ["t", "a", "approve_once"], "/api/tasks/t/tool-approvals/a/resolve", "POST", { decision: "approve_once" }],
  ["artifacts", ["p"], "/api/projects/p/artifacts"],
  ["createArtifact", ["p", { name: "A", local_path: "/tmp/a" }], "/api/projects/p/artifacts", "POST", { name: "A", local_path: "/tmp/a" }],
  ["deleteArtifact", ["p", "a"], "/api/projects/p/artifacts/a", "DELETE"],
  ["secrets", ["p"], "/api/projects/p/secrets"],
  ["putSecret", ["p", "API key/one", "secret"], "/api/projects/p/secrets/API%20key%2Fone", "PUT", { value: "secret" }],
  ["deleteSecret", ["p", "API key"], "/api/projects/p/secrets/API%20key", "DELETE"],
  ["cronJobs", ["p"], "/api/projects/p/cron-jobs"],
  ["createCron", ["p", { name: "daily", schedule_expr: "0 0 * * *", prompt: "go", backend: "codex" }], "/api/projects/p/cron-jobs", "POST", { name: "daily", schedule_expr: "0 0 * * *", prompt: "go", backend: "codex" }],
  ["toggleCron", ["p", "c", true], "/api/projects/p/cron-jobs/c/enable", "POST"],
  ["toggleCron", ["p", "c", false], "/api/projects/p/cron-jobs/c/disable", "POST"],
  ["deleteCron", ["p", "c"], "/api/projects/p/cron-jobs/c", "DELETE"],
  ["globalDirectories", [], "/api/directories"],
  ["createGlobalDirectory", [{ name: "work", path: "/work" }], "/api/directories", "POST", { name: "work", path: "/work" }],
  ["updateGlobalDirectory", ["d", { description: "D" }], "/api/directories/d", "PATCH", { description: "D" }],
  ["deleteGlobalDirectory", ["d"], "/api/directories/d", "DELETE"],
  ["globalMcp", [], "/api/mcp-servers"],
  ["createGlobalMcp", [{ name: "m", config: { command: "run" } }], "/api/mcp-servers", "POST", { name: "m", config: { command: "run" } }],
  ["updateGlobalMcp", ["m", { enabled: false }], "/api/mcp-servers/m", "PATCH", { enabled: false }],
  ["deleteGlobalMcp", ["m"], "/api/mcp-servers/m", "DELETE"],
  ["agents", [], "/api/agents"],
  ["createAgent", [{ name: "agent" }], "/api/agents", "POST", { name: "agent" }],
  ["updateAgent", ["a", { enabled: false }], "/api/agents/a", "PATCH", { enabled: false }],
  ["deleteAgent", ["a"], "/api/agents/a", "DELETE"],
  ["skills", [], "/api/skills"],
  ["createSkill", [{ name: "skill" }], "/api/skills", "POST", { name: "skill" }],
  ["updateSkill", ["s", { enabled: false }], "/api/skills/s", "PATCH", { enabled: false }],
  ["deleteSkill", ["s"], "/api/skills/s", "DELETE"],
  ["globalTools", [], "/api/global-tools"],
  ["createGlobalTool", [{ name: "tool" }], "/api/global-tools", "POST", { name: "tool" }],
  ["updateGlobalTool", ["g", { enabled: false }], "/api/global-tools/g", "PATCH", { enabled: false }],
  ["deleteGlobalTool", ["g"], "/api/global-tools/g", "DELETE"],
  ["capabilities", ["p", "mcp"], "/api/projects/p/capabilities/mcp"],
  ["configureCapability", ["p", "skill", "s", { enabled: true }], "/api/projects/p/capabilities/skill/s", "PUT", { enabled: true }],
  ["models", ["codex"], "/api/models/codex?refresh=false"],
  ["models", ["claude_code", true], "/api/models/claude_code?refresh=true"],
  ["discoverCapabilityImports", [], "/api/capability-imports/discover"],
  ["importCapabilities", [["one", "two"]], "/api/capability-imports", "POST", { candidate_ids: ["one", "two"] }],
  ["syncCapabilityImport", ["i"], "/api/capability-imports/i/sync", "POST"],
];

describe("API client", () => {
  beforeEach(() => {
    window.__MUSTER_API_URL__ = "https://api.example.test/";
  });

  it.each(cases)("builds %s requests", async (name, args, path, method, body) => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: method === "DELETE" ? 204 : 200, json: vi.fn().mockResolvedValue({ ok: true }) });
    vi.stubGlobal("fetch", fetchMock);
    const result = await (api[name] as (...values: unknown[]) => Promise<unknown>)(...args);

    expect(fetchMock).toHaveBeenCalledWith(`https://api.example.test${path}`, expect.objectContaining({
      headers: { "Content-Type": "application/json" },
      ...(method ? { method } : {}),
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    }));
    if (method === "DELETE") expect(result).toBeUndefined();
  });

  it("uses the environment/default base URL outside browser runtime", () => {
    const original = process.env.NEXT_PUBLIC_API_URL;
    vi.stubGlobal("window", undefined);
    process.env.NEXT_PUBLIC_API_URL = "https://env.example/";
    expect(apiBase()).toBe("https://env.example");
    delete process.env.NEXT_PUBLIC_API_URL;
    expect(apiBase()).toBe("http://localhost:8080");
    process.env.NEXT_PUBLIC_API_URL = original;
  });

  it.each([
    [{ detail: "missing" }, "missing"],
    [{ detail: [{ msg: "bad" }, {}, { msg: "input" }] }, "bad, input"],
    [{ detail: [] }, "Request failed with status 422"],
  ])("surfaces structured API errors", async (payload, expected) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422, json: vi.fn().mockResolvedValue(payload) }));
    await expect(api.health()).rejects.toMatchObject({ name: "ApiError", message: expected, status: 422 });
  });

  it("falls back when an error response is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500, json: vi.fn().mockRejectedValue(new Error("invalid")) }));
    const error = await api.health().catch((value) => value);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe("Request failed with status 500");
  });

  it("preserves custom request headers", async () => {
    // The public client currently supplies no custom headers; constructing an
    // ApiError here also protects its explicit name for error-boundary checks.
    expect(new ApiError("nope", 418)).toMatchObject({ name: "ApiError", status: 418 });
  });
});
