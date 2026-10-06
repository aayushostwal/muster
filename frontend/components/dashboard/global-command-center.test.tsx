import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { projects, allTasks } = vi.hoisted(() => ({ projects: vi.fn(), allTasks: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { projects, allTasks } }));

import { GlobalCommandCenter } from "./global-command-center";

const baseTask = {
  project_id: "project-1", initial_prompt: "Keep the useful execution context visible", media: [],
  backend: "codex", runtime_mode: "structured", model: "gpt-example", fallback_models: [],
  tags: ["UI"], thinking_level: "medium", agent_id: null, context_strategy: "full",
  session_id: null, created_at: "2026-10-06T08:00:00Z", updated_at: "2026-10-06T08:00:00Z",
  started_at: "2026-10-06T08:00:00Z", completed_at: null, cron_job_id: null,
};

function renderCenter() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><GlobalCommandCenter /></QueryClientProvider>);
}

beforeEach(() => {
  projects.mockReset().mockResolvedValue({ items: [{ id: "project-1", name: "Muster" }] });
  allTasks.mockReset().mockResolvedValue({ items: [
    { ...baseTask, id: "running-task", title: "Live agent run", status: "running", attention_reason: null },
    { ...baseTask, id: "attention-task", title: "Permission decision", status: "waiting_on_you", attention_reason: "tool_permission", updated_at: "2026-10-06T07:00:00Z" },
    { ...baseTask, id: "queued-task", title: "Queued follow-up", status: "queued", attention_reason: null, started_at: null },
    { ...baseTask, id: "done-task", title: "Old completed task", status: "done", attention_reason: null, completed_at: "2026-10-06T08:30:00Z" },
  ] });
});

describe("global command center priority view", () => {
  it("keeps attention and running tasks in the main surface and relegates queue/history", async () => {
    renderCenter();
    const priority = await screen.findByText("Priority work");
    const main = priority.closest("main");
    expect(main).not.toBeNull();
    const cards = within(main!).getAllByRole("article");
    expect(within(cards[0]).getByText("Permission decision")).toBeInTheDocument();
    expect(within(cards[1]).getByText("Live agent run")).toBeInTheDocument();
    expect(within(main!).getByText("Queued follow-up")).toBeInTheDocument();
    expect(screen.queryByText("Old completed task")).not.toBeInTheDocument();
  });
});
