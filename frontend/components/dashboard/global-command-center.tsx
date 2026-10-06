"use client";

import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, ArrowUpRight, CheckCircle2, CircleDot, Clock3, FolderKanban, LoaderCircle, Search, Sparkles, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Select } from "@/components/ui/select";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { TASK_TAG_COLORS } from "@/lib/task-tags";
import { taskNeedsAttention, taskStage, type TaskStage } from "@/lib/task-status";
import type { Project, Task } from "@/lib/types";
import { backendLabel, cn, formatRelativeTime, shortId } from "@/lib/utils";

export function GlobalCommandCenter() {
  const [query, setQuery] = useState("");
  const [projectFilter, setProjectFilter] = useState("all");
  const [backendFilter, setBackendFilter] = useState("all");
  const searchRef = useRef<HTMLInputElement>(null);
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const tasks = useQuery({ queryKey: ["tasks", "global"], queryFn: api.allTasks, refetchInterval: 5_000 });

  useEffect(() => {
    const focus = () => searchRef.current?.focus();
    window.addEventListener("muster:focus-search", focus);
    return () => window.removeEventListener("muster:focus-search", focus);
  }, []);

  const projectById = useMemo(
    () => new Map((projects.data?.items ?? []).map((project) => [project.id, project])),
    [projects.data],
  );
  const allTasks = useMemo(() => tasks.data?.items ?? [], [tasks.data]);
  const filteredTasks = useMemo(() => {
    const value = query.trim().toLowerCase();
    return allTasks.filter((task) => {
      const project = projectById.get(task.project_id);
      const matchesQuery = !value || task.title.toLowerCase().includes(value) ||
        task.initial_prompt.toLowerCase().includes(value) ||
        task.tags.some((tag) => tag.toLowerCase().includes(value)) ||
        project?.name.toLowerCase().includes(value);
      return matchesQuery &&
        (projectFilter === "all" || task.project_id === projectFilter) &&
        (backendFilter === "all" || task.backend === backendFilter);
    });
  }, [allTasks, backendFilter, projectById, projectFilter, query]);

  const priorityTasks = useMemo(() => filteredTasks
    .filter((task) => taskNeedsAttention(task) || task.status === "running")
    .sort((left, right) => {
      const priority = Number(taskNeedsAttention(right)) - Number(taskNeedsAttention(left));
      return priority || new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime();
    }), [filteredTasks]);
  const queued = filteredTasks.filter((task) => task.status === "queued");
  const globalAttention = allTasks.filter(taskNeedsAttention).length;
  const globalRunning = allTasks.filter((task) => task.status === "running").length;
  const globalQueued = allTasks.filter((task) => task.status === "queued").length;
  const hasFilters = Boolean(query || projectFilter !== "all" || backendFilter !== "all");
  const error = projects.error ?? tasks.error;
  const projectOptions = [
    { value: "all", label: "All projects" },
    ...(projects.data?.items ?? []).map((project) => ({ value: project.id, label: project.name })),
  ];

  if (error) {
    return <div className="mx-auto max-w-screen-2xl px-5 py-8 md:px-8"><ErrorState message={error.message} retry={() => void Promise.all([projects.refetch(), tasks.refetch()])} /></div>;
  }

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-4 sm:px-6 md:py-6 xl:px-8">
      <header className="flex flex-col gap-4 border-b border-white/[0.08] pb-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="flex items-center gap-2"><span className="relative flex h-2 w-2" aria-hidden="true"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-signal-400 opacity-40" /><span className="relative inline-flex h-2 w-2 rounded-full bg-signal-400" /></span><p className="eyebrow">Live operations</p></div>
          <h1 className="mt-1.5 text-2xl font-semibold tracking-[-0.035em] text-white">Command center</h1>
          <p className="mt-1 text-xs text-slate-400">Running work and decisions that need you, across every project.</p>
        </div>
        <Link href="/projects" className="inline-flex h-9 items-center justify-center gap-2 self-start rounded-lg border border-white/10 bg-white/[0.045] px-3 text-xs font-medium text-slate-300 transition hover:border-white/20 hover:bg-white/[0.08] hover:text-white sm:self-auto"><FolderKanban className="h-3.5 w-3.5 text-signal-400" /> Projects</Link>
      </header>

      <section className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border border-white/[0.08] bg-white/[0.035] px-3 py-2.5" aria-label="Workspace summary">
        <SummaryItem label="Running" value={globalRunning} icon={<LoaderCircle className={cn("h-3.5 w-3.5 text-signal-400", globalRunning > 0 && "animate-spin [animation-duration:3s]")} />} />
        <SummaryItem label="Needs attention" value={globalAttention} icon={<AlertTriangle className="h-3.5 w-3.5 text-amber-300" />} />
        <SummaryItem label="Queued" value={globalQueued} icon={<Clock3 className="h-3.5 w-3.5 text-sky-300" />} />
        <span className="hidden h-5 w-px bg-white/[0.08] sm:block" />
        <span className="text-[0.65rem] text-slate-500">{projects.data?.items.length ?? 0} active projects</span>
      </section>

      <section className="mt-3 flex flex-col gap-2 rounded-xl border border-white/[0.07] bg-black/10 p-2 sm:flex-row" aria-label="Task filters">
        <div className="relative min-w-0 flex-1"><Search className="pointer-events-none absolute left-3 top-2.5 h-3.5 w-3.5 text-slate-500" /><input ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} className="field h-9 rounded-lg py-2 pl-9 text-xs" placeholder="Search active tasks" aria-label="Search active tasks" /></div>
        <Select className="sm:w-48" label="Filter by project" value={projectFilter} onChange={setProjectFilter} options={projectOptions} />
        <Select className="sm:w-40" label="Filter by runtime" value={backendFilter} onChange={setBackendFilter} options={[{ value: "all", label: "All runtimes" }, { value: "claude_code", label: "Claude Code" }, { value: "codex", label: "Codex" }]} />
      </section>

      {projects.isPending || tasks.isPending ? <DashboardSkeleton /> : (
        <main className="mt-5">
          <div className="flex items-end justify-between gap-4">
            <div><div className="flex items-center gap-2"><h2 className="text-base font-semibold text-white">Priority work</h2><span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 font-mono text-[0.62rem] text-slate-400">{priorityTasks.length}</span></div><p className="mt-1 text-[0.68rem] text-slate-500">Attention items first, followed by live agent runs.</p></div>
          </div>

          {priorityTasks.length > 0 ? (
            <div className="mt-3 grid gap-2.5 md:grid-cols-2 2xl:grid-cols-3">
              <AnimatePresence mode="popLayout">{priorityTasks.map((task) => <PriorityTaskCard key={task.id} task={task} project={projectById.get(task.project_id)} />)}</AnimatePresence>
            </div>
          ) : (
            <div className="mt-3 flex min-h-28 items-center gap-3 rounded-xl border border-dashed border-signal-400/20 bg-signal-400/[0.035] px-5 text-sm text-slate-400"><CheckCircle2 className="h-5 w-5 shrink-0 text-signal-400" />{hasFilters ? "No priority work matches these filters." : "All clear. No agents are running or waiting for your attention."}</div>
          )}

          <QueuePanel tasks={queued} projectById={projectById} filtered={hasFilters} />
        </main>
      )}
    </div>
  );
}

function SummaryItem({ label, value, icon }: { label: string; value: number; icon: ReactNode }) {
  return <div className="flex items-center gap-2">{icon}<span className="font-mono text-sm font-semibold tabular-nums text-white">{value}</span><span className="text-[0.65rem] font-medium uppercase tracking-[0.09em] text-slate-500">{label}</span></div>;
}

function PriorityTaskCard({ task, project }: { task: Task; project?: Project }) {
  const stage = taskStage(task);
  const config = statusConfig[stage];
  const attention = taskNeedsAttention(task);
  const action = stage === "ready_for_review" ? "Review" : task.status === "failed" ? "Inspect" : attention ? "Respond" : "Open live";
  return (
    <motion.article layout initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.98 }} className={cn("group relative min-w-0 overflow-hidden rounded-xl border bg-ink-850/90 transition hover:bg-ink-800/90", config.border)}>
      {task.status === "running" && <motion.span className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-signal-400 to-transparent" animate={{ x: ["-65%", "65%"] }} transition={{ duration: 2.6, repeat: Infinity, ease: "easeInOut" }} />}
      <Link href={`/tasks/${task.id}`} className="block p-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-signal-400/40">
        <div className="flex min-w-0 items-center gap-2"><StatusBadge task={task} /><span className="min-w-0 flex-1 truncate text-[0.62rem] font-medium text-slate-400">{project?.name ?? "Unknown project"}</span><span className="font-mono text-[0.54rem] text-slate-600">#{shortId(task.id)}</span></div>
        <h3 className="mt-2.5 truncate text-sm font-semibold text-slate-100 transition group-hover:text-white">{task.title}</h3>
        <p className="mt-1 line-clamp-1 text-[0.66rem] leading-4 text-slate-500">{task.initial_prompt}</p>
        <div className="mt-2.5 flex min-w-0 items-center gap-1.5">
          <span className="max-w-28 truncate rounded-md border border-white/[0.07] bg-white/[0.03] px-1.5 py-0.5 text-[0.54rem] text-slate-400">{backendLabel(task.backend)}</span>
          <span className="max-w-32 truncate rounded-md border border-white/[0.07] bg-white/[0.03] px-1.5 py-0.5 text-[0.54rem] text-slate-500">{task.model || "Default model"}</span>
          <TaskTags tags={task.tags} />
        </div>
        <div className="mt-2.5 flex items-center justify-between gap-3 border-t border-white/[0.06] pt-2.5"><span className="truncate font-mono text-[0.58rem] text-slate-500">{task.status === "running" ? "Started" : "Updated"} {formatRelativeTime(task.status === "running" ? task.started_at || task.created_at : task.updated_at)}</span><span className={cn("inline-flex shrink-0 items-center gap-1 text-[0.62rem] font-semibold", config.tone)}>{action}<ArrowUpRight className="h-3 w-3" /></span></div>
      </Link>
    </motion.article>
  );
}

const statusConfig: Record<TaskStage, { label: string; classes: string; border: string; tone: string; icon: ReactNode }> = {
  running: { label: "Running", classes: "border-signal-400/20 bg-signal-400/[0.09] text-signal-300", border: "border-signal-400/20", tone: "text-signal-300", icon: <CircleDot className="h-3 w-3 animate-pulse" /> },
  waiting_on_you: { label: "Needs input", classes: "border-amber-400/20 bg-amber-400/[0.09] text-amber-300", border: "border-amber-400/20", tone: "text-amber-300", icon: <AlertTriangle className="h-3 w-3" /> },
  ready_for_review: { label: "Ready for review", classes: "border-violet-400/20 bg-violet-400/[0.09] text-violet-300", border: "border-violet-400/20", tone: "text-violet-300", icon: <CheckCircle2 className="h-3 w-3" /> },
  failed: { label: "Failed", classes: "border-red-400/20 bg-red-400/[0.09] text-red-300", border: "border-red-400/20", tone: "text-red-300", icon: <XCircle className="h-3 w-3" /> },
  queued: { label: "Queued", classes: "border-sky-400/20 bg-sky-400/[0.09] text-sky-300", border: "border-sky-400/20", tone: "text-sky-300", icon: <Clock3 className="h-3 w-3" /> },
  done: { label: "Complete", classes: "border-emerald-400/20 bg-emerald-400/[0.09] text-emerald-300", border: "border-emerald-400/20", tone: "text-emerald-300", icon: <CheckCircle2 className="h-3 w-3" /> },
  cancelled: { label: "Cancelled", classes: "border-white/10 bg-white/[0.05] text-slate-400", border: "border-white/10", tone: "text-slate-400", icon: <XCircle className="h-3 w-3" /> },
};

function StatusBadge({ task }: { task: Task }) {
  const item = statusConfig[taskStage(task)];
  return <span className={cn("inline-flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-0.5 text-[0.56rem] font-semibold", item.classes)}>{item.icon}{item.label}</span>;
}

function TaskTags({ tags }: { tags: string[] }) {
  if (!tags.length) return null;
  return <div className="flex min-w-0 items-center gap-1 overflow-hidden">{tags.slice(0, 2).map((tag) => <span key={tag} className={cn("max-w-24 truncate rounded-md border px-1.5 py-0.5 text-[0.52rem] font-medium", TASK_TAG_COLORS[tag] ?? "border-white/10 bg-white/[0.04] text-slate-400")}>{tag}</span>)}{tags.length > 2 && <span className="text-[0.52rem] text-slate-600">+{tags.length - 2}</span>}</div>;
}

function QueuePanel({ tasks, projectById, filtered }: { tasks: Task[]; projectById: Map<string, Project>; filtered: boolean }) {
  return <section className="mt-5 border-t border-white/[0.07] pt-4" aria-label="Queued tasks"><div className="flex items-center gap-2"><Clock3 className="h-3.5 w-3.5 text-sky-300" /><h2 className="text-xs font-semibold uppercase tracking-[0.1em] text-slate-400">Up next</h2><span className="font-mono text-[0.6rem] text-slate-600">{tasks.length}</span></div>{tasks.length === 0 ? <p className="mt-2 text-xs text-slate-600">{filtered ? "No queued tasks match these filters." : "The queue is clear."}</p> : <div className="mt-2 grid gap-2 md:grid-cols-2 xl:grid-cols-3">{tasks.slice(0, 6).map((task, index) => <Link key={task.id} href={`/tasks/${task.id}`} className="group flex min-w-0 items-center gap-2.5 rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2 transition hover:border-sky-400/20 hover:bg-white/[0.05]"><span className="font-mono text-[0.58rem] text-sky-300/70">{String(index + 1).padStart(2, "0")}</span><span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium text-slate-300 group-hover:text-white">{task.title}</span><span className="mt-0.5 block truncate text-[0.56rem] text-slate-600">{projectById.get(task.project_id)?.name ?? "Unknown project"} · {backendLabel(task.backend)}</span></span><ArrowUpRight className="h-3 w-3 text-slate-600" /></Link>)}</div>}</section>;
}

function DashboardSkeleton() {
  return <div className="mt-5"><Skeleton className="h-6 w-40" /><div className="mt-3 grid gap-2.5 md:grid-cols-2 2xl:grid-cols-3">{Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="h-40" />)}</div><div className="mt-5 flex items-center gap-2 text-xs text-slate-600"><Sparkles className="h-3.5 w-3.5" />Loading priority work</div></div>;
}
