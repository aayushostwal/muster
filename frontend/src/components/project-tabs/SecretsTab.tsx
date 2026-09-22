import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteSecret, listSecrets, upsertSecret } from "../../api/client";

export default function SecretsTab({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [keyName, setKeyName] = useState("");
  const [value, setValue] = useState("");

  const query = useQuery({
    queryKey: ["secrets", projectId],
    queryFn: () => listSecrets(projectId),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["secrets", projectId] });

  const upsertMutation = useMutation({
    mutationFn: () => upsertSecret(projectId, keyName, value),
    onSuccess: () => {
      setKeyName("");
      setValue("");
      invalidate();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (key: string) => deleteSecret(projectId, key),
    onSuccess: invalidate,
  });

  return (
    <div>
      <div className="section-header">
        <h3>Secrets</h3>
      </div>
      <p className="muted">Values are encrypted at rest and never returned by the API.</p>
      <form
        className="form-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (keyName.trim() && value.trim()) upsertMutation.mutate();
        }}
      >
        <input
          placeholder="KEY_NAME"
          value={keyName}
          onChange={(e) => setKeyName(e.target.value)}
        />
        <input
          placeholder="value"
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          style={{ flex: 1 }}
        />
        <button className="primary" type="submit" disabled={upsertMutation.isPending}>
          Save
        </button>
      </form>

      {query.isLoading && <div className="loading">Loading…</div>}
      {query.data && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Key</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {query.data.items.map((secret) => (
              <tr key={secret.key_name}>
                <td>{secret.key_name}</td>
                <td>
                  <button
                    className="danger"
                    onClick={() => deleteMutation.mutate(secret.key_name)}
                    disabled={deleteMutation.isPending}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
            {query.data.items.length === 0 && (
              <tr>
                <td colSpan={2} className="muted">
                  No secrets set.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
