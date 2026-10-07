import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LiveTerminal } from "./live-terminal";

const mocks = vi.hoisted(() => ({
  sendText: vi.fn(),
  sendBytes: vi.fn(),
  resize: vi.fn(),
  keyHandler: undefined as undefined | ((event: KeyboardEvent) => boolean),
  onData: undefined as undefined | ((data: string) => void),
  fit: vi.fn(),
  disconnect: vi.fn(),
  exit: null as null | { code: number; archived: boolean },
}));

vi.mock("@/hooks/use-terminal-session", () => ({
  useTerminalSession: () => ({
    sendText: mocks.sendText, sendBytes: mocks.sendBytes, resize: mocks.resize,
    connection: "live", control: "granted", exit: mocks.exit, error: null,
  }),
}));
vi.mock("@/components/task/terminal-history", () => ({ TerminalHistory: () => <div>Original session prompt</div> }));
vi.mock("@xterm/xterm", () => ({
  Terminal: class {
    cols = 80;
    rows = 24;
    loadAddon() {}
    open() {}
    focus() {}
    dispose() {}
    attachCustomKeyEventHandler(handler: (event: KeyboardEvent) => boolean) { mocks.keyHandler = handler; }
    onData(handler: (data: string) => void) { mocks.onData = handler; return { dispose() {} }; }
    onBinary() { return { dispose() {} }; }
  },
}));
vi.mock("@xterm/addon-fit", () => ({ FitAddon: class { fit = mocks.fit; } }));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.keyHandler = undefined;
  mocks.onData = undefined;
  mocks.exit = null;
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    disconnect = mocks.disconnect;
  });
});

async function mountTerminal() {
  const view = render(<LiveTerminal taskId="task-1" />);
  await waitFor(() => expect(mocks.keyHandler).toBeDefined());
  return view;
}

describe("LiveTerminal keyboard input", () => {
  it("opens readable history for closed sessions and retains terminal output", async () => {
    mocks.exit = { code: 0, archived: true };
    await mountTerminal();
    expect(screen.getByText("Original session prompt")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View terminal output" }));
    expect(screen.getByText("Archived terminal output")).toBeInTheDocument();
    expect(screen.queryByText("Original session prompt")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View session history" }));
    expect(screen.getByText("Original session prompt")).toBeInTheDocument();
  });
  it("sends a newline once on Shift+Enter and suppresses native submission", async () => {
    await mountTerminal();
    const event = new KeyboardEvent("keydown", { key: "Enter", shiftKey: true, cancelable: true });
    expect(mocks.keyHandler!(event)).toBe(false);
    expect(event.defaultPrevented).toBe(true);
    expect(mocks.sendText).toHaveBeenCalledExactlyOnceWith("\n");
    expect(mocks.keyHandler!(new KeyboardEvent("keyup", { key: "Enter", shiftKey: true }))).toBe(false);
    expect(mocks.keyHandler!(new KeyboardEvent("keypress", { key: "Enter", shiftKey: true }))).toBe(false);
    expect(mocks.sendText).toHaveBeenCalledTimes(1);
  });

  it("keeps plain Enter on the native submit path", async () => {
    await mountTerminal();
    expect(mocks.keyHandler!(new KeyboardEvent("keydown", { key: "Enter" }))).toBe(true);
    expect(mocks.sendText).not.toHaveBeenCalled();
    mocks.onData!("\r");
    expect(mocks.sendText).toHaveBeenCalledExactlyOnceWith("\r");
  });

  it.each([
    { key: "Tab", shiftKey: true },
    { key: "Enter", shiftKey: true, ctrlKey: true },
    { key: "Enter", shiftKey: true, altKey: true },
    { key: "Enter", shiftKey: true, metaKey: true },
    { key: "Enter", shiftKey: true, isComposing: true },
  ])("preserves other shortcuts and composing input: %j", async (options) => {
    await mountTerminal();
    expect(mocks.keyHandler!(new KeyboardEvent("keydown", options))).toBe(true);
    expect(mocks.sendText).not.toHaveBeenCalled();
  });

  it("fits the terminal inside an unpadded host and cleans up its observer", async () => {
    const view = await mountTerminal();
    const host = screen.getByLabelText("Interactive agent terminal");
    expect(host).toHaveClass("h-full");
    expect(host.parentElement).toHaveClass("pb-6", "pt-12", "px-2");
    expect(host).not.toHaveClass("pb-6", "pt-12", "px-2");
    expect(mocks.fit).toHaveBeenCalledTimes(1);
    expect(mocks.resize).toHaveBeenCalledWith(80, 24);
    view.unmount();
    expect(mocks.disconnect).toHaveBeenCalledTimes(1);
  });
});
