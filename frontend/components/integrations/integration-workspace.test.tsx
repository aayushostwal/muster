import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { projects, allCronJobs, models, updateCron } = vi.hoisted(() => ({
  projects: vi.fn(), allCronJobs: vi.fn(), models: vi.fn(), updateCron: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: { projects, allCronJobs, models, updateCron } }));

import { IntegrationWorkspace } from "./integration-workspace";

const job = {
  id: "job-1", project_id: "project-1", name: "Triage", schedule_expr: "0 * * * *",
  interval_minutes: 120, prompt: "Review Jira", backend: "codex", model: "gpt-example",
  thinking_level: "medium", enabled: true, last_run_at: null, last_status: null, created_at: "2026-09-30T00:00:00Z",
};

function renderWorkspace() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><IntegrationWorkspace /></QueryClientProvider>);
}

beforeEach(() => {
  projects.mockReset().mockResolvedValue({ items: [{ id: "project-1", name: "Work", primary_directory_id: "dir-1" }] });
  allCronJobs.mockReset().mockResolvedValue({ items: [job] });
  models.mockReset().mockResolvedValue({ items: [{ id: "gpt-example", label: "GPT example" }] });
  updateCron.mockReset().mockResolvedValue({ ...job, thinking_level: "high" });
  HTMLElement.prototype.scrollIntoView = vi.fn();
});

describe("recurring agent editor", () => {
  it("loads an existing job and saves model, thinking, prompt, and interval", async () => {
    renderWorkspace();
    await screen.findByRole("button", { name: "Edit" });
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));

    expect(screen.getByRole("textbox", { name: "Agent prompt" })).toHaveValue("Review Jira");
    expect(screen.getByLabelText("Model")).toHaveValue("gpt-example");
    expect(screen.getByLabelText("Frequency")).toHaveValue(2);
    expect(screen.getByLabelText("Frequency unit")).toHaveValue("hours");
    fireEvent.change(screen.getByLabelText("Thinking level"), { target: { value: "high" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateCron).toHaveBeenCalledWith("project-1", "job-1", {
      name: "Triage", prompt: "Review Jira", backend: "codex", model: "gpt-example",
      thinking_level: "high", interval_minutes: 120,
    }));
  });

  it("preserves a legacy cron expression while editing other settings", async () => {
    allCronJobs.mockResolvedValue({ items: [{ ...job, interval_minutes: null, schedule_expr: "0 9 * * 1-5" }] });
    renderWorkspace();
    await screen.findByRole("button", { name: "Edit" });
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    expect(screen.getByText("Current: 0 9 * * 1-5")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateCron).toHaveBeenCalled());
    expect(updateCron.mock.calls[0][2]).not.toHaveProperty("interval_minutes");
  });

  it("shows paused jobs across projects before selecting a project", async () => {
    allCronJobs.mockResolvedValue({ items: [{ ...job, enabled: false }] });
    renderWorkspace();
    expect(await screen.findByText("Triage")).toBeInTheDocument();
    expect(screen.getByText("Paused")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run now" })).toBeEnabled();
    expect(screen.getByLabelText("Project")).toHaveValue("");
  });
});
