"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Bot } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { AgentBackend } from "@/lib/types";
import { backendLabel, cn } from "@/lib/utils";

export function CreateProjectModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [backend, setBackend] = useState<AgentBackend>("claude_code");
  const [model, setModel] = useState("");
  const [error, setError] = useState("");
  const models = useQuery({ queryKey: ["models", backend], queryFn: () => api.models(backend), enabled: open, staleTime: 60 * 60 * 1000 });

  const create = useMutation({
    mutationFn: api.createProject,
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      toast(`${project.name} is ready`, "success");
      onClose();
      router.push(`/projects/${project.id}/board`);
    },
    onError: (cause: Error) => setError(cause.message),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const cleanName = name.trim();
    if (!cleanName) {
      setError("Give this project a name so it is easy to identify.");
      return;
    }
    setError("");
    create.mutate({
      name: cleanName,
      description: description.trim() || null,
      default_backend: backend,
      default_model: model.trim() || null,
      default_context_strategy: "full",
    });
  };

  return (
    <Modal open={open} onClose={onClose} title="Create a project" description="Define the default agent profile. Bindings can be added after creation.">
      <form onSubmit={submit} className="space-y-5">
        <div>
          <label className="label" htmlFor="project-name">Project name</label>
          <input id="project-name" className="field" value={name} onChange={(event) => setName(event.target.value)} autoComplete="off" autoFocus maxLength={200} />
        </div>
        <div>
          <label className="label" htmlFor="project-description">Purpose <span className="text-slate-600">— optional</span></label>
          <textarea id="project-description" className="field min-h-24 resize-y" value={description} onChange={(event) => setDescription(event.target.value)} maxLength={1000} />
        </div>
        <fieldset>
          <legend className="label">Default agent</legend>
          <div className="grid grid-cols-2 gap-3">
            {(["claude_code", "codex"] as AgentBackend[]).map((item) => (
              <button key={item} type="button" onClick={() => setBackend(item)} className={cn("rounded-xl border p-4 text-left transition", backend === item ? "border-signal-400/35 bg-signal-400/[0.07] shadow-glow" : "border-white/[0.08] bg-white/[0.025] hover:border-white/15")} aria-pressed={backend === item}>
                <Bot className={cn("h-4 w-4", backend === item ? "text-signal-400" : "text-slate-600")} />
                <span className="mt-3 block text-sm font-medium text-white">{backendLabel(item)}</span>
                <span className="mt-1 block text-[0.68rem] text-slate-600">Native CLI session</span>
              </button>
            ))}
          </div>
        </fieldset>
        <div>
          <label className="label">Preferred model <span className="text-slate-600">— optional</span></label>
          <Select label={models.isPending ? "Discovering models" : "Select a model"} value={model} onChange={setModel} options={[{ value: "", label: "Runtime default" }, ...(models.data?.items.map((item) => ({ value: item.id, label: item.label, description: item.id })) ?? [])]} />
        </div>
        {error && <p role="alert" className="rounded-xl border border-red-400/15 bg-red-400/[0.06] px-3 py-2.5 text-xs text-red-300">{error}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" loading={create.isPending}>Create project <ArrowRight className="h-4 w-4" /></Button>
        </div>
      </form>
    </Modal>
  );
}
