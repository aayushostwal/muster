import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cancelTask,
  compressTaskContext,
  getTask,
  getTranscript,
  listMessages,
  listRunAttempts,
  restartTask,
  retryTaskNow,
  sendMessage,
  switchTaskContextStrategy,
  switchTaskModel,
} from "../api/client";
import { useTaskSocket } from "../api/ws";
import ChatThread from "../components/ChatThread";
import Composer from "../components/Composer";
import type { MediaAttachment, TaskStatus } from "../types";

const MODEL_OPTIONS = ["default", "sonnet", "opus", "haiku"];
const CONTEXT_STRATEGIES = ["full_history", "rolling_summary", "compressed"];

function statusLabel(status: TaskStatus): string {
  return status.replace(/_/g, " ");
}

export default function TaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [showTranscript, setShowTranscript] = useState(false);

  const taskQuery = useQuery({
    queryKey: ["task", id],
    queryFn: () => getTask(id!),
    enabled: !!id,
  });

  const messagesQuery = useQuery({
    queryKey: ["messages", id],
    queryFn: () => listMessages(id!),
    enabled: !!id,
  });

  const runAttemptsQuery = useQuery({
    queryKey: ["run-attempts", id],
    queryFn: () => listRunAttempts(id!),
    enabled: !!id,
    refetchInterval: 5000,
  });

  const transcriptQuery = useQuery({
    queryKey: ["transcript", id],
    queryFn: () => getTranscript(id!),
    enabled: !!id && showTranscript,
  });

  const socketState = useTaskSocket(id, (event) => {
    if (event.type === "message") {
      queryClient.invalidateQueries({ queryKey: ["messages", id] });
    }
    if (event.type === "status") {
      queryClient.invalidateQueries({ queryKey: ["task", id] });
    }
    if (event.type === "run_attempt") {
      queryClient.invalidateQueries({ queryKey: ["run-attempts", id] });
    }
  });

  const sendMutation = useMutation({
    mutationFn: (payload: { content_text?: string; media?: MediaAttachment[] }) =>
      sendMessage(id!, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["messages", id] });
      queryClient.invalidateQueries({ queryKey: ["task", id] });
    },
  });

  const modelMutation = useMutation({
    mutationFn: (model: string) => switchTaskModel(id!, model),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["task", id] }),
  });

  const strategyMutation = useMutation({
    mutationFn: (strategy: string) => switchTaskContextStrategy(id!, strategy),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["task", id] }),
  });

  const compressMutation = useMutation({
    mutationFn: () => compressTaskContext(id!),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["messages", id] }),
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelTask(id!),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["task", id] }),
  });

  const restartMutation = useMutation({
    mutationFn: () => restartTask(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["task", id] });
      queryClient.invalidateQueries({ queryKey: ["messages", id] });
    },
  });

  const retryNowMutation = useMutation({
    mutationFn: () => retryTaskNow(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["task", id] });
      queryClient.invalidateQueries({ queryKey: ["run-attempts", id] });
    },
  });

  useEffect(() => {
    if (showTranscript) transcriptQuery.refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showTranscript]);

  const task = taskQuery.data;
  const status = socketState.status ?? task?.status;
  const tokenUsage = socketState.tokenUsage;

  const latestRunAttempt = useMemo(() => {
    const attempts = runAttemptsQuery.data?.items ?? [];
    if (attempts.length === 0) return socketState.lastRunAttempt;
    return attempts[attempts.length - 1];
  }, [runAttemptsQuery.data, socketState.lastRunAttempt]);

  const isBackoffWaiting =
    !!latestRunAttempt &&
    latestRunAttempt.failure_class === "transient" &&
    !!latestRunAttempt.retrying_at &&
    status === "running";

  if (!id) return null;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>{task?.title ?? "Task"}</h1>
          {task && (
            <Link to={`/projects/${task.project_id}/board`} className="muted">
              ← Back to board
            </Link>
          )}
        </div>
        {status && <span className={`status-pill ${status}`}>{statusLabel(status)}</span>}
      </div>

      {isBackoffWaiting && (
        <div className="warning-banner">
          <span>
            Run failed with a transient error and is retrying in the background
            {latestRunAttempt?.backoff_seconds != null
              ? ` (~${latestRunAttempt.backoff_seconds}s backoff)`
              : ""}
            .
          </span>
          <button
            className="primary"
            onClick={() => retryNowMutation.mutate()}
            disabled={retryNowMutation.isPending}
          >
            Retry now
          </button>
        </div>
      )}

      {task?.status === "failed" && (
        <div className="warning-banner">
          <span>This task's run failed.</span>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={() => retryNowMutation.mutate()} disabled={retryNowMutation.isPending}>
              Retry now
            </button>
            <button onClick={() => restartMutation.mutate()} disabled={restartMutation.isPending}>
              Restart
            </button>
          </div>
        </div>
      )}

      <div className="task-controls">
        <div className="control-group">
          Model:
          <select
            value={task?.model ?? ""}
            onChange={(e) => modelMutation.mutate(e.target.value)}
            disabled={!task || modelMutation.isPending}
          >
            <option value="">default</option>
            {MODEL_OPTIONS.filter((m) => m !== "default").map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
        <div className="control-group">
          Context strategy:
          <select
            value={task?.context_strategy ?? ""}
            onChange={(e) => strategyMutation.mutate(e.target.value)}
            disabled={!task || strategyMutation.isPending}
          >
            <option value="">default</option>
            {CONTEXT_STRATEGIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="control-group">
          Tokens:
          {tokenUsage ? (
            <>
              <div className="token-usage-bar">
                <div
                  className="token-usage-fill"
                  style={{
                    width: `${Math.min(100, (tokenUsage.used / Math.max(tokenUsage.limit, 1)) * 100)}%`,
                  }}
                />
              </div>
              <span>
                {tokenUsage.used.toLocaleString()} / {tokenUsage.limit.toLocaleString()}
              </span>
            </>
          ) : (
            <span className="muted">n/a</span>
          )}
        </div>
        <button onClick={() => compressMutation.mutate()} disabled={compressMutation.isPending}>
          Compress context
        </button>
        <button onClick={() => setShowTranscript((v) => !v)}>
          {showTranscript ? "Hide raw transcript" : "Show raw transcript"}
        </button>
        {status !== "done" && status !== "cancelled" && (
          <button
            className="danger"
            onClick={() => cancelMutation.mutate()}
            disabled={cancelMutation.isPending}
          >
            Cancel
          </button>
        )}
      </div>

      {messagesQuery.isLoading && <div className="loading">Loading messages…</div>}
      {messagesQuery.data && <ChatThread messages={messagesQuery.data.items} />}

      <Composer
        onSend={(payload) => sendMutation.mutate(payload)}
        disabled={sendMutation.isPending}
      />

      {showTranscript && (
        <div className="transcript-box">
          {transcriptQuery.isLoading && "Loading transcript…"}
          {transcriptQuery.data ?? ""}
        </div>
      )}
    </div>
  );
}
