"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { apiBase } from "@/lib/api";
import type { TaskStatusEvent } from "@/lib/types";

const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  waiting_on_you: "Waiting on you",
  done: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

/**
 * Subscribes to the global `/ws/events` feed and surfaces a browser
 * Notification whenever any task's status changes, regardless of whether
 * that task's terminal view is currently open. Clicking the notification
 * focuses the window and opens that task's terminal view.
 *
 * Mount once near the app root (see AppShell) — this is not per-task.
 */
export function useTaskNotifications() {
  const router = useRouter();
  const routerRef = useRef(router);

  useEffect(() => {
    routerRef.current = router;
  }, [router]);

  useEffect(() => {
    if (typeof window === "undefined" || !("Notification" in window)) return;

    if (Notification.permission === "default") {
      void Notification.requestPermission();
    }

    let socket: WebSocket | null = null;
    let timer: number | undefined;
    let disposed = false;
    let reconnectAttempt = 0;

    const connect = () => {
      const url = new URL(apiBase());
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      url.pathname = "/ws/events";
      url.search = "";
      socket = new WebSocket(url.toString());

      socket.onopen = () => {
        reconnectAttempt = 0;
      };

      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data as string) as TaskStatusEvent;
          if (event.type !== "task_status") return;
          if (Notification.permission !== "granted") return;

          const label = STATUS_LABELS[event.status] ?? event.status;
          const notification = new Notification(`${event.task_title} — ${label}`, {
            body: event.project_name ? `Project: ${event.project_name}` : undefined,
            tag: `muster-task-${event.task_id}`,
          });
          notification.onclick = () => {
            window.focus();
            routerRef.current.push(`/tasks/${event.task_id}`);
            notification.close();
          };
        } catch {
          // Ignore malformed frames and retain the live connection.
        }
      };

      socket.onclose = () => {
        if (disposed) return;
        const delay = Math.min(1_000 * 2 ** reconnectAttempt, 15_000);
        reconnectAttempt += 1;
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
  }, []);
}
