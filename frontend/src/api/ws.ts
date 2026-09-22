import { useEffect, useRef, useState } from "react";
import { BASE_URL } from "./client";
import type { Message, TaskRunAttempt, TaskStatus, TokenUsage } from "../types";

export type TaskSocketEvent =
  | { type: "message"; message: Message }
  | { type: "status"; status: TaskStatus }
  | { type: "run_attempt"; attempt: TaskRunAttempt }
  | { type: "token_usage"; used: number; limit: number };

export type TaskSocketListener = (event: TaskSocketEvent) => void;

function wsUrlForTask(taskId: string): string {
  const httpUrl = new URL(BASE_URL);
  const protocol = httpUrl.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${httpUrl.host}/ws/tasks/${taskId}`;
}

/** Minimal WS client for /ws/tasks/{id}. Parses newline-delimited JSON events. */
export class TaskSocket {
  private ws: WebSocket | null = null;
  private listeners = new Set<TaskSocketListener>();
  private taskId: string;
  private shouldReconnect = true;
  private reconnectDelay = 1000;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(taskId: string) {
    this.taskId = taskId;
  }

  connect() {
    this.shouldReconnect = true;
    this.open();
  }

  private open() {
    const ws = new WebSocket(wsUrlForTask(this.taskId));
    this.ws = ws;

    ws.onmessage = (event) => {
      const raw = typeof event.data === "string" ? event.data : "";
      // Server sends one JSON object per message (or per line); handle both.
      for (const line of raw.split("\n")) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          const parsed = JSON.parse(trimmed) as TaskSocketEvent;
          this.emit(parsed);
        } catch {
          // ignore malformed event
        }
      }
    };

    ws.onclose = () => {
      if (this.shouldReconnect) {
        this.reconnectTimer = setTimeout(() => this.open(), this.reconnectDelay);
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, 15000);
      }
    };

    ws.onopen = () => {
      this.reconnectDelay = 1000;
    };
  }

  private emit(event: TaskSocketEvent) {
    for (const listener of this.listeners) listener(event);
  }

  subscribe(listener: TaskSocketListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  close() {
    this.shouldReconnect = false;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }
}

export interface UseTaskSocketState {
  status: TaskStatus | null;
  tokenUsage: TokenUsage | null;
  lastMessage: Message | null;
  lastRunAttempt: TaskRunAttempt | null;
}

/**
 * Hook that opens a WS connection to /ws/tasks/{taskId} and exposes the
 * latest state plus a raw event subscription for components that need every
 * event (e.g. appending messages to a list).
 */
export function useTaskSocket(
  taskId: string | undefined,
  onEvent?: TaskSocketListener,
): UseTaskSocketState {
  const [state, setState] = useState<UseTaskSocketState>({
    status: null,
    tokenUsage: null,
    lastMessage: null,
    lastRunAttempt: null,
  });
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!taskId) return;
    const socket = new TaskSocket(taskId);
    const unsubscribe = socket.subscribe((event) => {
      onEventRef.current?.(event);
      setState((prev) => {
        switch (event.type) {
          case "message":
            return { ...prev, lastMessage: event.message };
          case "status":
            return { ...prev, status: event.status };
          case "run_attempt":
            return { ...prev, lastRunAttempt: event.attempt };
          case "token_usage":
            return { ...prev, tokenUsage: { used: event.used, limit: event.limit } };
          default:
            return prev;
        }
      });
    });
    socket.connect();
    return () => {
      unsubscribe();
      socket.close();
    };
  }, [taskId]);

  return state;
}
