// Types mirroring backend/app/db/models.py 1:1 (snake_case JSON keys, as
// serialized by FastAPI/Pydantic). See docs/SPEC.md "Data model".

export type AgentBackend = "claude_code" | "codex";

export type TaskStatus =
  | "queued"
  | "running"
  | "waiting_on_you"
  | "done"
  | "failed"
  | "cancelled";

export type MessageSender = "user" | "agent" | "system";

export type AccessScope = "read" | "read_write";

export type FailureClass = "transient" | "other";

export interface Project {
  id: string;
  name: string;
  description: string | null;
  default_backend: AgentBackend;
  default_model: string | null;
  default_context_strategy: string | null;
  archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface DirectoryBinding {
  id: string;
  project_id: string;
  path: string;
  access_scope: AccessScope;
  created_at: string;
}

export interface McpServerConfig {
  command: string;
  args: string[];
  env: Record<string, string>;
}

export interface McpBinding {
  id: string;
  project_id: string;
  name: string;
  config: McpServerConfig;
  created_at: string;
}

export interface ToolBinding {
  id: string;
  project_id: string;
  name: string;
  config: Record<string, unknown>;
  created_at: string;
}

export interface ProjectArtifact {
  id: string;
  project_id: string;
  name: string;
  local_path: string;
  remote_url: string | null;
  created_at: string;
}

export interface Secret {
  key_name: string;
  project_id: string;
  created_at?: string;
  updated_at?: string;
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
  created_at: string;
  updated_at: string;
}

export interface Task {
  id: string;
  project_id: string;
  title: string;
  initial_prompt: string;
  status: TaskStatus;
  backend: AgentBackend;
  model: string | null;
  context_strategy: string | null;
  session_id: string | null;
  cron_job_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface MediaAttachment {
  url?: string;
  name?: string;
  content_type?: string;
  [key: string]: unknown;
}

export interface Message {
  id: string;
  task_id: string;
  sender: MessageSender;
  content_text: string | null;
  media: MediaAttachment[] | null;
  created_at: string;
}

export interface ContextSnapshot {
  id: string;
  task_id: string;
  summary_text: string;
  raw_transcript_path: string | null;
  created_at: string;
}

export interface TaskRunAttempt {
  id: string;
  task_id: string;
  attempt_number: number;
  exit_code: number | null;
  failure_class: FailureClass | null;
  stderr_tail: string | null;
  backoff_seconds: number | null;
  retrying_at: string | null;
  created_at: string;
}

export interface TokenUsage {
  used: number;
  limit: number;
}

export interface ListResponse<T> {
  items: T[];
}
