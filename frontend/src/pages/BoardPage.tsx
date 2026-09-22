import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createTask, getProject, listTasks } from "../api/client";
import type { AgentBackend, Task, TaskStatus } from "../types";

const COLUMNS: { status: TaskStatus; label: string }[] = [
  { status: "queued", label: "Queued" },
  { status: "running", label: "Running" },
  { status: "waiting_on_you", label: "Waiting on You" },
  { status: "done", label: "Done" },
  { status: "failed", label: "Failed" },
  { status: "cancelled", label: "Cancelled" },
];

export default function BoardPage() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [backend, setBackend] = useState<AgentBackend>("claude_code");

  const projectQuery = useQuery({
    queryKey: ["project", id],
    queryFn: () => getProject(id!),
    enabled: !!id,
  });

  const tasksQuery = useQuery({
    queryKey: ["tasks", id],
    queryFn: () => listTasks(id!),
    enabled: !!id,
    refetchInterval: 5000,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createTask(id!, { title, initial_prompt: prompt, backend }),
    onSuccess: () => {
      setTitle("");
      setPrompt("");
      setShowForm(false);
      queryClient.invalidateQueries({ queryKey: ["tasks", id] });
    },
  });

  if (!id) return null;

  const tasksByStatus: Record<TaskStatus, Task[]> = {
    queued: [],
    running: [],
    waiting_on_you: [],
    done: [],
    failed: [],
    cancelled: [],
  };
  for (const task of tasksQuery.data?.items ?? []) {
    tasksByStatus[task.status]?.push(task);
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>{projectQuery.data?.name ?? "Board"}</h1>
          <Link to={`/projects/${id}`} className="muted">
            ← Back to project
          </Link>
        </div>
        <button className="primary" onClick={() => setShowForm((v) => !v)}>
          New task
        </button>
      </div>

      {showForm && (
        <form
          className="card"
          style={{ marginBottom: 16 }}
          onSubmit={(e) => {
            e.preventDefault();
            if (title.trim() && prompt.trim()) createMutation.mutate();
          }}
        >
          <div className="form-row">
            <input
              placeholder="Task title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
            <select value={backend} onChange={(e) => setBackend(e.target.value as AgentBackend)}>
              <option value="claude_code">claude_code</option>
              <option value="codex">codex</option>
            </select>
          </div>
          <div className="form-row">
            <textarea
              placeholder="Initial prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              style={{ flex: 1, minHeight: 60 }}
              required
            />
          </div>
          <button className="primary" type="submit" disabled={createMutation.isPending}>
            Create task
          </button>
          {createMutation.isError && (
            <div className="error-banner">{(createMutation.error as Error).message}</div>
          )}
        </form>
      )}

      {tasksQuery.isLoading && <div className="loading">Loading tasks…</div>}
      {tasksQuery.isError && (
        <div className="error-banner">{(tasksQuery.error as Error).message}</div>
      )}

      <div className="board">
        {COLUMNS.map((col) => (
          <div className="board-column" key={col.status}>
            <div className="board-column-header">
              <span>{col.label}</span>
              <span>{tasksByStatus[col.status].length}</span>
            </div>
            {tasksByStatus[col.status].map((task) => (
              <Link key={task.id} to={`/tasks/${task.id}`} className="task-card">
                <div className="task-title">{task.title}</div>
                <div className="task-meta">
                  {task.backend}
                  {task.model ? ` · ${task.model}` : ""}
                </div>
              </Link>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
