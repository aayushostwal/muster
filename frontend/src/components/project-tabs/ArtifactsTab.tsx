import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createArtifact, deleteArtifact, listArtifacts } from "../../api/client";

export default function ArtifactsTab({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [remoteUrl, setRemoteUrl] = useState("");

  const query = useQuery({
    queryKey: ["artifacts", projectId],
    queryFn: () => listArtifacts(projectId),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["artifacts", projectId] });

  const createMutation = useMutation({
    mutationFn: () =>
      createArtifact(projectId, {
        name,
        local_path: localPath,
        remote_url: remoteUrl || undefined,
      }),
    onSuccess: () => {
      setName("");
      setLocalPath("");
      setRemoteUrl("");
      invalidate();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (artifactId: string) => deleteArtifact(projectId, artifactId),
    onSuccess: invalidate,
  });

  return (
    <div>
      <div className="section-header">
        <h3>Artifacts</h3>
      </div>
      <form
        className="form-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim() && localPath.trim()) createMutation.mutate();
        }}
      >
        <input placeholder="name" value={name} onChange={(e) => setName(e.target.value)} />
        <input
          placeholder="local path"
          value={localPath}
          onChange={(e) => setLocalPath(e.target.value)}
        />
        <input
          placeholder="remote url (optional)"
          value={remoteUrl}
          onChange={(e) => setRemoteUrl(e.target.value)}
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
              <th>Local path</th>
              <th>Remote URL</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {query.data.items.map((artifact) => (
              <tr key={artifact.id}>
                <td>{artifact.name}</td>
                <td>{artifact.local_path}</td>
                <td>
                  {artifact.remote_url ? (
                    <a href={artifact.remote_url} target="_blank" rel="noreferrer">
                      link
                    </a>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td>
                  <button
                    className="danger"
                    onClick={() => deleteMutation.mutate(artifact.id)}
                    disabled={deleteMutation.isPending}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
            {query.data.items.length === 0 && (
              <tr>
                <td colSpan={4} className="muted">
                  No artifacts recorded.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
