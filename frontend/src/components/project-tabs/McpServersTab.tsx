import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createMcpServer, deleteMcpServer, listMcpServers } from "../../api/client";

export default function McpServersTab({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");

  const query = useQuery({
    queryKey: ["mcp-servers", projectId],
    queryFn: () => listMcpServers(projectId),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["mcp-servers", projectId] });

  const createMutation = useMutation({
    mutationFn: () =>
      createMcpServer(projectId, {
        name,
        config: {
          command,
          args: args
            .split(" ")
            .map((a) => a.trim())
            .filter(Boolean),
          env: {},
        },
      }),
    onSuccess: () => {
      setName("");
      setCommand("");
      setArgs("");
      invalidate();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (bindingId: string) => deleteMcpServer(projectId, bindingId),
    onSuccess: invalidate,
  });

  return (
    <div>
      <div className="section-header">
        <h3>MCP servers</h3>
      </div>
      <form
        className="form-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim() && command.trim()) createMutation.mutate();
        }}
      >
        <input placeholder="name" value={name} onChange={(e) => setName(e.target.value)} />
        <input
          placeholder="command"
          value={command}
          onChange={(e) => setCommand(e.target.value)}
        />
        <input
          placeholder="args (space separated)"
          value={args}
          onChange={(e) => setArgs(e.target.value)}
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
              <th>Command</th>
              <th>Args</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {query.data.items.map((binding) => (
              <tr key={binding.id}>
                <td>{binding.name}</td>
                <td>{binding.config.command}</td>
                <td>{binding.config.args?.join(" ")}</td>
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
                <td colSpan={4} className="muted">
                  No MCP servers configured.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
