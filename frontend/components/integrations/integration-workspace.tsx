"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Bot, Clock3, Play, Plus, Sparkles } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { AgentBackend, CronJob } from "@/lib/types";
import { backendLabel, formatDateTime } from "@/lib/utils";

const units = { minutes: 1, hours: 60, days: 1440 } as const;
type Unit = keyof typeof units;

function frequency(job: CronJob): string {
  if (!job.interval_minutes) return `Custom schedule · ${job.schedule_expr}`;
  const minutes = job.interval_minutes;
  if (minutes % 1440 === 0) return `Every ${minutes / 1440} day${minutes === 1440 ? "" : "s"}`;
  if (minutes % 60 === 0) return `Every ${minutes / 60} hour${minutes === 60 ? "" : "s"}`;
  return `Every ${minutes} minute${minutes === 1 ? "" : "s"}`;
}

export function IntegrationWorkspace() {
  const queryClient = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const [projectId, setProjectId] = useState("");
  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("project");
    if (requested) setProjectId(requested);
  }, []);
  const selectedProject = projects.data?.items.find((project) => project.id === projectId);
  const jobs = useQuery({ queryKey: ["cron", projectId], queryFn: () => api.cronJobs(projectId), enabled: !!projectId });
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [backend, setBackend] = useState<AgentBackend>("codex");
  const [amount, setAmount] = useState(1);
  const [unit, setUnit] = useState<Unit>("hours");
  const [error, setError] = useState("");
  const [lastTaskId, setLastTaskId] = useState("");

  const create = useMutation({
    mutationFn: () => api.createCron(projectId, {
      name: name.trim(), prompt: prompt.trim(), backend,
      schedule_expr: "0 * * * *", interval_minutes: amount * units[unit],
    }),
    onSuccess: () => {
      setError(""); setName(""); setPrompt("");
      queryClient.invalidateQueries({ queryKey: ["cron", projectId] });
    },
    onError: (cause: Error) => setError(cause.message),
  });
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => api.toggleCron(projectId, id, enabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["cron", projectId] }),
    onError: (cause: Error) => setError(cause.message),
  });
  const run = useMutation({
    mutationFn: (id: string) => api.runCronNow(projectId, id),
    onSuccess: ({ task_id }) => { setError(""); setLastTaskId(task_id); queryClient.invalidateQueries({ queryKey: ["cron", projectId] }); },
    onError: (cause: Error) => setError(cause.message),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!projectId || !name.trim() || !prompt.trim() || !Number.isInteger(amount) || amount < 1 || amount * units[unit] > 525600) {
      setError("Choose a project, add a name and prompt, and set a frequency of up to one year.");
      return;
    }
    create.mutate();
  }

  return <main className="mx-auto max-w-5xl space-y-8 px-5 py-8 md:px-8">
    <header className="space-y-3">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-signal-400"><Sparkles className="h-4 w-4" /> Automation</div>
      <h1 className="text-3xl font-semibold tracking-tight text-white">Recurring agents</h1>
      <p className="max-w-2xl text-sm leading-6 text-slate-400">Describe the work once. Muster starts a fresh Codex or Claude CLI session at the interval you choose and places each run on the project board.</p>
    </header>

    <form onSubmit={submit} className="surface overflow-hidden rounded-panel border border-white/[0.08]">
      <div className="space-y-5 p-5 md:p-7">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-200"><Bot className="h-4 w-4 text-signal-400" /> What should this agent do?</div>
        <textarea aria-label="Agent prompt" className="field min-h-52 resize-y border-white/[0.08] bg-black/20 text-sm leading-6" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="For example: Review my assigned Jira issues and recent Slack requests using the available MCP connectors. Create or update project tasks for clear action items, then summarize what needs my attention." required />
        <p className="text-xs leading-5 text-slate-500">The agent receives this prompt on every run. It uses the selected project's directories, enabled tools, skills, and MCP connectors.</p>
      </div>
      <div className="grid gap-4 border-t border-white/[0.07] bg-white/[0.015] p-5 md:grid-cols-2 md:p-7">
        <label className="space-y-2 text-xs font-medium text-slate-400">Name<input className="field" value={name} onChange={(event) => setName(event.target.value)} placeholder="Issue and message triage" required maxLength={200} /></label>
        <label className="space-y-2 text-xs font-medium text-slate-400">Project<select className="field" value={projectId} onChange={(event) => setProjectId(event.target.value)} required><option value="">Choose a project</option>{projects.data?.items.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
        <label className="space-y-2 text-xs font-medium text-slate-400">Agent CLI<select className="field" value={backend} onChange={(event) => setBackend(event.target.value as AgentBackend)}><option value="codex">Codex</option><option value="claude_code">Claude Code</option></select></label>
        <div className="space-y-2 text-xs font-medium text-slate-400"><span>Run every</span><div className="flex gap-2"><input aria-label="Frequency" className="field min-w-0 flex-1" type="number" min={1} max={525600 / units[unit]} value={amount} onChange={(event) => setAmount(Number(event.target.value))} required /><select aria-label="Frequency unit" className="field w-36" value={unit} onChange={(event) => setUnit(event.target.value as Unit)}><option value="minutes">Minutes</option><option value="hours">Hours</option><option value="days">Days</option></select></div></div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.07] px-5 py-4 md:px-7">
        <span className="text-xs text-slate-500">{selectedProject ? selectedProject.primary_directory_id ? `Runs in ${selectedProject.name}` : "This project needs a primary directory before scheduling." : "Choose a project to use its capabilities."}</span>
        <Button type="submit" loading={create.isPending} disabled={!selectedProject?.primary_directory_id}><Plus className="h-4 w-4" /> Create recurring agent</Button>
      </div>
    </form>

    {error && <p role="alert" className="rounded-xl border border-red-400/20 bg-red-400/[0.06] p-3 text-sm text-red-300">{error}</p>}
    {lastTaskId && <Link href={`/tasks/${lastTaskId}`} className="inline-flex items-center gap-2 text-sm text-signal-300">Open new agent session <ArrowUpRight className="h-4 w-4" /></Link>}

    <section className="space-y-4">
      <div className="flex items-center gap-2"><Clock3 className="h-4 w-4 text-signal-400" /><h2 className="text-lg font-medium text-white">Scheduled for this project</h2></div>
      {!projectId ? <p className="text-sm text-slate-500">Choose a project to see its recurring agents.</p> : jobs.isPending ? <p className="text-sm text-slate-500">Loading agents…</p> : jobs.isError ? <p className="text-sm text-red-300">{jobs.error.message}</p> : !jobs.data.items.length ? <p className="text-sm text-slate-500">No recurring agents yet.</p> : <div className="space-y-3">{jobs.data.items.map((job) => <article key={job.id} className="surface rounded-xl p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="text-sm font-semibold text-white">{job.name}</h3><p className="mt-1 text-xs text-slate-500">{frequency(job)} · {backendLabel(job.backend)} · Last run {formatDateTime(job.last_run_at)}</p></div><div className="flex items-center gap-2"><Button size="sm" variant="ghost" disabled={!job.enabled} loading={run.isPending} onClick={() => run.mutate(job.id)}><Play className="h-3.5 w-3.5" /> Run now</Button><Button size="sm" variant="ghost" loading={toggle.isPending} onClick={() => toggle.mutate({ id: job.id, enabled: !job.enabled })}>{job.enabled ? "Pause" : "Resume"}</Button></div></div><p className="mt-3 line-clamp-3 whitespace-pre-wrap text-xs leading-5 text-slate-400">{job.prompt}</p></article>)}</div>}
    </section>
  </main>;
}
