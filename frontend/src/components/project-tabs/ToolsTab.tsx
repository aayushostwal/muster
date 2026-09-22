import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createTool, deleteTool, listTools } from "../../api/client";

export default function ToolsTab({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [configText, setConfigText] = useState("{}");
  const [configError, setConfigError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["tools", projectId],
    queryFn: () => listTools(projectId),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["tools", projectId] });

  const createMutation = useMutation({
    mutationFn: () => createTool(projectId, { name, config: JSON.parse(configText || "{}") }),
    onSuccess: () => {
      setName("");
      setConfigText("{}");
      invalidate();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (bindingId: string) => deleteTool(projectId, bindingId),
    onSuccess: invalidate,
  });

  return (
    <div>
      <div className="section-header">
        <h3>Tools</h3>
      </div>
      <form
        className="form-row"
        onSubmit={(e) => {
          e.preventDefault();
          try {
            JSON.parse(configText || "{}");
            setConfigError(null);
          } catch {
            setConfigError("Config must be valid JSON");
            return;
          }
          if (name.trim()) createMutation.mutate();
        }}
      >
        <input placeholder="name" value={name} onChange={(e) => setName(e.target.value)} />
        <input
          placeholder='config JSON, e.g. {"key": "value"}'
          value={configText}
          onChange={(e) => setConfigText(e.target.value)}
          style={{ flex: 1 }}
        />
        <button className="primary" type="submit" disabled={createMutation.isPending}>
          Add
        </button>
      </form>
      {configError && <div className="error-banner">{configError}</div>}

      {query.isLoading && <div className="loading">Loading…</div>}
      {query.data && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Config</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {query.data.items.map((binding) => (
              <tr key={binding.id}>
                <td>{binding.name}</td>
                <td>
                  <code>{JSON.stringify(binding.config)}</code>
                </td>
                <td>
                  <button
                    className="danger"
                    onClick={() => deleteMutation.mutate(binding.id)}
                    disabled={deleteMutation.isPending}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
            {query.data.items.length === 0 && (
              <tr>
                <td colSpan={3} className="muted">
                  No tools configured.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
