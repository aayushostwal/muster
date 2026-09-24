"use client";

import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CircleDot,
  Clock3,
  FolderKanban,
  Layers3,
  LoaderCircle,
  Search,
  Sparkles,
  TimerReset,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Select } from "@/components/ui/select";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { TASK_TAG_COLORS } from "@/lib/task-tags";
import type { Project, Task, TaskStatus } from "@/lib/types";
import { backendLabel, cn, formatRelativeTime, shortId } from "@/lib/utils";

const ATTENTION_STATUSES: TaskStatus[] = ["waiting_on_you", "failed"];

export function GlobalCommandCenter() {
  const [query, setQuery] = useState("");
  const [projectFilter, setProjectFilter] = useState("all");
  const [backendFilter, setBackendFilter] = useState("all");
  const searchRef = useRef<HTMLInputElement>(null);

  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: api.projects,
  });
  const tasks = useQuery({
    queryKey: ["tasks", "global"],
    queryFn: api.allTasks,
    refetchInterval: 5_000,
  });

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
      const matchesQuery =
        !value ||
        task.title.toLowerCase().includes(value) ||
        task.initial_prompt.toLowerCase().includes(value) ||
        task.tags.some((tag) => tag.toLowerCase().includes(value)) ||
        project?.name.toLowerCase().includes(value);
      return (
        matchesQuery &&
        (projectFilter === "all" || task.project_id === projectFilter) &&
        (backendFilter === "all" || task.backend === backendFilter)
      );
    });
  }, [allTasks, backendFilter, projectById, projectFilter, query]);

  const attention = filteredTasks.filter((task) => ATTENTION_STATUSES.includes(task.status));
  const running = filteredTasks.filter((task) => task.status === "running");
  const queued = filteredTasks.filter((task) => task.status === "queued");
  const recent = filteredTasks
    .filter((task) => task.status === "done" || task.status === "cancelled")
    .slice(0, 6);
  const globalAttention = allTasks.filter((task) => ATTENTION_STATUSES.includes(task.status)).length;
  const globalRunning = allTasks.filter((task) => task.status === "running").length;
  const globalQueued = allTasks.filter((task) => task.status === "queued").length;
  const hasFilters = Boolean(query || projectFilter !== "all" || backendFilter !== "all");
  const isPending = projects.isPending || tasks.isPending;
  const error = projects.error ?? tasks.error;

  const projectOptions = [
    { value: "all", label: "All projects" },
    ...(projects.data?.items ?? []).map((project) => ({ value: project.id, label: project.name })),
  ];

  if (error) {
    return (
      <div className="mx-auto max-w-screen-2xl px-5 py-8 md:px-8">
        <ErrorState message={error.message} retry={() => void Promise.all([projects.refetch(), tasks.refetch()])} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-5 sm:px-6 md:py-7 xl:px-8">
      <header className="flex flex-col gap-5 border-b border-white/[0.07] pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2" aria-hidden="true">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-signal-400 opacity-40" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-signal-400" />
            </span>
            <p className="eyebrow">Live operations</p>
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-[-0.035em] text-white md:text-3xl">Command center</h1>
          <p className="mt-1.5 text-sm text-slate-500">Every active agent run and decision point, across your workspace.</p>
        </div>
        <Link href="/projects" className="inline-flex h-10 items-center justify-center gap-2 self-start rounded-xl border border-white/10 bg-white/[0.04] px-4 text-sm font-medium text-slate-300 transition hover:border-white/20 hover:bg-white/[0.07] hover:text-white lg:self-auto">
          <FolderKanban className="h-4 w-4 text-signal-400" /> Manage projects
        </Link>
      </header>

      <section className="mt-5 grid overflow-hidden rounded-panel border border-white/[0.08] bg-white/[0.025] sm:grid-cols-2 xl:grid-cols-4" aria-label="Workspace summary">
        <Metric label="Running now" value={globalRunning} icon={<LoaderCircle className={cn("h-4 w-4 text-signal-400", globalRunning > 0 && "animate-spin [animation-duration:3s]")} />} tone="signal" />
        <Metric label="Needs attention" value={globalAttention} icon={<AlertTriangle className="h-4 w-4 text-amber-300" />} tone="warning" />
        <Metric label="Queued" value={globalQueued} icon={<Clock3 className="h-4 w-4 text-sky-300" />} tone="info" />
        <Metric label="Active projects" value={projects.data?.items.length ?? 0} icon={<Layers3 className="h-4 w-4 text-pulse-400" />} tone="pulse" />
      </section>

      <section className="mt-5 flex flex-col gap-3 rounded-2xl border border-white/[0.07] bg-black/10 p-3 lg:flex-row" aria-label="Task filters">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3.5 top-3.5 h-4 w-4 text-slate-600" />
          <input ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} className="field h-11 pl-10" placeholder="Search tasks, prompts, projects or tags" aria-label="Search all tasks" />
        </div>
        <Select className="lg:w-56" label="Filter by project" value={projectFilter} onChange={setProjectFilter} options={projectOptions} />
        <Select className="lg:w-48" label="Filter by runtime" value={backendFilter} onChange={setBackendFilter} options={[{ value: "all", label: "All runtimes" }, { value: "claude_code", label: "Claude Code" }, { value: "codex", label: "Codex" }]} />
      </section>

      {isPending ? (
        <DashboardSkeleton />
      ) : (
        <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.65fr)_minmax(19rem,0.75fr)]">
          <main className="min-w-0 space-y-7">
            <TaskSection
              eyebrow="Act now"
              title="Needs your attention"
              count={attention.length}
              description="Blocked runs and failed executions awaiting a decision."
              empty={hasFilters ? "No attention items match these filters." : "Nothing is blocked. Your agents can keep moving."}
              emptyTone="success"
            >
              <div className="grid gap-3 lg:grid-cols-2">
                <AnimatePresence mode="popLayout">
                  {attention.map((task) => <AttentionCard key={task.id} task={task} project={projectById.get(task.project_id)} />)}
                </AnimatePresence>
              </div>
            </TaskSection>

            <TaskSection
              eyebrow="In flight"
              title="Running now"
              count={running.length}
              description="Live work currently consuming an agent runtime."
              empty={hasFilters ? "No running tasks match these filters." : "No agents are running right now."}
            >
              <div className="grid gap-3 md:grid-cols-2">
                <AnimatePresence mode="popLayout">
                  {running.map((task) => <RunningCard key={task.id} task={task} project={projectById.get(task.project_id)} />)}
                </AnimatePresence>
              </div>
            </TaskSection>
          </main>

          <aside className="min-w-0 space-y-5">
            <QueuePanel tasks={queued} projectById={projectById} filtered={hasFilters} />
            <ProjectPulse projects={projects.data?.items ?? []} tasks={allTasks} />
            <RecentPanel tasks={recent} projectById={projectById} filtered={hasFilters} />
          </aside>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, icon, tone }: { label: string; value: number; icon: ReactNode; tone: "signal" | "warning" | "info" | "pulse" }) {
  const glows = { signal: "from-signal-400/[0.08]", warning: "from-amber-400/[0.07]", info: "from-sky-400/[0.07]", pulse: "from-pulse-400/[0.07]" };
  return (
    <div className={cn("relative flex items-center gap-3 border-b border-white/[0.07] bg-gradient-to-br p-4 last:border-b-0 sm:[&:nth-child(odd)]:border-r xl:border-b-0 xl:border-r xl:last:border-r-0", glows[tone])}>
      <span className="grid h-9 w-9 place-items-center rounded-xl border border-white/[0.08] bg-black/20">{icon}</span>
      <div><p className="font-mono text-xl font-semibold tabular-nums text-white">{value}</p><p className="text-[0.68rem] font-medium uppercase tracking-[0.12em] text-slate-600">{label}</p></div>
    </div>
  );
}

function TaskSection({ eyebrow, title, count, description, empty, emptyTone, children }: { eyebrow: string; title: string; count: number; description: string; empty: string; emptyTone?: "success"; children: ReactNode }) {
  return (
    <section>
      <div className="mb-3 flex items-end justify-between gap-4">
        <div><p className="eyebrow">{eyebrow}</p><div className="mt-1.5 flex items-center gap-2.5"><h2 className="text-lg font-semibold text-white">{title}</h2><span className="rounded-md bg-white/[0.055] px-2 py-0.5 font-mono text-[0.68rem] tabular-nums text-slate-500">{count}</span></div><p className="mt-1 text-xs text-slate-600">{description}</p></div>
      </div>
      {count ? children : <div className={cn("flex min-h-28 items-center gap-3 rounded-2xl border border-dashed px-5 text-sm", emptyTone === "success" ? "border-signal-400/15 bg-signal-400/[0.025] text-slate-500" : "border-white/[0.08] bg-white/[0.015] text-slate-600")}><CheckCircle2 className={cn("h-5 w-5 shrink-0", emptyTone === "success" ? "text-signal-400" : "text-slate-700")} />{empty}</div>}
    </section>
  );
}

function AttentionCard({ task, project }: { task: Task; project?: Project }) {
  const failed = task.status === "failed";
  return (
    <motion.article layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97 }} className={cn("group relative overflow-hidden rounded-2xl border p-4", failed ? "border-red-400/15 bg-gradient-to-br from-red-400/[0.07] to-white/[0.02]" : "border-amber-400/15 bg-gradient-to-br from-amber-400/[0.07] to-white/[0.02]")}>
      <div className="flex items-start justify-between gap-3">
        <TaskIdentity project={project} task={task} />
        <StatusBadge status={task.status} />
      </div>
      <h3 className="mt-3 line-clamp-2 text-sm font-semibold leading-5 text-slate-100">{task.title}</h3>
      <p className="mt-1.5 line-clamp-2 text-xs leading-5 text-slate-500">{task.initial_prompt}</p>
      <TaskTags tags={task.tags} />
      <div className="mt-4 flex items-center justify-between border-t border-white/[0.06] pt-3">
        <span className="font-mono text-[0.65rem] text-slate-600">Updated {formatRelativeTime(task.updated_at)}</span>
        <Link href={`/tasks/${task.id}`} className={cn("inline-flex items-center gap-1.5 text-xs font-semibold transition", failed ? "text-red-300 hover:text-red-200" : "text-amber-300 hover:text-amber-200")}>Review task <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" /></Link>
      </div>
    </motion.article>
  );
}

function RunningCard({ task, project }: { task: Task; project?: Project }) {
  return (
    <motion.article layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97 }} whileHover={{ y: -2 }} className="group relative overflow-hidden rounded-2xl border border-signal-400/15 bg-gradient-to-br from-signal-400/[0.055] to-white/[0.02] p-4 shadow-[0_16px_60px_rgba(0,0,0,0.16)]">
      <motion.div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-signal-400 to-transparent" animate={{ opacity: [0.25, 0.9, 0.25], scaleX: [0.55, 1, 0.55] }} transition={{ duration: 2.8, repeat: Infinity, ease: "easeInOut" }} />
      <div className="flex items-start justify-between gap-3"><TaskIdentity project={project} task={task} /><StatusBadge status={task.status} /></div>
      <h3 className="mt-3 line-clamp-2 text-sm font-semibold leading-5 text-slate-100">{task.title}</h3>
      <p className="mt-1.5 line-clamp-2 text-xs leading-5 text-slate-500">{task.initial_prompt}</p>
      <TaskTags tags={task.tags} />
      <div className="mt-4 grid grid-cols-2 gap-2 border-t border-white/[0.06] pt-3 text-[0.66rem]">
        <div><p className="uppercase tracking-wider text-slate-700">Runtime</p><p className="mt-1 truncate text-slate-400">{backendLabel(task.backend)} · {task.model || "default"}</p></div>
        <div><p className="uppercase tracking-wider text-slate-700">Started</p><p className="mt-1 font-mono text-slate-400">{formatRelativeTime(task.started_at || task.created_at)}</p></div>
      </div>
      <Link href={`/tasks/${task.id}`} className="mt-3 flex items-center justify-between rounded-xl border border-white/[0.07] bg-black/15 px-3 py-2 text-xs font-medium text-slate-300 transition hover:border-signal-400/20 hover:bg-signal-400/[0.05] hover:text-white"><span>Open live terminal</span><ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" /></Link>
    </motion.article>
  );
}

function TaskIdentity({ project, task }: { project?: Project; task: Task }) {
  return <div className="min-w-0"><Link href={project ? `/projects/${project.id}/board` : "#"} className="block max-w-48 truncate text-[0.68rem] font-semibold uppercase tracking-[0.1em] text-slate-400 transition hover:text-white">{project?.name ?? "Unknown project"}</Link><p className="mt-1 font-mono text-[0.62rem] text-slate-700">#{shortId(task.id)}</p></div>;
}

function StatusBadge({ status }: { status: TaskStatus }) {
  const config: Record<TaskStatus, { label: string; classes: string; icon: ReactNode }> = {
    running: { label: "Running", classes: "border-signal-400/20 bg-signal-400/[0.08] text-signal-300", icon: <CircleDot className="h-3 w-3 animate-pulse" /> },
    waiting_on_you: { label: "Needs input", classes: "border-amber-400/20 bg-amber-400/[0.08] text-amber-300", icon: <AlertTriangle className="h-3 w-3" /> },
    failed: { label: "Failed", classes: "border-red-400/20 bg-red-400/[0.08] text-red-300", icon: <XCircle className="h-3 w-3" /> },
    queued: { label: "Queued", classes: "border-sky-400/20 bg-sky-400/[0.08] text-sky-300", icon: <Clock3 className="h-3 w-3" /> },
    done: { label: "Complete", classes: "border-emerald-400/20 bg-emerald-400/[0.08] text-emerald-300", icon: <CheckCircle2 className="h-3 w-3" /> },
    cancelled: { label: "Cancelled", classes: "border-white/10 bg-white/[0.04] text-slate-500", icon: <XCircle className="h-3 w-3" /> },
  };
  const item = config[status];
  return <span className={cn("inline-flex shrink-0 items-center gap-1.5 rounded-lg border px-2 py-1 text-[0.62rem] font-semibold", item.classes)}>{item.icon}{item.label}</span>;
}

function TaskTags({ tags }: { tags: string[] }) {
  if (!tags.length) return null;
  return <div className="mt-3 flex flex-wrap gap-1.5">{tags.slice(0, 3).map((tag) => <span key={tag} className={cn("rounded-md border px-1.5 py-0.5 text-[0.58rem] font-medium", TASK_TAG_COLORS[tag] ?? "border-white/10 bg-white/[0.04] text-slate-400")}>{tag}</span>)}{tags.length > 3 && <span className="px-1 py-0.5 text-[0.58rem] text-slate-600">+{tags.length - 3}</span>}</div>;
}

function QueuePanel({ tasks, projectById, filtered }: { tasks: Task[]; projectById: Map<string, Project>; filtered: boolean }) {
  return <SidePanel title="Up next" count={tasks.length} icon={<TimerReset className="h-4 w-4 text-sky-300" />}>
    {tasks.length === 0 ? <PanelEmpty text={filtered ? "No queued tasks match." : "The queue is clear."} /> : <div className="divide-y divide-white/[0.06]">{tasks.slice(0, 6).map((task, index) => <Link key={task.id} href={`/tasks/${task.id}`} className="group flex items-center gap-3 py-3 first:pt-1 last:pb-1"><span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-white/[0.07] bg-white/[0.025] font-mono text-[0.62rem] text-slate-600">{index + 1}</span><span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium text-slate-300 group-hover:text-white">{task.title}</span><span className="mt-1 block truncate text-[0.62rem] text-slate-600">{projectById.get(task.project_id)?.name ?? "Unknown project"} · {backendLabel(task.backend)}</span></span><ArrowRight className="h-3.5 w-3.5 text-slate-700 transition group-hover:translate-x-0.5 group-hover:text-slate-400" /></Link>)}</div>}
  </SidePanel>;
}

function ProjectPulse({ projects, tasks }: { projects: Project[]; tasks: Task[] }) {
  const activity = projects.map((project) => ({ project, running: tasks.filter((task) => task.project_id === project.id && task.status === "running").length, attention: tasks.filter((task) => task.project_id === project.id && ATTENTION_STATUSES.includes(task.status)).length })).filter((item) => item.running || item.attention).sort((a, b) => (b.attention * 10 + b.running) - (a.attention * 10 + a.running));
  return <SidePanel title="Project pulse" count={activity.length} icon={<FolderKanban className="h-4 w-4 text-pulse-400" />}>
    {activity.length === 0 ? <PanelEmpty text="No projects have active work." /> : <div className="space-y-2">{activity.slice(0, 6).map(({ project, running, attention }) => <Link href={`/projects/${project.id}/board`} key={project.id} className="flex items-center gap-3 rounded-xl border border-transparent px-2 py-2 transition hover:border-white/[0.07] hover:bg-white/[0.025]"><span className="relative grid h-8 w-8 place-items-center rounded-lg border border-white/[0.08] bg-white/[0.035] text-[0.62rem] font-semibold text-slate-400"><FolderKanban className="h-3.5 w-3.5" />{attention > 0 && <span className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-amber-400 ring-2 ring-ink-900" />}</span><span className="min-w-0 flex-1 truncate text-xs font-medium text-slate-300">{project.name}</span><span className="flex gap-1.5 font-mono text-[0.6rem]"><span className="text-signal-400">{running} live</span>{attention > 0 && <span className="text-amber-300">{attention} blocked</span>}</span></Link>)}</div>}
    <Link href="/projects" className="mt-3 flex items-center justify-center gap-1.5 border-t border-white/[0.06] pt-3 text-[0.68rem] font-medium text-slate-500 transition hover:text-white">View all projects <ArrowRight className="h-3 w-3" /></Link>
  </SidePanel>;
}

function RecentPanel({ tasks, projectById, filtered }: { tasks: Task[]; projectById: Map<string, Project>; filtered: boolean }) {
  return <SidePanel title="Recent outcomes" count={tasks.length} icon={<CheckCircle2 className="h-4 w-4 text-emerald-300" />}>
    {tasks.length === 0 ? <PanelEmpty text={filtered ? "No outcomes match." : "Completed work will appear here."} /> : <div className="space-y-1">{tasks.map((task) => <Link key={task.id} href={`/tasks/${task.id}`} className="group flex items-center gap-2.5 rounded-lg px-2 py-2 transition hover:bg-white/[0.025]"><span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", task.status === "done" ? "bg-emerald-400" : "bg-slate-600")} /><span className="min-w-0 flex-1"><span className="block truncate text-xs text-slate-400 group-hover:text-slate-200">{task.title}</span><span className="mt-0.5 block truncate text-[0.58rem] text-slate-700">{projectById.get(task.project_id)?.name} · {formatRelativeTime(task.updated_at)}</span></span></Link>)}</div>}
  </SidePanel>;
}

function SidePanel({ title, count, icon, children }: { title: string; count: number; icon: ReactNode; children: ReactNode }) {
  return <section className="rounded-2xl border border-white/[0.07] bg-white/[0.02] p-4"><header className="mb-3 flex items-center gap-2 border-b border-white/[0.06] pb-3">{icon}<h2 className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">{title}</h2><span className="ml-auto rounded-md bg-white/[0.045] px-1.5 py-0.5 font-mono text-[0.6rem] text-slate-600">{count}</span></header>{children}</section>;
}

function PanelEmpty({ text }: { text: string }) {
  return <div className="flex min-h-16 items-center gap-2 text-xs text-slate-700"><Sparkles className="h-4 w-4" />{text}</div>;
}

function DashboardSkeleton() {
  return <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.65fr)_minmax(19rem,0.75fr)]"><div className="space-y-7"><div><Skeleton className="h-7 w-52" /><div className="mt-3 grid gap-3 lg:grid-cols-2"><Skeleton className="h-52" /><Skeleton className="h-52" /></div></div><div><Skeleton className="h-7 w-44" /><div className="mt-3 grid gap-3 md:grid-cols-2"><Skeleton className="h-64" /><Skeleton className="h-64" /></div></div></div><div className="space-y-5"><Skeleton className="h-52" /><Skeleton className="h-52" /><Skeleton className="h-44" /></div></div>;
}
