import type {
  AgentBackend,
  Artifact,
  ContextSnapshot,
  Capability,
  CapabilityDiscovery,
  CapabilityImportResult,
  CronJob,
  DirectoryBinding,
  DirectoryResource,
  GlobalMcpServer,
  GlobalTool,
  AgentProfile,
  Skill,
  ModelCatalog,
  ListResponse,
  McpBinding,
  McpConfig,
  Message,
  Project,
  ProjectInput,
  RunAttempt,
  TaskEvent,
  TaskInvocation,
  Secret,
  Task,
  ToolApproval,
  ToolBinding,
  ToolRuleConfig,
} from "@/lib/types";

declare global {
  interface Window {
    __MUSTER_API_URL__?: string;
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function apiBase(): string {
  if (typeof window !== "undefined" && window.__MUSTER_API_URL__) {
    return window.__MUSTER_API_URL__.replace(/\/$/, "");
  }
  return (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080").replace(/\/$/, "");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string | Array<{ msg?: string }> };
      if (typeof payload.detail === "string") message = payload.detail;
      if (Array.isArray(payload.detail)) {
        message = payload.detail.map((item) => item.msg).filter(Boolean).join(", ") || message;
      }
    } catch {
      // Preserve the HTTP fallback when a response does not contain JSON.
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

export const api = {
  health: () => request<{ status: string }>("/api/health"),
  projects: () => request<ListResponse<Project>>("/api/projects"),
  project: (id: string) => request<Project>(`/api/projects/${id}`),
  createProject: (body: ProjectInput) =>
    request<Project>("/api/projects", { method: "POST", ...json(body) }),
  updateProject: (id: string, body: Partial<ProjectInput>) =>
    request<Project>(`/api/projects/${id}`, { method: "PATCH", ...json(body) }),
  deleteProject: (id: string) => request<void>(`/api/projects/${id}`, { method: "DELETE" }),

  tasks: (projectId: string) =>
    request<ListResponse<Task>>(`/api/projects/${projectId}/tasks`),
  allTasks: () => request<ListResponse<Task>>("/api/tasks"),
  task: (id: string) => request<Task>(`/api/tasks/${id}`),
  createTask: (
    projectId: string,
    body: {
      title: string;
      initial_prompt: string;
      backend?: AgentBackend;
      model?: string;
      context_strategy?: string;
      fallback_models?: string[];
      tags?: string[];
      thinking_level?: string;
      agent_id?: string;
    },
  ) => request<Task>(`/api/projects/${projectId}/tasks`, { method: "POST", ...json(body) }),
  taskAction: (id: string, action: "cancel" | "restart" | "retry-now") =>
    request<Task>(`/api/tasks/${id}/${action}`, { method: "POST" }),
  updateTaskBackend: (id: string, backend: AgentBackend) =>
    request<Task>(`/api/tasks/${id}/backend`, { method: "PATCH", ...json({ backend }) }),
  updateTaskModel: (id: string, model: string) =>
    request<Task>(`/api/tasks/${id}/model`, { method: "PATCH", ...json({ model }) }),
  updateTaskModels: (id: string, models: string[]) =>
    request<Task>(`/api/tasks/${id}/models`, { method: "PATCH", ...json({ models }) }),
  updateTaskThinking: (id: string, thinking_level: string) =>
    request<Task>(`/api/tasks/${id}/thinking-level`, { method: "PATCH", ...json({ thinking_level }) }),
  updateTaskContext: (id: string, context_strategy: string) =>
    request<Task>(`/api/tasks/${id}/context-strategy`, {
      method: "PATCH",
      ...json({ context_strategy }),
    }),
  updateTaskTags: (id: string, tags: string[]) =>
    request<Task>(`/api/tasks/${id}/tags`, { method: "PATCH", ...json({ tags }) }),
  compressContext: (id: string) =>
    request<ContextSnapshot>(`/api/tasks/${id}/compress-context`, { method: "POST" }),
  messages: (id: string) => request<ListResponse<Message>>(`/api/tasks/${id}/messages`),
  sendMessage: (id: string, content_text: string, media: Message["media"] = []) =>
    request<Message>(`/api/tasks/${id}/messages`, {
      method: "POST",
      ...json({ content_text, media }),
    }),
  transcript: (id: string) =>
    request<{ task_id: string; transcript: string }>(`/api/tasks/${id}/transcript`),
  attempts: (id: string) =>
    request<ListResponse<RunAttempt>>(`/api/tasks/${id}/run-attempts`),
  invocations: (id: string) =>
    request<ListResponse<TaskInvocation>>(`/api/tasks/${id}/invocations`),
  taskEvents: (id: string) =>
    request<ListResponse<TaskEvent>>(`/api/tasks/${id}/events`),

  directories: (projectId: string) =>
    request<ListResponse<DirectoryBinding>>(`/api/projects/${projectId}/directories`),
  createDirectory: (projectId: string, body: { directory_id: string; access_scope: string }) =>
    request<DirectoryBinding>(`/api/projects/${projectId}/directories`, {
      method: "POST",
      ...json(body),
    }),
  deleteDirectory: (projectId: string, id: string) =>
    request<void>(`/api/projects/${projectId}/directories/${id}`, { method: "DELETE" }),

  mcpServers: (projectId: string) =>
    request<ListResponse<McpBinding>>(`/api/projects/${projectId}/mcp-servers`),
  createMcp: (projectId: string, body: { name: string; config: McpConfig }) =>
    request<McpBinding>(`/api/projects/${projectId}/mcp-servers`, {
      method: "POST",
      ...json(body),
    }),
  deleteMcp: (projectId: string, id: string) =>
    request<void>(`/api/projects/${projectId}/mcp-servers/${id}`, { method: "DELETE" }),

  tools: (projectId: string) =>
    request<ListResponse<ToolBinding>>(`/api/projects/${projectId}/tools`),
  createTool: (projectId: string, body: { name: string; config: ToolRuleConfig }) =>
    request<ToolBinding>(`/api/projects/${projectId}/tools`, {
      method: "POST",
      ...json(body),
    }),
  deleteTool: (projectId: string, id: string) =>
    request<void>(`/api/projects/${projectId}/tools/${id}`, { method: "DELETE" }),
  toolApprovals: (taskId: string) =>
    request<ListResponse<ToolApproval>>(`/api/tasks/${taskId}/tool-approvals`),
  resolveToolApproval: (
    taskId: string,
    approvalId: string,
    decision: "approve_once" | "always_allow" | "deny",
  ) => request<ToolApproval>(`/api/tasks/${taskId}/tool-approvals/${approvalId}/resolve`, {
    method: "POST",
    ...json({ decision }),
  }),

  artifacts: (projectId: string) =>
    request<ListResponse<Artifact>>(`/api/projects/${projectId}/artifacts`),
  createArtifact: (
    projectId: string,
    body: { name: string; local_path: string; remote_url?: string | null },
  ) =>
    request<Artifact>(`/api/projects/${projectId}/artifacts`, {
      method: "POST",
      ...json(body),
    }),
  deleteArtifact: (projectId: string, id: string) =>
    request<void>(`/api/projects/${projectId}/artifacts/${id}`, { method: "DELETE" }),

  secrets: (projectId: string) =>
    request<ListResponse<Secret>>(`/api/projects/${projectId}/secrets`),
  putSecret: (projectId: string, key: string, value: string) =>
    request<Secret>(`/api/projects/${projectId}/secrets/${encodeURIComponent(key)}`, {
      method: "PUT",
      ...json({ value }),
    }),
  deleteSecret: (projectId: string, key: string) =>
    request<void>(`/api/projects/${projectId}/secrets/${encodeURIComponent(key)}`, {
      method: "DELETE",
    }),

  cronJobs: (projectId: string) =>
    request<ListResponse<CronJob>>(`/api/projects/${projectId}/cron-jobs`),
  createCron: (
    projectId: string,
    body: {
      name: string;
      schedule_expr: string;
      prompt: string;
      backend: AgentBackend;
      model?: string | null;
    },
  ) =>
    request<CronJob>(`/api/projects/${projectId}/cron-jobs`, {
      method: "POST",
      ...json(body),
    }),
  toggleCron: (projectId: string, id: string, enabled: boolean) =>
    request<CronJob>(`/api/projects/${projectId}/cron-jobs/${id}/${enabled ? "enable" : "disable"}`, {
      method: "POST",
    }),
  deleteCron: (projectId: string, id: string) =>
    request<void>(`/api/projects/${projectId}/cron-jobs/${id}`, { method: "DELETE" }),

  globalDirectories: () => request<ListResponse<DirectoryResource>>("/api/directories"),
  createGlobalDirectory: (body: { name: string; path: string; description?: string | null }) =>
    request<DirectoryResource>("/api/directories", { method: "POST", ...json(body) }),
  updateGlobalDirectory: (id: string, body: Partial<{ name: string; path: string; description: string | null }>) =>
    request<DirectoryResource>(`/api/directories/${id}`, { method: "PATCH", ...json(body) }),
  deleteGlobalDirectory: (id: string) => request<void>(`/api/directories/${id}`, { method: "DELETE" }),

  globalMcp: () => request<ListResponse<GlobalMcpServer>>("/api/mcp-servers"),
  createGlobalMcp: (body: { name: string; description?: string | null; config: McpConfig; enabled?: boolean }) =>
    request<GlobalMcpServer>("/api/mcp-servers", { method: "POST", ...json(body) }),
  updateGlobalMcp: (id: string, body: Partial<{ name: string; description: string | null; config: McpConfig; enabled: boolean }>) =>
    request<GlobalMcpServer>(`/api/mcp-servers/${id}`, { method: "PATCH", ...json(body) }),
  deleteGlobalMcp: (id: string) => request<void>(`/api/mcp-servers/${id}`, { method: "DELETE" }),

  agents: () => request<ListResponse<AgentProfile>>("/api/agents"),
  createAgent: (body: Omit<AgentProfile, "id" | "created_at" | "updated_at">) =>
    request<AgentProfile>("/api/agents", { method: "POST", ...json(body) }),
  updateAgent: (id: string, body: Partial<Omit<AgentProfile, "id" | "created_at" | "updated_at">>) =>
    request<AgentProfile>(`/api/agents/${id}`, { method: "PATCH", ...json(body) }),
  deleteAgent: (id: string) => request<void>(`/api/agents/${id}`, { method: "DELETE" }),

  skills: () => request<ListResponse<Skill>>("/api/skills"),
  createSkill: (body: Omit<Skill, "id" | "created_at" | "updated_at">) =>
    request<Skill>("/api/skills", { method: "POST", ...json(body) }),
  updateSkill: (id: string, body: Partial<Omit<Skill, "id" | "created_at" | "updated_at">>) =>
    request<Skill>(`/api/skills/${id}`, { method: "PATCH", ...json(body) }),
  deleteSkill: (id: string) => request<void>(`/api/skills/${id}`, { method: "DELETE" }),

  globalTools: () => request<ListResponse<GlobalTool>>("/api/global-tools"),
  createGlobalTool: (body: Omit<GlobalTool, "id" | "created_at" | "updated_at">) =>
    request<GlobalTool>("/api/global-tools", { method: "POST", ...json(body) }),
  updateGlobalTool: (id: string, body: Partial<Omit<GlobalTool, "id" | "created_at" | "updated_at">>) =>
    request<GlobalTool>(`/api/global-tools/${id}`, { method: "PATCH", ...json(body) }),
  deleteGlobalTool: (id: string) => request<void>(`/api/global-tools/${id}`, { method: "DELETE" }),

  capabilities: (projectId: string, type: "mcp" | "agent" | "skill" | "tool") =>
    request<ListResponse<Capability>>(`/api/projects/${projectId}/capabilities/${type}`),
  configureCapability: (projectId: string, type: "mcp" | "agent" | "skill" | "tool", id: string, body: { enabled: boolean; config_override?: Record<string, unknown> }) =>
    request<Capability>(`/api/projects/${projectId}/capabilities/${type}/${id}`, { method: "PUT", ...json(body) }),
  models: (backend: AgentBackend, refresh = false) =>
    request<ModelCatalog>(`/api/models/${backend}?refresh=${refresh}`),
  discoverCapabilityImports: () =>
    request<CapabilityDiscovery>("/api/capability-imports/discover"),
  importCapabilities: (candidateIds: string[]) =>
    request<CapabilityImportResult>("/api/capability-imports", {
      method: "POST",
      ...json({ candidate_ids: candidateIds }),
    }),
  syncCapabilityImport: (importId: string) =>
    request<CapabilityImportResult>(`/api/capability-imports/${importId}/sync`, {
      method: "POST",
    }),
};
