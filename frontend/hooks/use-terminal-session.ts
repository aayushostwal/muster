"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiBase } from "@/lib/api";

type TerminalEvent =
  | { type: "ready"; control: "granted" | "read_only"; oldest_seq: number; latest_seq: number }
  | { type: "output"; seq: number; data_b64: string }
  | { type: "control"; state: "granted" | "read_only" }
  | { type: "gap"; oldest_seq: number }
  | { type: "exit"; exit_code: number | null; status: string; archived?: boolean }
  | { type: "error"; code: string; message: string };

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}

function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

export function useTerminalSession(
  taskId: string,
  handlers: { onOutput: (data: Uint8Array) => void; onGap: () => void },
) {
  const handlersRef = useRef(handlers);
  useEffect(() => {
    handlersRef.current = handlers;
  }, [handlers]);
  const socketRef = useRef<WebSocket | null>(null);
  const disposedRef = useRef(false);
  const reconnectRef = useRef(0);
  const lastSeqRef = useRef(0);
  const sizeRef = useRef({ cols: 120, rows: 32 });
  const controlRef = useRef<"granted" | "read_only">("read_only");
  const exitedRef = useRef(false);
  const [connection, setConnection] = useState<"connecting" | "live" | "offline">("connecting");
  const [control, setControl] = useState<"granted" | "read_only">("read_only");
  const [exit, setExit] = useState<{ code: number | null; archived: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    disposedRef.current = false;
    exitedRef.current = false;
    lastSeqRef.current = 0;
    let timer: number | undefined;

    const connect = () => {
      setConnection("connecting");
      const url = new URL(apiBase());
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      url.pathname = `/ws/tasks/${taskId}/terminal`;
      url.search = "";
      const socket = new WebSocket(url.toString());
      socketRef.current = socket;
      socket.onopen = () => {
        reconnectRef.current = 0;
        setConnection("live");
        socket.send(JSON.stringify({ type: "attach", ...sizeRef.current, after_seq: lastSeqRef.current }));
      };
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data as string) as TerminalEvent;
          if (event.type === "ready") {
            controlRef.current = event.control;
            setControl(event.control);
            setError(null);
          } else if (event.type === "output") {
            lastSeqRef.current = Math.max(lastSeqRef.current, event.seq);
            handlersRef.current.onOutput(base64ToBytes(event.data_b64));
            if (event.seq % 32 === 0) socket.send(JSON.stringify({ type: "ack", seq: event.seq }));
          } else if (event.type === "control") {
            controlRef.current = event.state;
            setControl(event.state);
          } else if (event.type === "gap") {
            lastSeqRef.current = event.oldest_seq - 1;
            handlersRef.current.onGap();
          } else if (event.type === "exit") {
            controlRef.current = "read_only";
            setControl("read_only");
            if (event.status === "queued") {
              lastSeqRef.current = 0;
              handlersRef.current.onGap();
              socket.close();
            } else {
              exitedRef.current = true;
              setExit({ code: event.exit_code, archived: Boolean(event.archived) });
            }
          } else if (event.type === "error") {
            setError(event.message);
          }
        } catch {
          setError("The terminal sent an invalid frame");
        }
      };
      socket.onerror = () => socket.close();
      socket.onclose = () => {
        if (socketRef.current === socket) socketRef.current = null;
        if (disposedRef.current || exitedRef.current) return;
        setConnection("offline");
        const delay = Math.min(1_000 * 2 ** reconnectRef.current, 15_000);
        reconnectRef.current += 1;
        timer = window.setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      disposedRef.current = true;
      if (timer) window.clearTimeout(timer);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [taskId]);

  const sendBytes = useCallback((bytes: Uint8Array) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN || controlRef.current !== "granted") return;
    socket.send(JSON.stringify({ type: "input", data_b64: bytesToBase64(bytes) }));
  }, []);

  const sendText = useCallback((value: string) => sendBytes(new TextEncoder().encode(value)), [sendBytes]);

  const resize = useCallback((cols: number, rows: number) => {
    sizeRef.current = { cols, rows };
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "resize", cols, rows }));
    }
  }, []);

  const takeControl = useCallback(() => {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "take_control" }));
  }, []);

  return { connection, control, exit, error, sendBytes, sendText, resize, takeControl };
}
