export type AgentBackend = "claude_code" | "codex";
export type TaskStatus =
  | "queued"
  | "running"
  | "waiting_on_you"
  | "done"
  | "failed"
  | "cancelled";
export type AccessScope = "read" | "read_write";
export type MessageSender = "user" | "agent" | "system";

export interface Project {
  id: string;
  name: string;
  description: string | null;
  default_backend: AgentBackend;
  default_model: string | null;
  default_context_strategy: string;
  primary_directory_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectInput {
  name: string;
  description?: string | null;
  default_backend: AgentBackend;
  default_model?: string | null;
  default_context_strategy?: string;
  primary_directory_id?: string | null;
}

export interface Task {
  id: string;
  project_id: string;
  title: string;
  initial_prompt: string;
  status: TaskStatus;
  backend: AgentBackend;
  model: string | null;
  fallback_models: string[];
  tags: string[];
  thinking_level: string;
  agent_id: string | null;
  context_strategy: string;
  session_id: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  cron_job_id: string | null;
}

export interface Message {
  id: string;
  task_id: string;
  sender: MessageSender;
  content_text: string | null;
  media: Array<{ path?: string; mime?: string; name?: string }>;
  is_blocking_question: boolean;
  created_at: string;
  optimistic?: boolean;
}

export interface DirectoryBinding {
  id: string;
  project_id: string;
  directory_id: string | null;
  path: string;
  name: string | null;
  access_scope: AccessScope;
  created_at: string;
}

export interface McpConfig {
  transport?: "stdio" | "http" | "sse";
  command?: string | null;
  args: string[];
  env: Record<string, string>;
  url?: string | null;
  headers?: Record<string, string>;
  bearer_token_env_var?: string | null;
}

export interface McpBinding {
  id: string;
  project_id: string;
  name: string;
  config: McpConfig;
  created_at: string;
}

export interface ToolBinding {
  id: string;
  project_id: string;
  name: string;
  config: Partial<ToolRuleConfig> & Record<string, unknown>;
  created_at: string;
}

export interface ToolRuleConfig {
  backend: "all" | AgentBackend;
  decision: "allow" | "deny";
  claude_pattern: string | null;
  codex_prefix: string[];
}

export interface ToolApproval {
  id: string;
  task_id: string;
  invocation_id: string | null;
  backend: AgentBackend;
  tool_name: string;
  tool_input: Record<string, unknown>;
  permission_rule: ToolRuleConfig;
  reason: string | null;
  status: "pending" | "approved_once" | "approved_project" | "denied" | "consumed";
  resolution_scope: "once" | "project" | null;
  created_at: string;
  resolved_at: string | null;
}

export interface Artifact {
  id: string;
  project_id: string;
  name: string;
  local_path: string;
  remote_url: string | null;
  created_at: string;
}

export interface Secret {
  id: string;
  project_id: string;
  key_name: string;
  created_at: string;
}

export interface CronJob {
  id: string;
  project_id: string;
  name: string;
  schedule_expr: string;
  prompt: string;
  backend: AgentBackend;
  model: string | null;
  enabled: boolean;
  last_run_at: string | null;
  last_status: string | null;
  created_at: string;
}

export interface RunAttempt {
  id: string;
  task_id: string;
  attempt_number: number;
  failure_class: "transient" | "other" | null;
  error_message: string | null;
  backoff_seconds: number | null;
  created_at: string;
}

export interface DirectoryResource {
  id: string;
  name: string;
  path: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface GlobalMcpServer {
  id: string;
  name: string;
  description: string | null;
  config: McpConfig;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface AgentProfile {
  id: string;
  name: string;
  description: string | null;
  backend: AgentBackend;
  system_prompt: string;
  model: string | null;
  thinking_level: string;
  config: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface Skill {
  id: string;
  name: string;
  description: string | null;
  instructions: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface Capability {
  resource_type: "mcp" | "agent" | "skill";
  resource_id: string;
  name: string;
  description: string | null;
  enabled: boolean;
  global_enabled: boolean;
  config: Record<string, unknown>;
}

export interface ModelOption {
  id: string;
  label: string;
  backend: AgentBackend;
  source: string;
}

export interface ModelCatalog {
  backend: AgentBackend;
  items: ModelOption[];
  refreshed_at: string;
  expires_at: string;
  cached: boolean;
  discovery_error: string | null;
}

export type CapabilityImportKind = "agent" | "skill" | "mcp";
export type CapabilityImportRuntime = "claude" | "codex";

export interface CapabilityImportPreview {
  candidate_id: string;
  resource_type: CapabilityImportKind;
  source_runtime: CapabilityImportRuntime;
  source_scope: string;
  source_locator: string;
  name: string;
  target_name: string;
  description: string | null;
  status: "new" | "updated" | "unchanged";
  preview: Record<string, unknown>;
  warnings: string[];
}

export interface CapabilityDiscovery {
  items: CapabilityImportPreview[];
  warnings: string[];
}

export interface CapabilityImportResult {
  items: Array<{
    import_id: string;
    resource_type: CapabilityImportKind;
    resource_id: string;
    name: string;
    action: "created" | "updated" | "unchanged";
  }>;
}

export interface TaskInvocation {
  id: string;
  task_id: string;
  sequence: number;
  backend: AgentBackend;
  session_id: string | null;
  model: string | null;
  thinking_level: string | null;
  status: string;
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  started_at: string;
  completed_at: string | null;
}

export interface TaskEvent {
  id: string;
  task_id: string;
  invocation_id: string | null;
  kind: "invocation" | "log" | "tool_call" | "tool_result" | "agent_call" | "reasoning" | "diff" | string;
  title: string;
  content: string | null;
  event_metadata: Record<string, unknown>;
  created_at: string;
}

export interface ContextSnapshot {
  id: string;
  task_id: string;
  summary_text: string;
  raw_transcript_path: string;
  token_count: number | null;
  created_at: string;
}

export interface ListResponse<T> {
  items: T[];
}

export type TaskStreamEvent =
  | { type: "message"; message: Message }
  | { type: "status"; status: TaskStatus }
  | { type: "run_attempt"; attempt: RunAttempt }
  | { type: "activity"; event: TaskEvent }
  | { type: "invocation"; invocation: TaskInvocation }
  | { type: "token_usage"; used: number; limit: number }
  | { type: "tool_approval"; approval: ToolApproval };
