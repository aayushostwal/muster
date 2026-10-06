import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { task, sendMessage, invocations } = vi.hoisted(() => ({
  task: vi.fn(), sendMessage: vi.fn(), invocations: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/hooks/use-task-stream", () => ({ useTaskStream: () => ({ connection: "offline", tokenUsage: null, prSuggestion: null }) }));
vi.mock("@/hooks/use-slash-commands", () => ({ SLASH_PATTERN: /(?:^|\s)\/([\w-]*)$/, useSlashCommands: () => ({ suggestions: [], isPending: false, isError: false }) }));
vi.mock("@/components/ui/toast", () => ({ useToast: () => vi.fn() }));
vi.mock("@/components/task/live-terminal", () => ({ LiveTerminal: () => <div>Archived terminal output</div> }));
vi.mock("@/components/task/magic-canvas", () => ({ MagicCanvas: () => null }));
vi.mock("@/components/task/pr-delivery-bar", () => ({ PrDeliveryPanel: () => null }));
vi.mock("@/lib/api", () => ({ api: {
  task, sendMessage, invocations,
  messages: vi.fn(async () => ({ items: [] })),
  attempts: vi.fn(async () => ({ items: [] })),
  taskEvents: vi.fn(async () => ({ items: [] })),
  toolApprovals: vi.fn(async () => ({ items: [] })),
  project: vi.fn(async () => ({ id: "project-1", name: "Relay", default_backend: "codex" })),
} }));

import { TaskConsole } from "./task-console";

const closed = {
  id: "task-1", project_id: "project-1", title: "Update PR #43", backend: "codex",
  runtime_mode: "interactive", status: "waiting_on_you", attention_reason: "awaiting_review",
  initial_prompt: "Fix authorization", media: [], model: "gpt-5.6-sol", thinking_level: "medium",
  tags: [], fallback_models: [], completed_at: null,
};

beforeEach(() => {
  task.mockReset().mockResolvedValue(closed);
  sendMessage.mockReset().mockResolvedValue({ id: "message-1", task_id: "task-1", sender: "user", content_text: "Add this comment to the PR", media: [] });
  invocations.mockReset().mockResolvedValue({ items: [{ id: "old-session", runtime_mode: "interactive" }] });
});

describe("interactive task follow-ups", () => {
  it("sends a follow-up from an archived terminal and refreshes the new invocation without a task stream", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><TaskConsole taskId="task-1" /></QueryClientProvider>);
    const composer = await screen.findByRole("combobox", { name: "Message agent" });
    expect(screen.getByText("Archived terminal output")).toBeInTheDocument();
    fireEvent.change(composer, { target: { value: "Add this comment to the PR" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(sendMessage).toHaveBeenCalledWith("task-1", "Add this comment to the PR", []));
    await waitFor(() => expect(invocations).toHaveBeenCalledTimes(2));
  });
});
