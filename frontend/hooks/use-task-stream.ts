"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { apiBase } from "@/lib/api";
import type { ListResponse, Message, RunAttempt, Task, TaskEvent, TaskInvocation, TaskStreamEvent, ToolApproval } from "@/lib/types";

export function useTaskStream(taskId: string) {
  const queryClient = useQueryClient();
  const [connection, setConnection] = useState<"connecting" | "live" | "offline">("connecting");
  const [tokenUsage, setTokenUsage] = useState<{ used: number; limit: number } | null>(null);
  const reconnectAttempt = useRef(0);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let timer: number | undefined;
    let disposed = false;

    const connect = () => {
      setConnection("connecting");
      const url = new URL(apiBase());
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      url.pathname = `/ws/tasks/${taskId}`;
      url.search = "";
      socket = new WebSocket(url.toString());
      socket.onopen = () => {
        reconnectAttempt.current = 0;
        setConnection("live");
      };
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data as string) as TaskStreamEvent;
          if (event.type === "message") {
            queryClient.setQueryData<ListResponse<Message>>(["messages", taskId], (current) => {
              if (current?.items.some((item) => item.id === event.message.id)) return current;
              return { items: [...(current?.items ?? []), event.message] };
            });
          }
          if (event.type === "status") {
            queryClient.setQueryData<Task>(["task", taskId], (current) => current ? { ...current, status: event.status } : current);
          }
          if (event.type === "run_attempt") {
            queryClient.setQueryData<ListResponse<RunAttempt>>(["attempts", taskId], (current) => ({ items: [...(current?.items ?? []), event.attempt] }));
          }
          if (event.type === "activity") {
            queryClient.setQueryData<ListResponse<TaskEvent>>(["task-events", taskId], (current) => {
              if (current?.items.some((item) => item.id === event.event.id)) return current;
              return { items: [...(current?.items ?? []), event.event] };
            });
          }
          if (event.type === "invocation") {
            queryClient.setQueryData<ListResponse<TaskInvocation>>(["invocations", taskId], (current) => {
              const items = current?.items ?? [];
              const index = items.findIndex((item) => item.id === event.invocation.id);
              if (index < 0) return { items: [...items, event.invocation] };
              return { items: items.map((item) => item.id === event.invocation.id ? event.invocation : item) };
            });
          }
          if (event.type === "token_usage") setTokenUsage({ used: event.used, limit: event.limit });
          if (event.type === "tool_approval") {
            queryClient.setQueryData<ListResponse<ToolApproval>>(["tool-approvals", taskId], (current) => {
              const items = current?.items ?? [];
              if (items.some((item) => item.id === event.approval.id)) return current;
              return { items: [...items, event.approval] };
            });
          }
        } catch {
          // Ignore malformed frames and retain the live connection.
        }
      };
      socket.onclose = () => {
        if (disposed) return;
        setConnection("offline");
        const delay = Math.min(1_000 * 2 ** reconnectAttempt.current, 15_000);
        reconnectAttempt.current += 1;
        timer = window.setTimeout(connect, delay);
      };
      socket.onerror = () => socket?.close();
    };

    connect();
    return () => {
      disposed = true;
      if (timer) window.clearTimeout(timer);
      socket?.close();
    };
  }, [queryClient, taskId]);

  return { connection, tokenUsage };
}
