import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createDirectory, deleteDirectory, listDirectories } from "../../api/client";
import type { AccessScope } from "../../types";

export default function DirectoriesTab({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [path, setPath] = useState("");
  const [scope, setScope] = useState<AccessScope>("read_write");

  const query = useQuery({
    queryKey: ["directories", projectId],
    queryFn: () => listDirectories(projectId),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["directories", projectId] });

  const createMutation = useMutation({
    mutationFn: () => createDirectory(projectId, { path, access_scope: scope }),
    onSuccess: () => {
      setPath("");
      invalidate();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (bindingId: string) => deleteDirectory(projectId, bindingId),
    onSuccess: invalidate,
  });

  return (
    <div>
      <div className="section-header">
        <h3>Bound directories</h3>
      </div>
      <form
        className="form-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (path.trim()) createMutation.mutate();
        }}
      >
        <input
          placeholder="/absolute/path"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          style={{ flex: 1 }}
        />
        <select value={scope} onChange={(e) => setScope(e.target.value as AccessScope)}>
          <option value="read">read</option>
          <option value="read_write">read_write</option>
        </select>
        <button className="primary" type="submit" disabled={createMutation.isPending}>
          Add
        </button>
      </form>

      {query.isLoading && <div className="loading">Loading…</div>}
      {query.data && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Path</th>
              <th>Access</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {query.data.items.map((binding) => (
              <tr key={binding.id}>
                <td>{binding.path}</td>
                <td>{binding.access_scope}</td>
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
                  No directories bound.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
