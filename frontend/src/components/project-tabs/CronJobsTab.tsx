import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createCronJob,
  deleteCronJob,
  disableCronJob,
  enableCronJob,
  listCronJobs,
} from "../../api/client";
import type { AgentBackend } from "../../types";

export default function CronJobsTab({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [scheduleExpr, setScheduleExpr] = useState("");
  const [prompt, setPrompt] = useState("");
  const [backend, setBackend] = useState<AgentBackend>("claude_code");

  const query = useQuery({
    queryKey: ["cron-jobs", projectId],
    queryFn: () => listCronJobs(projectId),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["cron-jobs", projectId] });

  const createMutation = useMutation({
    mutationFn: () =>
      createCronJob(projectId, { name, schedule_expr: scheduleExpr, prompt, backend }),
    onSuccess: () => {
      setName("");
      setScheduleExpr("");
      setPrompt("");
      invalidate();
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ cronId, enable }: { cronId: string; enable: boolean }) =>
      enable ? enableCronJob(projectId, cronId) : disableCronJob(projectId, cronId),
    onSuccess: invalidate,
  });

  const deleteMutation = useMutation({
    mutationFn: (cronId: string) => deleteCronJob(projectId, cronId),
    onSuccess: invalidate,
  });

  return (
    <div>
      <div className="section-header">
        <h3>Cron jobs</h3>
      </div>
      <form
        className="form-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim() && scheduleExpr.trim() && prompt.trim()) createMutation.mutate();
        }}
      >
        <input placeholder="name" value={name} onChange={(e) => setName(e.target.value)} />
        <input
          placeholder="cron expr, e.g. */15 * * * *"
          value={scheduleExpr}
          onChange={(e) => setScheduleExpr(e.target.value)}
        />
        <select value={backend} onChange={(e) => setBackend(e.target.value as AgentBackend)}>
          <option value="claude_code">claude_code</option>
          <option value="codex">codex</option>
        </select>
        <input
          placeholder="prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          style={{ flex: 1 }}
        />
        <button className="primary" type="submit" disabled={createMutation.isPending}>
          Add
        </button>
      </form>

      {query.isLoading && <div className="loading">Loading…</div>}
      {query.data && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Schedule</th>
              <th>Backend</th>
              <th>Enabled</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {query.data.items.map((cron) => (
              <tr key={cron.id}>
                <td>{cron.name}</td>
                <td>
                  <code>{cron.schedule_expr}</code>
                </td>
                <td>{cron.backend}</td>
                <td>{cron.enabled ? "yes" : "no"}</td>
                <td style={{ display: "flex", gap: 6 }}>
                  <button
                    onClick={() =>
                      toggleMutation.mutate({ cronId: cron.id, enable: !cron.enabled })
                    }
                    disabled={toggleMutation.isPending}
                  >
                    {cron.enabled ? "Disable" : "Enable"}
                  </button>
                  <button
                    className="danger"
                    onClick={() => deleteMutation.mutate(cron.id)}
                    disabled={deleteMutation.isPending}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
            {query.data.items.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  No cron jobs configured.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
