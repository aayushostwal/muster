import type { PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { push, agents, skills } = vi.hoisted(() => ({
  push: vi.fn(),
  agents: vi.fn(),
  skills: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/api", () => ({
  apiBase: () => "https://api.example.test",
  api: { agents, skills },
}));

import { useSlashCommands } from "./use-slash-commands";
import { useTaskNotifications } from "./use-task-notifications";
import { useTaskStream } from "./use-task-stream";
import { useTerminalSession } from "./use-terminal-session";

class MockSocket {
  static OPEN = 1;
  static instances: MockSocket[] = [];
  readonly url: string;
  readyState = 1;
  send = vi.fn();
  close = vi.fn();
  onopen: (() => void) | null = null;
  onmessage: ((message: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockSocket.instances.push(this);
  }

  emit(value: unknown) {
    this.onmessage?.({ data: typeof value === "string" ? value : JSON.stringify(value) });
  }
}

function queryWrapper(client: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

beforeEach(() => {
  MockSocket.instances = [];
  push.mockReset();
  agents.mockReset();
  skills.mockReset();
  vi.stubGlobal("WebSocket", MockSocket);
  Object.defineProperty(window, "focus", { configurable: true, value: vi.fn() });
});

describe("useSlashCommands", () => {
  it("loads enabled commands, sorts, filters, and reports query state", async () => {
    agents.mockResolvedValue({ items: [
      { id: "a1", name: "Zed", enabled: true, description: null },
      { id: "a2", name: "Hidden", enabled: false, description: null },
    ] });
    skills.mockResolvedValue({ items: [{ id: "s1", name: "Analyze", enabled: true, description: "Inspect" }] });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result, rerender } = renderHook(({ query }) => useSlashCommands(query), {
      initialProps: { query: "" as string | null },
      wrapper: queryWrapper(client),
    });
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current.suggestions.map((item) => item.name)).toEqual(["Analyze", "pr", "Zed"]);
    rerender({ query: "zed" });
    expect(result.current.suggestions.map((item) => item.name)).toEqual(["Zed"]);
    rerender({ query: null });
    expect(result.current.suggestions).toEqual([]);
  });

  it("surfaces query failures", async () => {
    agents.mockRejectedValue(new Error("offline"));
    skills.mockResolvedValue({ items: [] });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useSlashCommands(""), { wrapper: queryWrapper(client) });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

describe("useTaskStream", () => {
  it("connects and projects every stream event into query state", () => {
    const client = new QueryClient();
    const { result, unmount } = renderHook(() => useTaskStream("t"), { wrapper: queryWrapper(client) });
    const socket = MockSocket.instances[0];
    expect(socket.url).toBe("wss://api.example.test/ws/tasks/t");
    act(() => socket.onopen?.());
    expect(result.current.connection).toBe("live");

    const events = [
      { type: "message", message: { id: "m", content_text: "hello" } },
      { type: "message", message: { id: "m", content_text: "duplicate" } },
      { type: "status", status: "queued" },
      { type: "status", status: "running", attention_reason: "approval_required" },
      { type: "run_attempt", attempt: { id: "run" } },
      { type: "activity", event: { id: "event" } },
      { type: "activity", event: { id: "event" } },
      { type: "invocation", invocation: { id: "invoke", status: "running" } },
      { type: "invocation", invocation: { id: "invoke", status: "done" } },
      { type: "token_usage", used: 25, limit: 100 },
      { type: "tool_approval", approval: { id: "approval" } },
      { type: "tool_approval", approval: { id: "approval" } },
      { type: "pr_suggestion", eligible_file_count: 3 },
      { type: "pr_delivery", run: { id: "pr", status: "prepared" } },
      { type: "pr_delivery", run: { id: "pr", status: "opened" } },
    ];
    for (const event of events) act(() => socket.emit(event));
    act(() => socket.emit("not-json"));

    expect(client.getQueryData<{ items: unknown[] }>(["messages", "t"])?.items).toHaveLength(1);
    expect(client.getQueryData(["task", "t"])).toBeUndefined();
    client.setQueryData(["task", "t"], { id: "t", status: "queued" });
    act(() => socket.emit({ type: "status", status: "running", attention_reason: "approval_required" }));
    expect(client.getQueryData<{ status: string }>(["task", "t"])?.status).toBe("running");
    expect(client.getQueryData<{ items: unknown[] }>(["attempts", "t"])?.items).toHaveLength(1);
    expect(client.getQueryData<{ items: unknown[] }>(["task-events", "t"])?.items).toHaveLength(1);
    expect(client.getQueryData<{ items: Array<{ status: string }> }>(["invocations", "t"])?.items[0].status).toBe("done");
    expect(client.getQueryData<{ items: unknown[] }>(["tool-approvals", "t"])?.items).toHaveLength(1);
    expect(client.getQueryData<{ items: Array<{ status: string }> }>(["pr-delivery-runs", "t"])?.items[0].status).toBe("opened");
    expect(result.current.tokenUsage).toEqual({ used: 25, limit: 100 });
    expect(result.current.prSuggestion).toEqual({ eligibleFileCount: 3 });

    act(() => socket.onerror?.());
    expect(socket.close).toHaveBeenCalled();
    unmount();
    expect(socket.close).toHaveBeenCalled();
  });

  it("reconnects with backoff after an unexpected close", () => {
    vi.useFakeTimers();
    const client = new QueryClient();
    const { result, unmount } = renderHook(() => useTaskStream("t"), { wrapper: queryWrapper(client) });
    const first = MockSocket.instances[0];
    act(() => first.onclose?.({ code: 1006 }));
    expect(result.current.connection).toBe("offline");
    act(() => vi.advanceTimersByTime(1_000));
    expect(MockSocket.instances).toHaveLength(2);
    unmount();
    vi.useRealTimers();
  });
});

describe("useTerminalSession", () => {
  it("handles terminal protocol events and control operations", () => {
    const onOutput = vi.fn();
    const onGap = vi.fn();
    const { result, unmount } = renderHook(() => useTerminalSession("t", { onOutput, onGap }));
    const socket = MockSocket.instances[0];
    expect(socket.url).toBe("wss://api.example.test/ws/tasks/t/terminal");
    act(() => socket.onopen?.());
    expect(socket.send).toHaveBeenCalledWith(JSON.stringify({ type: "attach", cols: 120, rows: 32, after_seq: 0 }));
    act(() => socket.emit({ type: "ready", control: "granted", oldest_seq: 1, latest_seq: 1 }));
    expect(result.current.control).toBe("granted");
    act(() => socket.emit({ type: "output", seq: 32, data_b64: btoa("hello") }));
    expect(new TextDecoder().decode(onOutput.mock.calls[0][0])).toBe("hello");
    expect(socket.send).toHaveBeenCalledWith(JSON.stringify({ type: "ack", seq: 32 }));
    act(() => result.current.sendText("input"));
    expect(socket.send).toHaveBeenCalledWith(expect.stringContaining('"type":"input"'));
    act(() => result.current.resize(80, 24));
    expect(socket.send).toHaveBeenCalledWith(JSON.stringify({ type: "resize", cols: 80, rows: 24 }));
    act(() => result.current.takeControl());
    expect(socket.send).toHaveBeenCalledWith(JSON.stringify({ type: "take_control" }));
    act(() => socket.emit({ type: "control", state: "read_only" }));
    act(() => socket.emit({ type: "output", seq: 33, data_b64: btoa("!") }));
    act(() => result.current.sendText("ignored"));
    act(() => socket.emit({ type: "gap", oldest_seq: 10 }));
    expect(onGap).toHaveBeenCalled();
    act(() => socket.emit({ type: "error", code: "bad", message: "Denied" }));
    expect(result.current.error).toBe("Denied");
    act(() => socket.emit("broken"));
    expect(result.current.error).toBe("The terminal sent an invalid frame");
    act(() => socket.emit({ type: "exit", exit_code: 0, status: "done", archived: true }));
    expect(result.current.exit).toEqual({ code: 0, archived: true });
    act(() => socket.onclose?.({ code: 1000 }));
    expect(MockSocket.instances).toHaveLength(1);
    unmount();
  });

  it("handles queued exits, rejected sockets, and reconnects", () => {
    vi.useFakeTimers();
    const onGap = vi.fn();
    const { result, unmount } = renderHook(() => useTerminalSession("t", { onOutput: vi.fn(), onGap }));
    const first = MockSocket.instances[0];
    act(() => first.emit({ type: "exit", exit_code: null, status: "queued" }));
    expect(onGap).toHaveBeenCalled();
    act(() => first.onclose?.({ code: 1008 }));
    expect(result.current.error).toContain("rejected");

    unmount();
    const secondHook = renderHook(() => useTerminalSession("next", { onOutput: vi.fn(), onGap: vi.fn() }));
    const second = MockSocket.instances.at(-1)!;
    act(() => second.onclose?.({ code: 1006 }));
    act(() => vi.advanceTimersByTime(1_000));
    expect(MockSocket.instances.length).toBeGreaterThan(2);
    secondHook.unmount();
    vi.useRealTimers();
  });
});

describe("useTaskNotifications", () => {
  it("requests permission, displays status frames, and navigates on click", () => {
    const notifications: Array<{ onclick: (() => void) | null; close: ReturnType<typeof vi.fn> }> = [];
    class MockNotification {
      static permission: NotificationPermission = "default";
      static requestPermission = vi.fn().mockResolvedValue("granted");
      onclick: (() => void) | null = null;
      close = vi.fn();
      constructor(public title: string, public options?: NotificationOptions) {
        notifications.push(this);
      }
    }
    vi.stubGlobal("Notification", MockNotification);
    const { unmount } = renderHook(() => useTaskNotifications());
    expect(MockNotification.requestPermission).toHaveBeenCalled();
    MockNotification.permission = "granted";
    const socket = MockSocket.instances[0];
    act(() => socket.onopen?.());
    act(() => socket.emit({ type: "other" }));
    act(() => socket.emit("bad"));
    act(() => socket.emit({ type: "task_status", status: "running", task_title: "Build", task_id: "t", project_name: "Muster" }));
    act(() => socket.emit({ type: "task_status", status: "mystery", task_title: "Other", task_id: "u" }));
    expect(notifications).toHaveLength(2);
    expect((notifications[0] as unknown as { title: string }).title).toContain("Running");
    act(() => notifications[0].onclick?.());
    expect(push).toHaveBeenCalledWith("/tasks/t");
    expect(notifications[0].close).toHaveBeenCalled();
    act(() => socket.onerror?.());
    expect(socket.close).toHaveBeenCalled();
    unmount();
  });

  it("reconnects after close and skips notifications without permission", () => {
    vi.useFakeTimers();
    class DeniedNotification {
      static permission: NotificationPermission = "denied";
      static requestPermission = vi.fn();
    }
    vi.stubGlobal("Notification", DeniedNotification);
    const { unmount } = renderHook(() => useTaskNotifications());
    const socket = MockSocket.instances[0];
    act(() => socket.emit({ type: "task_status", status: "mystery", task_title: "T", task_id: "t" }));
    act(() => socket.onclose?.({ code: 1006 }));
    act(() => vi.advanceTimersByTime(1_000));
    expect(MockSocket.instances).toHaveLength(2);
    unmount();
    vi.useRealTimers();
  });
});
