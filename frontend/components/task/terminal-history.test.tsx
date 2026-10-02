import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
const { terminalHistory } = vi.hoisted(() => ({ terminalHistory: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { terminalHistory } }));
import { TerminalHistory } from "./terminal-history";

function mount() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><TerminalHistory taskId="task" /></QueryClientProvider>);
}
beforeEach(() => terminalHistory.mockReset());
it("loads from the beginning, preserves prompts and appends subsequent activity", async () => {
  terminalHistory.mockResolvedValueOnce({ items: [{ role: "user", text: "Original prompt", timestamp: "2026-10-01" }], next_cursor: "0:123" })
    .mockResolvedValueOnce({ items: [{ role: "assistant", text: "PR raised" }, { role: "tool_result", text: "Tests pass", truncated: true }], next_cursor: null });
  mount();
  expect(await screen.findByText("Original prompt")).toBeInTheDocument();
  expect(terminalHistory).toHaveBeenCalledWith("task", "0:0");
  fireEvent.click(screen.getByRole("button", { name: "Load more history" }));
  expect(await screen.findByText("PR raised")).toBeInTheDocument();
  expect(screen.getByText("Original prompt")).toBeInTheDocument();
  expect(screen.getByText("Tests pass")).toBeInTheDocument();
  expect(terminalHistory).toHaveBeenCalledWith("task", "0:123");
  expect(screen.queryByRole("button", { name: "Load more history" })).not.toBeInTheDocument();
});
it("shows unavailable history explicitly", async () => {
  terminalHistory.mockResolvedValue({ items: [], next_cursor: null });
  mount();
  expect(await screen.findByText(/No saved native conversation/)).toBeInTheDocument();
});
it("allows retry after an archive read fails", async () => {
  terminalHistory.mockRejectedValueOnce(new Error("Read failed"))
    .mockResolvedValueOnce({ items: [{ role: "assistant", text: "Recovered" }], next_cursor: null });
  mount();
  expect(await screen.findByText("Read failed")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(screen.getByText("Recovered")).toBeInTheDocument());
});
