import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
const { session } = vi.hoisted(() => ({ session: { resize: vi.fn(), sendBytes: vi.fn(), sendText: vi.fn(), connection: "offline", control: "read_only", exit: { code: 0, archived: true }, error: null } }));
vi.mock("@/hooks/use-terminal-session", () => ({ useTerminalSession: () => session }));
vi.mock("@/components/task/terminal-history", () => ({ TerminalHistory: () => <div>Original session prompt</div> }));
vi.mock("@xterm/xterm", () => ({ Terminal: class {
  cols = 120; rows = 32;
  loadAddon() {} open() {} write() {} focus() {} dispose() {}
  onData() { return { dispose() {} }; } onBinary() { return { dispose() {} }; }
} }));
vi.mock("@xterm/addon-fit", () => ({ FitAddon: class { fit() {} } }));
import { LiveTerminal } from "./live-terminal";
it("opens readable history for closed sessions and retains terminal output", () => {
  render(<LiveTerminal taskId="task" />);
  expect(screen.getByText("Original session prompt")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "View terminal output" }));
  expect(screen.getByText("Archived terminal output")).toBeInTheDocument();
  expect(screen.queryByText("Original session prompt")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "View session history" }));
  expect(screen.getByText("Original session prompt")).toBeInTheDocument();
});
