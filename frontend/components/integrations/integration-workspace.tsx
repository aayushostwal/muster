"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Bot, Clock3, Pencil, Play, Plus, Sparkles } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { AgentBackend, CronJob } from "@/lib/types";
import { backendLabel, formatDateTime } from "@/lib/utils";

const units = { minutes: 1, hours: 60, days: 1440 } as const;
type Unit = keyof typeof units;
const thinkingLevels: CronJob["thinking_level"][] = ["low", "medium", "high", "xhigh", "max"];
const fieldHeight = "h-12 min-h-12 py-0";

function intervalParts(minutes: number): { amount: number; unit: Unit } {
  if (minutes % 1440 === 0) return { amount: minutes / 1440, unit: "days" };
  if (minutes % 60 === 0) return { amount: minutes / 60, unit: "hours" };
  return { amount: minutes, unit: "minutes" };
}

function frequency(job: CronJob): string {
  if (!job.interval_minutes) return `Custom schedule · ${job.schedule_expr}`;
  const { amount, unit } = intervalParts(job.interval_minutes);
  return `Every ${amount} ${amount === 1 ? unit.slice(0, -1) : unit}`;
}

export function IntegrationWorkspace() {
  const composer = useRef<HTMLFormElement>(null);
  const queryClient = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const [projectId, setProjectId] = useState("");
  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("project");
    if (!requested) return;
    const frame = window.requestAnimationFrame(() => setProjectId(requested));
    return () => window.cancelAnimationFrame(frame);
  }, []);
  const selectedProject = projects.data?.items.find((project) => project.id === projectId);
  const jobs = useQuery({ queryKey: ["cron-all"], queryFn: api.allCronJobs });
  const [filterProjectId, setFilterProjectId] = useState("");
  const visibleJobs = (jobs.data?.items ?? []).filter((job) => !filterProjectId || job.project_id === filterProjectId);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [backend, setBackend] = useState<AgentBackend>("codex");
  const [model, setModel] = useState("");
  const [thinking, setThinking] = useState<CronJob["thinking_level"]>("medium");
  const [amount, setAmount] = useState(1);
  const [unit, setUnit] = useState<Unit>("hours");
  const [legacySchedule, setLegacySchedule] = useState<string | null>(null);
  const [windowEnabled, setWindowEnabled] = useState(false);
  const [windowStart, setWindowStart] = useState("11:00");
  const [windowEnd, setWindowEnd] = useState("21:00");
  const [timezone, setTimezone] = useState("Asia/Kolkata");
  const [error, setError] = useState("");
  const [lastTaskId, setLastTaskId] = useState("");
  const catalog = useQuery({ queryKey: ["models", backend], queryFn: () => api.models(backend), staleTime: 60 * 60 * 1000 });
  const catalogItems = catalog.data?.items ?? [];
  const modelOptions = model && !catalogItems.some((item) => item.id === model)
    ? [{ id: model, label: model }, ...catalogItems]
    : catalogItems;

  function resetEditor() {
    setEditingId(null); setName(""); setPrompt(""); setModel(""); setThinking("medium");
    setAmount(1); setUnit("hours"); setLegacySchedule(null); setError("");
    setWindowEnabled(false); setWindowStart("11:00"); setWindowEnd("21:00"); setTimezone("Asia/Kolkata");
  }

  function edit(job: CronJob) {
    setProjectId(job.project_id);
    setEditingId(job.id); setName(job.name); setPrompt(job.prompt); setBackend(job.backend);
    setModel(job.model ?? ""); setThinking(job.thinking_level);
    setWindowEnabled(!!job.window_start); setWindowStart(job.window_start ?? "11:00");
    setWindowEnd(job.window_end ?? "21:00"); setTimezone(job.timezone ?? "Asia/Kolkata");
    if (job.interval_minutes) {
      const interval = intervalParts(job.interval_minutes);
      setAmount(interval.amount); setUnit(interval.unit); setLegacySchedule(null);
    } else {
      setLegacySchedule(job.schedule_expr);
    }
    setError("");
    composer.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const save = useMutation({
    mutationFn: () => {
      const values = { name: name.trim(), prompt: prompt.trim(), backend, model: model || null, thinking_level: thinking,
        timezone: timezone.trim(), window_start: windowEnabled ? windowStart : null, window_end: windowEnabled ? windowEnd : null };
      if (editingId) return api.updateCron(projectId, editingId, {
        ...values, ...(legacySchedule ? {} : { interval_minutes: amount * units[unit] }),
      });
      return api.createCron(projectId, {
        ...values, schedule_expr: "0 * * * *", interval_minutes: amount * units[unit],
      });
    },
    onSuccess: () => {
      resetEditor();
      queryClient.invalidateQueries({ queryKey: ["cron-all"] });
    },
    onError: (cause: Error) => setError(cause.message),
  });
  const toggle = useMutation({
    mutationFn: ({ projectId: jobProjectId, id, enabled }: { projectId: string; id: string; enabled: boolean }) => api.toggleCron(jobProjectId, id, enabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["cron-all"] }),
    onError: (cause: Error) => setError(cause.message),
  });
  const run = useMutation({
    mutationFn: ({ projectId: jobProjectId, id }: { projectId: string; id: string }) => api.runCronNow(jobProjectId, id),
    onSuccess: ({ task_id }) => { setError(""); setLastTaskId(task_id); queryClient.invalidateQueries({ queryKey: ["cron-all"] }); },
    onError: (cause: Error) => setError(cause.message),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!projectId || !name.trim() || !prompt.trim() || (!legacySchedule && (!Number.isInteger(amount) || amount < 1 || amount * units[unit] > 525600))) {
      setError("Choose a project, add a name and prompt, and set a frequency of up to one year.");
      return;
    }
    if (windowEnabled && (!windowStart || !windowEnd || windowStart === windowEnd)) {
      setError("Choose different window start and end times.");
      return;
    }
    save.mutate();
  }

  return <main className="mx-auto max-w-5xl space-y-8 px-5 py-8 md:px-8">
    <header className="space-y-3">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-signal-400"><Sparkles className="h-4 w-4" /> Automation</div>
      <h1 className="text-3xl font-semibold tracking-tight text-white">Recurring agents</h1>
      <p className="max-w-2xl text-sm leading-6 text-slate-400">Describe the work once. Muster starts a fresh Codex or Claude CLI session at the interval you choose and places each run on the project board.</p>
    </header>

    <form ref={composer} onSubmit={submit} className="surface scroll-mt-20 overflow-hidden rounded-panel border border-white/[0.08]">
      <div className="space-y-5 p-5 md:p-7">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-200"><Bot className="h-4 w-4 text-signal-400" /> {editingId ? "Edit this agent’s instructions" : "What should this agent do?"}</div>
        <textarea aria-label="Agent prompt" className="field min-h-52 resize-y border-white/[0.08] bg-black/20 text-sm leading-6" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="For example: Review my assigned Jira issues and recent Slack requests using the available MCP connectors. Create or update project tasks for clear action items, then summarize what needs my attention." required />
        <p className="text-xs leading-5 text-slate-500">The agent receives this prompt on every run. It uses the selected project’s directories, enabled tools, skills, and MCP connectors.</p>
      </div>
      <div className="grid gap-x-6 gap-y-5 border-t border-white/[0.07] bg-white/[0.015] p-5 sm:grid-cols-2 md:p-7">
        <label className="block min-w-0 text-xs font-medium text-slate-400"><span className="mb-2 block">Name</span><input className={`field ${fieldHeight}`} value={name} onChange={(event) => setName(event.target.value)} placeholder="Issue and message triage" required maxLength={200} /></label>
        <label className="block min-w-0 text-xs font-medium text-slate-400"><span className="mb-2 block">Project</span><select className={`field ${fieldHeight}`} value={projectId} onChange={(event) => setProjectId(event.target.value)} disabled={!!editingId} required><option value="">Choose a project</option>{projects.data?.items.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
        <label className="block min-w-0 text-xs font-medium text-slate-400"><span className="mb-2 block">Agent CLI</span><select className={`field ${fieldHeight}`} value={backend} onChange={(event) => { setBackend(event.target.value as AgentBackend); setModel(""); }}><option value="codex">Codex</option><option value="claude_code">Claude Code</option></select></label>
        <label className="block min-w-0 text-xs font-medium text-slate-400"><span className="mb-2 block">Model</span><select className={`field ${fieldHeight}`} value={model} onChange={(event) => setModel(event.target.value)}><option value="">Runtime default</option>{modelOptions.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select>{catalog.isError && <span className="mt-1 block text-[0.68rem] text-amber-300">Model discovery unavailable; saved model is still selectable.</span>}</label>
        <label className="block min-w-0 text-xs font-medium text-slate-400"><span className="mb-2 block">Thinking level</span><select className={`field ${fieldHeight}`} value={thinking} onChange={(event) => setThinking(event.target.value as CronJob["thinking_level"])}>{thinkingLevels.map((level) => <option key={level} value={level}>{level[0].toUpperCase() + level.slice(1)}</option>)}</select></label>
        <div className="min-w-0 text-xs font-medium text-slate-400"><span className="mb-2 block">Run every</span>{legacySchedule ? <div className="flex min-h-12 items-center justify-between gap-3 rounded-xl border border-white/10 px-3.5"><span className="truncate text-sm text-slate-300">Current: {legacySchedule}</span><button type="button" className="shrink-0 text-signal-300" onClick={() => setLegacySchedule(null)}>Use interval</button></div> : <div className="grid grid-cols-[minmax(0,1fr)_minmax(7rem,9rem)] gap-2"><input aria-label="Frequency" className={`field min-w-0 ${fieldHeight}`} type="number" min={1} max={Math.floor(525600 / units[unit])} value={amount} onChange={(event) => setAmount(Number(event.target.value))} required /><select aria-label="Frequency unit" className={`field min-w-0 ${fieldHeight}`} value={unit} onChange={(event) => setUnit(event.target.value as Unit)}><option value="minutes">Minutes</option><option value="hours">Hours</option><option value="days">Days</option></select></div>}</div>
      </div>
      <div className="space-y-4 border-t border-white/[0.07] px-5 py-5 md:px-7">
        <label className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={windowEnabled} onChange={(event) => setWindowEnabled(event.target.checked)} />Limit to a daily run window</label>
        <div className="grid gap-4 sm:grid-cols-3">
          {windowEnabled && <><label className="text-xs text-slate-400">Window start<input type="time" className={`field mt-2 ${fieldHeight}`} value={windowStart} onChange={(event) => setWindowStart(event.target.value)} required /></label><label className="text-xs text-slate-400">Window end<input type="time" className={`field mt-2 ${fieldHeight}`} value={windowEnd} onChange={(event) => setWindowEnd(event.target.value)} required /></label></>}
          <label className="text-xs text-slate-400">Timezone<input className={`field mt-2 ${fieldHeight}`} value={timezone} onChange={(event) => setTimezone(event.target.value)} placeholder="Asia/Kolkata" required /></label>
        </div>
        {windowEnabled && <p className="text-xs leading-5 text-slate-500">Intervals restart at the window opening each day. No scheduled runs start at or after the closing time. Overnight windows are supported. Run now bypasses the window.</p>}
        <p className="text-xs leading-5 text-slate-500">The terminal closes after the recurring turn finishes. Its output stays available for review.</p>
      </div>
      <div className="flex flex-col gap-4 border-t border-white/[0.07] px-5 py-4 sm:flex-row sm:items-center sm:justify-between md:px-7">
        <span className="text-xs leading-5 text-slate-500">{selectedProject ? selectedProject.primary_directory_id ? `Runs in ${selectedProject.name}` : "This project needs a primary directory before scheduling." : "Choose a project to use its capabilities."}</span>
        <div className="flex items-center gap-2 self-end sm:self-auto">{editingId && <Button type="button" variant="ghost" onClick={resetEditor}>Cancel</Button>}<Button type="submit" loading={save.isPending} disabled={!selectedProject?.primary_directory_id}>{editingId ? <Pencil className="h-4 w-4" /> : <Plus className="h-4 w-4" />}{editingId ? "Save changes" : "Create recurring agent"}</Button></div>
      </div>
    </form>

    {error && <p role="alert" className="rounded-xl border border-red-400/20 bg-red-400/[0.06] p-3 text-sm text-red-300">{error}</p>}
    {lastTaskId && <Link href={`/tasks/${lastTaskId}`} className="inline-flex items-center gap-2 text-sm text-signal-300">Open new agent session <ArrowUpRight className="h-4 w-4" /></Link>}

    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2"><Clock3 className="h-4 w-4 text-signal-400" /><h2 className="text-lg font-medium text-white">Scheduled agents</h2></div>
        <select aria-label="Filter scheduled agents by project" className="field w-full sm:w-48" value={filterProjectId} onChange={(event) => setFilterProjectId(event.target.value)}><option value="">All projects</option>{projects.data?.items.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select>
      </div>
      {jobs.isPending ? <p className="text-sm text-slate-500">Loading agents…</p> : jobs.isError ? <p className="text-sm text-red-300">{jobs.error.message}</p> : !jobs.data.items.length ? <p className="text-sm text-slate-500">No recurring agents yet.</p> : !visibleJobs.length ? <p className="text-sm text-slate-500">No recurring agents in this project.</p> : <div className="space-y-3">{visibleJobs.map((job) => <article key={job.id} className="surface rounded-xl p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0"><div className="flex items-center gap-2"><h3 className="truncate text-sm font-semibold text-white">{job.name}</h3>{!job.enabled && <span className="rounded-md border border-amber-400/20 bg-amber-400/[0.06] px-1.5 py-0.5 text-[0.65rem] text-amber-300">Paused</span>}</div><p className="mt-1 text-xs leading-5 text-slate-500">{projects.data?.items.find((project) => project.id === job.project_id)?.name || "Project"} · {frequency(job)} · {backendLabel(job.backend)} · {job.model || "Runtime default"} · {job.thinking_level} thinking</p><p className="text-xs text-slate-600">Last run {formatDateTime(job.last_run_at)}</p></div>
          <div className="flex flex-wrap items-center gap-2"><Button size="sm" variant="ghost" onClick={() => edit(job)}><Pencil className="h-3.5 w-3.5" /> Edit</Button><Button size="sm" variant="ghost" loading={run.isPending} onClick={() => run.mutate({ projectId: job.project_id, id: job.id })}><Play className="h-3.5 w-3.5" /> Run now</Button><Button size="sm" variant="ghost" loading={toggle.isPending} onClick={() => toggle.mutate({ projectId: job.project_id, id: job.id, enabled: !job.enabled })}>{job.enabled ? "Pause" : "Resume"}</Button></div>
        </div>
        {job.window_start && <p className="mt-2 text-xs text-slate-400">Daily window {job.window_start}–{job.window_end} · {job.timezone}</p>}
        <p className="mt-3 line-clamp-3 whitespace-pre-wrap text-xs leading-5 text-slate-400">{job.prompt}</p>
      </article>)}</div>}
    </section>
  </main>;
}
