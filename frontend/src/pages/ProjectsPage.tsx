import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { createProject, listProjects } from "../api/client";
import type { AgentBackend } from "../types";

export default function ProjectsPage() {
  const queryClient = useQueryClient();
  const [showArchived, setShowArchived] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [backend, setBackend] = useState<AgentBackend>("claude_code");

  const projectsQuery = useQuery({
    queryKey: ["projects", showArchived],
    queryFn: () => listProjects(showArchived),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createProject({
        name,
        description: description || undefined,
        default_backend: backend,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setName("");
      setDescription("");
      setShowForm(false);
    },
  });

  return (
    <div>
      <div className="page-header">
        <h1>Projects</h1>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={() => setShowArchived((v) => !v)}>
            {showArchived ? "Hide archived" : "Show archived"}
          </button>
          <button className="primary" onClick={() => setShowForm((v) => !v)}>
            New project
          </button>
        </div>
      </div>

      {showForm && (
        <form
          className="card"
          style={{ marginBottom: 16 }}
          onSubmit={(e) => {
            e.preventDefault();
            createMutation.mutate();
          }}
        >
          <div className="form-row">
            <input
              placeholder="Project name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
            <input
              placeholder="Description (optional)"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <select value={backend} onChange={(e) => setBackend(e.target.value as AgentBackend)}>
              <option value="claude_code">claude_code</option>
              <option value="codex">codex</option>
            </select>
            <button className="primary" type="submit" disabled={createMutation.isPending}>
              Create
            </button>
          </div>
          {createMutation.isError && (
            <div className="error-banner">{(createMutation.error as Error).message}</div>
          )}
        </form>
      )}

      {projectsQuery.isLoading && <div className="loading">Loading projects…</div>}
      {projectsQuery.isError && (
        <div className="error-banner">{(projectsQuery.error as Error).message}</div>
      )}
      {projectsQuery.data && (
        <div className="project-list">
          {projectsQuery.data.items.map((project) => (
            <Link key={project.id} to={`/projects/${project.id}`} className="project-card">
              <h3>{project.name}</h3>
              {project.description && <div className="muted">{project.description}</div>}
              <span className="badge">{project.default_backend}</span>
              {project.archived && <span className="badge">archived</span>}
            </Link>
          ))}
          {projectsQuery.data.items.length === 0 && (
            <div className="muted">No projects yet. Create one to get started.</div>
          )}
        </div>
      )}
    </div>
  );
}
