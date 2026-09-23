"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Bot } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { MultiSelect, Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { TASK_TAG_OPTIONS } from "@/lib/task-tags";
import type { AgentBackend } from "@/lib/types";
import { backendLabel, cn } from "@/lib/utils";

export function CreateTaskModal({ projectId, open, onClose }: { projectId: string; open: boolean; onClose: () => void }) {
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api.project(projectId), enabled: open });
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [backend, setBackend] = useState<AgentBackend | "inherit">("inherit");
  const [models, setModels] = useState<string[]>([]);
  const [thinking, setThinking] = useState("medium");
  const [tags, setTags] = useState<string[]>([]);
  const [agentId, setAgentId] = useState("");
  const [error, setError] = useState("");
  const agents = useQuery({ queryKey: ["registry", "agents"], queryFn: api.agents, enabled: open });
  const agentAccess = useQuery({ queryKey: ["capabilities", projectId, "agent"], queryFn: () => api.capabilities(projectId, "agent"), enabled: open });
  const effectiveBackend = backend === "inherit" ? (project.data?.default_backend ?? "claude_code") : backend;
  const modelCatalog = useQuery({ queryKey: ["models", effectiveBackend], queryFn: () => api.models(effectiveBackend), enabled: open, staleTime: 60 * 60 * 1000 });
  const router = useRouter(); const queryClient = useQueryClient(); const toast = useToast();
  const refreshModels = useMutation({
    mutationFn: () => api.models(effectiveBackend, true),
    onSuccess: (catalog) => queryClient.setQueryData(["models", effectiveBackend], catalog),
    onError: (cause: Error) => toast(cause.message, "error"),
  });
  const enabledAgentIds = new Set(agentAccess.data?.items.filter((item) => item.enabled).map((item) => item.resource_id));
  const create = useMutation({
    mutationFn: () => api.createTask(projectId, { title: title.trim(), initial_prompt: prompt.trim(), backend: backend === "inherit" ? undefined : backend, model: models[0], fallback_models: models.slice(1), tags, thinking_level: thinking, agent_id: agentId || undefined }),
    onSuccess: (task) => { queryClient.invalidateQueries({ queryKey: ["tasks", projectId] }); toast("Task queued and agent started", "success"); onClose(); router.push(`/tasks/${task.id}`); },
    onError: (cause: Error) => setError(cause.message),
  });
  const submit = (event: FormEvent) => { event.preventDefault(); if (!title.trim() || !prompt.trim()) return setError("Title and execution brief are required."); setError(""); create.mutate(); };
  return (
    <Modal open={open} onClose={onClose} title="Launch a task" description="Creating the task starts the selected agent immediately." wide>
      <form onSubmit={submit} className="space-y-5">
        <div><label className="label" htmlFor="task-title">Task title</label><input id="task-title" className="field" value={title} onChange={(event) => setTitle(event.target.value)} autoFocus maxLength={300} /></div>
        <div><div className="mb-2 flex items-center justify-between"><label className="text-xs font-medium text-slate-300" htmlFor="task-prompt">Execution brief</label><span className="font-mono text-[0.62rem] text-slate-700">{prompt.length} characters</span></div><textarea id="task-prompt" className="field min-h-40 resize-y leading-6" value={prompt} onChange={(event) => setPrompt(event.target.value)} /></div>
        <fieldset><legend className="label">Agent backend</legend><div className="grid gap-2 sm:grid-cols-3">{(["inherit", "claude_code", "codex"] as const).map((item) => <button key={item} type="button" onClick={() => setBackend(item)} aria-pressed={backend === item} className={cn("rounded-xl border p-3 text-left transition", backend === item ? "border-signal-400/30 bg-signal-400/[0.07]" : "border-white/[0.08] bg-white/[0.02] hover:border-white/15")}><Bot className={cn("h-4 w-4", backend === item ? "text-signal-400" : "text-slate-600")} /><span className="mt-2 block text-xs font-medium text-slate-200">{item === "inherit" ? "Project default" : backendLabel(item)}</span>{item === "inherit" && <span className="mt-1 block text-[0.62rem] text-slate-600">{project.data ? backendLabel(project.data.default_backend) : "Loading"}</span>}</button>)}</div></fieldset>
        <div className="grid gap-4 sm:grid-cols-2"><div><label className="label">Agent profile <span className="text-slate-600">— optional</span></label><Select label="Use project default" value={agentId} onChange={(value) => { setAgentId(value); const agent = agents.data?.items.find((item) => item.id === value); if (agent) { setBackend(agent.backend); setThinking(agent.thinking_level); setModels(agent.model ? [agent.model] : []); } }} options={[{ value: "", label: "Project default" }, ...(agents.data?.items.filter((item) => item.enabled && enabledAgentIds.has(item.id)).map((item) => ({ value: item.id, label: item.name, description: backendLabel(item.backend) })) ?? [])]} /></div><div><label className="label">Thinking level</label><Select label="Thinking level" value={thinking} onChange={setThinking} options={["low", "medium", "high", "xhigh", "max"].map((value) => ({ value, label: value[0].toUpperCase() + value.slice(1) }))} /></div></div>
        <div><label className="label">Workflow tags <span className="text-slate-600">— optional</span></label><MultiSelect label="Add task tags" values={tags} onChange={setTags} options={[...TASK_TAG_OPTIONS]} /></div>
        <div><div className="mb-2 flex items-center justify-between"><label className="text-xs font-medium text-slate-300">Model chain <span className="text-slate-600">— primary, then fallbacks</span></label><button type="button" onClick={() => refreshModels.mutate()} disabled={refreshModels.isPending} className="text-[0.65rem] text-signal-400 disabled:opacity-50">{refreshModels.isPending ? "Refreshing…" : "Refresh from CLI"}</button></div><MultiSelect label={modelCatalog.isPending ? "Discovering models" : "Select models"} values={models} onChange={setModels} options={(modelCatalog.data?.items ?? []).map((item) => ({ value: item.id, label: item.label, description: item.id }))} disabled={modelCatalog.isPending} /></div>
        {error && <p role="alert" className="rounded-xl border border-red-400/15 bg-red-400/[0.05] px-3 py-2.5 text-xs text-red-300">{error}</p>}
        <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" variant="primary" loading={create.isPending}>Launch task <ArrowRight className="h-4 w-4" /></Button></div>
      </form>
    </Modal>
  );
}
