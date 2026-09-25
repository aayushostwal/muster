"use client";

import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  AlertCircle,
  ArrowDownUp,
  ArrowUpRight,
  ClipboardCheck,
  CheckCircle2,
  ChevronDown,
  CircleDot,
  Clock3,
  Columns3,
  FilterX,
  Gauge,
  LayoutList,
  LoaderCircle,
  PauseCircle,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  StopCircle,
  Tags,
  Timer,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { CreateTaskModal } from "@/components/board/create-task-modal";
import { TagManager } from "@/components/board/tag-manager";
import { ProjectHeader } from "@/components/project/project-header";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { Tooltip } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { TASK_TAG_COLORS } from "@/lib/task-tags";
import { taskNeedsAttention, taskStage, type TaskStage } from "@/lib/task-status";
import type { AgentBackend, Task } from "@/lib/types";
import { backendLabel, cn, formatRelativeTime, shortId } from "@/lib/utils";

type BoardScope = "all" | "active" | "attention" | "finished";
type BoardView = "gallery" | "list";
type BoardDensity = "compact" | "comfortable";
type BoardSort = "updated" | "created" | "oldest" | "title";

const statusConfig: Record<TaskStage, {
  label: string;
  shortLabel: string;
  description: string;
  icon: typeof CircleDot;
  tone: string;
  dot: string;
  border: string;
  surface: string;
}> = {
  queued: { label: "Queued", shortLabel: "Queued", description: "Ready for an available runtime", icon: Clock3, tone: "text-slate-300", dot: "bg-slate-400", border: "border-slate-400/15", surface: "from-slate-400/[0.055]" },
  running: { label: "In progress", shortLabel: "Running", description: "Agents currently executing", icon: LoaderCircle, tone: "text-signal-300", dot: "bg-signal-400", border: "border-signal-400/20", surface: "from-signal-400/[0.07]" },
  waiting_on_you: { label: "Needs your input", shortLabel: "Needs input", description: "Blocked on a decision or permission", icon: PauseCircle, tone: "text-amber-300", dot: "bg-amber-400", border: "border-amber-400/20", surface: "from-amber-400/[0.07]" },
  ready_for_review: { label: "Ready for review", shortLabel: "Review", description: "A turn finished; verify it, continue, or complete the task", icon: ClipboardCheck, tone: "text-violet-300", dot: "bg-violet-400", border: "border-violet-400/20", surface: "from-violet-400/[0.07]" },
  failed: { label: "Failed", shortLabel: "Failed", description: "Runs that need review or a retry", icon: AlertCircle, tone: "text-red-300", dot: "bg-red-400", border: "border-red-400/20", surface: "from-red-400/[0.06]" },
  done: { label: "Completed", shortLabel: "Complete", description: "Successfully finished work", icon: CheckCircle2, tone: "text-emerald-300", dot: "bg-emerald-400", border: "border-emerald-400/15", surface: "from-emerald-400/[0.05]" },
  cancelled: { label: "Cancelled", shortLabel: "Cancelled", description: "Stopped before completion", icon: StopCircle, tone: "text-slate-500", dot: "bg-slate-600", border: "border-white/[0.07]", surface: "from-white/[0.025]" },
};

const stageOrder: TaskStage[] = ["waiting_on_you", "ready_for_review", "running", "queued", "failed", "done", "cancelled"];
const scopeOptions: Array<{ value: BoardScope; label: string; statuses: TaskStage[] }> = [
  { value: "all", label: "All work", statuses: stageOrder },
  { value: "active", label: "Active", statuses: ["running", "queued"] },
  { value: "attention", label: "Needs attention", statuses: ["waiting_on_you", "ready_for_review", "failed"] },
  { value: "finished", label: "History", statuses: ["done", "cancelled"] },
];

export function TaskBoard({ projectId }: { projectId: string }) {
  const [createOpen, setCreateOpen] = useState(false);
  const [tagsOpen, setTagsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [backend, setBackend] = useState<AgentBackend | "all">("all");
  const [tag, setTag] = useState("all");
  const [scope, setScope] = useState<BoardScope>("all");
  const [sort, setSort] = useState<BoardSort>("updated");
  const [view, setView] = useState<BoardView>("gallery");
  const [density, setDensity] = useState<BoardDensity>("compact");
  const [showEmpty, setShowEmpty] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const tasks = useQuery({ queryKey: ["tasks", projectId], queryFn: () => api.tasks(projectId), refetchInterval: 5_000 });
  const tagCatalog = useQuery({ queryKey: ["project-task-tags", projectId], queryFn: () => api.projectTaskTags(projectId) });

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const savedView = window.localStorage.getItem("muster:task-board-view");
      const savedDensity = window.localStorage.getItem("muster:task-board-density");
      if (savedView === "gallery" || savedView === "list") setView(savedView);
      if (savedDensity === "compact" || savedDensity === "comfortable") setDensity(savedDensity);
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);
  useEffect(() => { window.localStorage.setItem("muster:task-board-view", view); }, [view]);
  useEffect(() => { window.localStorage.setItem("muster:task-board-density", density); }, [density]);
  useEffect(() => {
    const focus = () => searchRef.current?.focus();
    const keyboard = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      const typing = target.matches("input, textarea, select, [contenteditable='true']");
      if (event.key === "/" && !typing) { event.preventDefault(); searchRef.current?.focus(); }
      if (event.key === "Escape" && document.activeElement === searchRef.current) { setQuery(""); searchRef.current?.blur(); }
    };
    window.addEventListener("muster:focus-search", focus);
    window.addEventListener("keydown", keyboard);
    return () => { window.removeEventListener("muster:focus-search", focus); window.removeEventListener("keydown", keyboard); };
  }, []);

  const allTasks = useMemo(() => tasks.data?.items ?? [], [tasks.data?.items]);
  const metrics = useMemo(() => getMetrics(allTasks), [allTasks]);
  const tagOptions = useMemo(() => {
    const counts = new Map<string, { name: string; count: number }>();
    for (const task of allTasks) for (const value of task.tags) {
      const key = value.toLowerCase();
      const current = counts.get(key);
      counts.set(key, { name: current?.name ?? value, count: (current?.count ?? 0) + 1 });
    }
    const used = [...counts.values()].sort((a, b) => a.name.localeCompare(b.name));
    return [
      { value: "all", label: "All tags" },
      { value: "__attention__", label: `Needs Attention (${metrics.attention})` },
      ...used.map((item) => ({ value: item.name, label: `${item.name} (${item.count})` })),
    ];
  }, [allTasks, metrics.attention]);
  const visibleTasks = useMemo(() => {
    const value = query.trim().toLowerCase();
    const statuses = scopeOptions.find((item) => item.value === scope)?.statuses ?? stageOrder;
    return sortTasks(allTasks.filter((task) =>
      statuses.includes(taskStage(task)) &&
      (backend === "all" || task.backend === backend) &&
      (tag === "all" || (tag === "__attention__" ? taskNeedsAttention(task) : task.tags.some((value) => value.toLowerCase() === tag.toLowerCase()))) &&
      (!value || task.title.toLowerCase().includes(value) || task.initial_prompt.toLowerCase().includes(value) || task.model?.toLowerCase().includes(value) || task.id.toLowerCase().includes(value) || task.tags.some((item) => item.toLowerCase().includes(value)))), sort);
  }, [allTasks, backend, query, scope, sort, tag]);
  const visibleStages = stageOrder.filter((status) => {
    const inScope = scopeOptions.find((item) => item.value === scope)?.statuses.includes(status);
    return inScope && (showEmpty || visibleTasks.some((task) => taskStage(task) === status));
  });
  const hasFilters = Boolean(query || backend !== "all" || tag !== "all" || scope !== "all");
  const clearFilters = () => { setQuery(""); setBackend("all"); setTag("all"); setScope("all"); };

  return (
    <div className="mx-auto max-w-[128rem] px-3 py-4 sm:px-5 md:px-7 md:py-6">
      <ProjectHeader projectId={projectId} />

      <section className="surface relative mt-3 overflow-hidden rounded-panel">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_12%_0%,rgba(66,232,196,0.09),transparent_28rem),radial-gradient(circle_at_90%_100%,rgba(102,104,245,0.08),transparent_26rem)]" />
        <div className="relative flex flex-col gap-4 px-4 py-4 lg:flex-row lg:items-center lg:justify-between lg:px-5">
          <div className="flex min-w-0 items-center gap-3.5">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-signal-400/15 bg-signal-400/[0.07] text-signal-300 shadow-glow"><Gauge className="h-4 w-4" /></div>
            <div className="min-w-0">
              <div className="flex items-center gap-2"><p className="eyebrow">Operations</p><span className="inline-flex items-center gap-1.5 text-[0.58rem] uppercase tracking-[0.14em] text-slate-600"><span className={cn("h-1.5 w-1.5 rounded-full", tasks.isFetching ? "animate-pulse bg-signal-400" : "bg-emerald-500/70")} />{tasks.isFetching ? "Syncing" : "Live"}</span></div>
              <h2 className="mt-1 truncate text-lg font-semibold tracking-[-0.025em] text-white">Task command center</h2>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-white/[0.07] bg-white/[0.07] sm:grid-cols-4 lg:min-w-[42rem]">
            <Metric label="In flight" value={metrics.active} hint={`${metrics.running} executing`} tone="signal" />
            <Metric label="Needs action" value={metrics.attention} hint={metrics.attention ? "Review blockers" : "All clear"} tone={metrics.attention ? "warning" : "neutral"} />
            <Metric label="Closed · 24h" value={metrics.closedToday} hint={`${metrics.done} total complete`} tone="neutral" />
            <Metric label="Success rate" value={`${metrics.successRate}%`} hint={`${metrics.total} tasks tracked`} tone="pulse" />
          </div>
          <Button variant="primary" onClick={() => setCreateOpen(true)} className="shrink-0"><Plus className="h-4 w-4" /> Launch task</Button>
        </div>
      </section>

      {metrics.attention > 0 && <AttentionRail tasks={allTasks.filter(taskNeedsAttention)} onShowAll={() => setScope("attention")} />}

      <section className="sticky top-[calc(var(--header-height)+0.5rem)] z-20 mt-3 rounded-2xl border border-white/[0.075] bg-ink-900/90 p-2.5 shadow-panel backdrop-blur-2xl" aria-label="Task board controls">
        <div className="flex flex-col gap-2 xl:flex-row xl:items-center">
          <div className="flex min-w-0 flex-1 gap-2">
            <div className="relative min-w-0 flex-1 xl:max-w-md">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-600" />
              <input ref={searchRef} className="field h-9 min-h-9 rounded-lg py-0 pl-9 pr-14 text-xs" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search title, brief, model, tag, or task ID" aria-label="Search tasks" />
              <kbd className="pointer-events-none absolute right-2.5 top-2 rounded border border-white/[0.08] bg-white/[0.035] px-1.5 py-0.5 font-mono text-[0.55rem] text-slate-600">/</kbd>
            </div>
            <div className="hidden items-center rounded-lg border border-white/[0.07] bg-black/15 p-0.5 sm:flex" aria-label="Task scope">
              {scopeOptions.map((item) => <button key={item.value} type="button" onClick={() => setScope(item.value)} aria-pressed={scope === item.value} className={cn("rounded-md px-2.5 py-1.5 text-[0.64rem] font-medium transition", scope === item.value ? "bg-white/[0.09] text-white shadow" : "text-slate-600 hover:text-slate-300")}>{item.label}</button>)}
            </div>
          </div>
          <div className="flex min-w-0 items-center gap-2 overflow-x-auto">
            <Select className="h-9 min-h-9 w-32 shrink-0 rounded-lg py-0 text-xs" label="Filter backend" value={backend} onChange={(value) => setBackend(value as AgentBackend | "all")} options={[{ value: "all", label: "All runtimes" }, { value: "claude_code", label: "Claude Code" }, { value: "codex", label: "Codex" }]} />
            <Select className="h-9 min-h-9 w-40 shrink-0 rounded-lg py-0 text-xs" label="Filter tag" value={tag} onChange={setTag} options={tagOptions} />
            <Tooltip label="Create or rename project tags" side="bottom"><button type="button" onClick={() => setTagsOpen(true)} className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-white/[0.07] bg-black/15 text-slate-600 transition hover:border-white/15 hover:text-white" aria-label="Manage project tags"><Tags className="h-3.5 w-3.5" /></button></Tooltip>
            <div className="relative shrink-0"><ArrowDownUp className="pointer-events-none absolute left-2.5 top-2.5 z-10 h-3.5 w-3.5 text-slate-600" /><Select className="h-9 min-h-9 w-36 rounded-lg py-0 pl-8 text-xs" label="Sort tasks" value={sort} onChange={(value) => setSort(value as BoardSort)} options={[{ value: "updated", label: "Recently active" }, { value: "created", label: "Newest first" }, { value: "oldest", label: "Oldest first" }, { value: "title", label: "Task title" }]} /></div>
            <div className="flex shrink-0 rounded-lg border border-white/[0.07] bg-black/15 p-0.5">
              <IconToggle active={view === "gallery"} label="Grouped gallery" onClick={() => setView("gallery")}><Columns3 className="h-3.5 w-3.5" /></IconToggle>
              <IconToggle active={view === "list"} label="Dense list" onClick={() => setView("list")}><LayoutList className="h-3.5 w-3.5" /></IconToggle>
            </div>
            {view === "gallery" && <Tooltip label={density === "compact" ? "Use comfortable cards" : "Fit more tasks"} side="bottom"><button type="button" onClick={() => setDensity((current) => current === "compact" ? "comfortable" : "compact")} className="h-9 shrink-0 rounded-lg border border-white/[0.07] bg-black/15 px-2.5 text-[0.6rem] font-medium text-slate-500 transition hover:text-white" aria-label="Toggle task card density">{density === "compact" ? "Compact" : "Comfortable"}</button></Tooltip>}
            <Tooltip label={showEmpty ? "Hide empty stages" : "Show empty stages"} side="bottom"><button type="button" onClick={() => setShowEmpty((current) => !current)} aria-pressed={showEmpty} className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-lg border transition", showEmpty ? "border-pulse-400/25 bg-pulse-400/10 text-pulse-400" : "border-white/[0.07] bg-black/15 text-slate-600 hover:text-white")} aria-label="Toggle empty stages"><CircleDot className="h-3.5 w-3.5" /></button></Tooltip>
            {hasFilters && <Tooltip label="Clear filters" side="bottom"><button type="button" onClick={clearFilters} className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-white/[0.07] bg-black/15 text-slate-600 transition hover:border-white/15 hover:text-white" aria-label="Clear task filters"><FilterX className="h-3.5 w-3.5" /></button></Tooltip>}
          </div>
        </div>
        <div className="mt-2 flex items-center gap-1 overflow-x-auto sm:hidden">{scopeOptions.map((item) => <button key={item.value} type="button" onClick={() => setScope(item.value)} className={cn("shrink-0 rounded-lg px-2.5 py-1.5 text-[0.62rem]", scope === item.value ? "bg-white/[0.09] text-white" : "text-slate-600")}>{item.label}</button>)}</div>
      </section>

      <div className="mt-3 flex items-center justify-between px-1 text-[0.62rem] text-slate-600"><p><span className="font-mono text-slate-400">{visibleTasks.length}</span> of {allTasks.length} tasks visible{tagCatalog.isSuccess && !allTasks.some((task) => task.tags.length) ? <button type="button" onClick={() => setTagsOpen(true)} className="ml-2 text-signal-400 hover:text-signal-300">No labels assigned — manage tags</button> : null}</p><p className="hidden items-center gap-1.5 sm:flex"><RefreshCw className={cn("h-3 w-3", tasks.isFetching && "animate-spin text-signal-400")} /> Refreshes every 5 seconds</p></div>
      {tasks.isPending && <BoardSkeleton />}
      {tasks.isError && <div className="mt-4"><ErrorState message={tasks.error.message} retry={() => tasks.refetch()} /></div>}
      {tasks.isSuccess && allTasks.length === 0 && <div className="mt-4"><EmptyState title="Your first run starts here" description="Launch a task and Muster will stream its execution, decisions, and result into this command center." action={<Button variant="primary" onClick={() => setCreateOpen(true)}><Sparkles className="h-4 w-4" /> Launch first task</Button>} /></div>}
      {tasks.isSuccess && allTasks.length > 0 && visibleTasks.length === 0 && <div className="mt-4"><EmptyState title="No tasks match this view" description="Clear a filter or switch scope to bring the rest of your work back into view." action={<Button onClick={clearFilters}><FilterX className="h-4 w-4" /> Clear filters</Button>} /></div>}
      {tasks.isSuccess && visibleTasks.length > 0 && view === "gallery" && <motion.div layout className="mt-3 space-y-2.5"><AnimatePresence initial={false} mode="popLayout">{visibleStages.map((status) => <TaskLane key={status} status={status} tasks={visibleTasks.filter((task) => taskStage(task) === status)} density={density} />)}</AnimatePresence></motion.div>}
      {tasks.isSuccess && visibleTasks.length > 0 && view === "list" && <TaskList tasks={visibleTasks} />}
      <CreateTaskModal projectId={projectId} open={createOpen} onClose={() => setCreateOpen(false)} />
      <TagManager projectId={projectId} open={tagsOpen} onClose={() => setTagsOpen(false)} />
    </div>
  );
}

function IconToggle({ active, label, onClick, children }: { active: boolean; label: string; onClick: () => void; children: ReactNode }) {
  return <Tooltip label={label} side="bottom"><button type="button" onClick={onClick} aria-label={label} aria-pressed={active} className={cn("grid h-8 w-8 place-items-center rounded-md transition", active ? "bg-white/[0.1] text-white" : "text-slate-600 hover:text-slate-300")}>{children}</button></Tooltip>;
}

function Metric({ label, value, hint, tone }: { label: string; value: string | number; hint: string; tone: "signal" | "warning" | "pulse" | "neutral" }) {
  return <div className="min-w-0 bg-ink-950/45 px-3 py-2.5"><div className="flex items-baseline justify-between gap-2"><p className="truncate text-[0.56rem] font-semibold uppercase tracking-[0.13em] text-slate-600">{label}</p><p className={cn("font-mono text-base font-semibold tabular-nums", tone === "signal" && "text-signal-300", tone === "warning" && "text-amber-300", tone === "pulse" && "text-pulse-400", tone === "neutral" && "text-slate-200")}>{value}</p></div><p className="mt-0.5 truncate text-[0.57rem] text-slate-700">{hint}</p></div>;
}

function AttentionRail({ tasks, onShowAll }: { tasks: Task[]; onShowAll: () => void }) {
  const urgent = sortTasks(tasks, "oldest");
  return <motion.section initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} className="mt-3 flex flex-col gap-2 rounded-2xl border border-amber-400/15 bg-amber-400/[0.04] px-3 py-2.5 sm:flex-row sm:items-center" aria-label="Tasks needing attention"><div className="flex shrink-0 items-center gap-2 text-amber-200"><span className="relative grid h-7 w-7 place-items-center rounded-lg bg-amber-400/10"><span className="absolute h-2 w-2 animate-ping rounded-full bg-amber-400/40" /><PauseCircle className="relative h-3.5 w-3.5" /></span><div><p className="text-[0.68rem] font-semibold">Action queue</p><p className="text-[0.56rem] text-amber-200/45">Oldest action first</p></div></div><div className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto sm:border-l sm:border-amber-400/10 sm:pl-3">{urgent.slice(0, 3).map((task) => <Link key={task.id} href={`/tasks/${task.id}`} className="group flex min-w-48 flex-1 items-center gap-2 rounded-lg border border-amber-400/10 bg-black/15 px-2.5 py-2 transition hover:border-amber-400/25 hover:bg-amber-400/[0.04]"><span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", statusConfig[taskStage(task)].dot)} /><span className="min-w-0 flex-1 truncate text-[0.65rem] text-slate-300 group-hover:text-white">{task.title}</span><span className="shrink-0 font-mono text-[0.54rem] text-slate-700">{formatRelativeTime(task.updated_at)}</span></Link>)}</div><button type="button" onClick={onShowAll} className="shrink-0 rounded-lg px-2.5 py-2 text-[0.62rem] font-medium text-amber-300 transition hover:bg-amber-400/[0.07]">Review all {tasks.length}</button></motion.section>;
}

function TaskLane({ status, tasks, density }: { status: TaskStage; tasks: Task[]; density: BoardDensity }) {
  const [open, setOpen] = useState(status !== "done" && status !== "cancelled");
  const [visibleCount, setVisibleCount] = useState(24);
  const config = statusConfig[status];
  const Icon = config.icon;
  const visible = tasks.slice(0, visibleCount);
  return <motion.section layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} className={cn("overflow-hidden rounded-2xl border bg-gradient-to-r to-transparent", config.border, config.surface)} aria-labelledby={`lane-${status}`}><button type="button" onClick={() => setOpen((current) => !current)} className="flex w-full items-center gap-3 px-3.5 py-3 text-left transition hover:bg-white/[0.018] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-400/40" aria-expanded={open}><span className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-current/10 bg-black/20", config.tone)}><Icon className={cn("h-3.5 w-3.5", status === "running" && "animate-spin motion-reduce:animate-none")} /></span><span className="min-w-0 flex-1"><span className="flex items-center gap-2"><span id={`lane-${status}`} className="text-xs font-semibold text-slate-100">{config.label}</span><span className="rounded-md bg-white/[0.05] px-1.5 py-0.5 font-mono text-[0.56rem] tabular-nums text-slate-500">{tasks.length}</span></span><span className="mt-0.5 hidden text-[0.6rem] text-slate-600 sm:block">{config.description}</span></span>{status === "running" && tasks.length > 0 && <span className="mr-2 hidden items-center gap-1.5 text-[0.58rem] text-signal-400/70 sm:flex"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-signal-400 motion-reduce:animate-none" /> live execution</span>}<ChevronDown className={cn("h-4 w-4 text-slate-600 transition-transform", !open && "-rotate-90")} /></button><AnimatePresence initial={false}>{open && <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ type: "spring", stiffness: 420, damping: 38 }} className="overflow-hidden"><div className={cn("grid border-t border-white/[0.055] p-2.5", density === "compact" ? "grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-2" : "grid-cols-[repeat(auto-fill,minmax(19rem,1fr))] gap-2.5")}><AnimatePresence mode="popLayout">{visible.map((task) => <TaskCard key={task.id} task={task} density={density} />)}</AnimatePresence>{tasks.length === 0 && <div className="col-span-full flex items-center gap-2 rounded-xl border border-dashed border-white/[0.06] px-3 py-4 text-[0.64rem] text-slate-700"><CircleDot className="h-3.5 w-3.5" /> Nothing in this stage</div>}{visibleCount < tasks.length && <button type="button" onClick={() => setVisibleCount((count) => count + 24)} className="col-span-full rounded-xl border border-dashed border-white/[0.08] px-3 py-3 text-xs text-slate-500 transition hover:border-white/15 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-400/40">Show {Math.min(24, tasks.length - visibleCount)} more</button>}</div></motion.div>}</AnimatePresence></motion.section>;
}

function TaskCard({ task, density }: { task: Task; density: BoardDensity }) {
  if (task.status === "done" || task.status === "cancelled") {
    return <OutcomeTaskCard task={task} />;
  }
  return <ActiveTaskCard task={task} density={density} />;
}

function OutcomeTaskCard({ task }: { task: Task }) {
  const config = statusConfig[task.status];
  const duration = task.started_at ? formatDuration(task.started_at, task.completed_at) : null;
  return <motion.article layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className={cn("group min-w-0 rounded-xl border bg-ink-850/55 transition-colors hover:border-white/[0.14] hover:bg-ink-800/70", config.border)}><Link href={`/tasks/${task.id}`} className="block rounded-xl p-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-400/40"><div className="flex items-center gap-2"><span className={cn("h-1.5 w-1.5 rounded-full", config.dot)} /><span className={cn("text-[0.55rem] font-semibold uppercase tracking-[0.12em]", config.tone)}>{config.shortLabel}</span><span className="ml-auto text-[0.56rem] text-slate-700">{formatRelativeTime(task.completed_at ?? task.updated_at)}</span></div><h4 className="mt-2 line-clamp-1 text-xs font-medium text-slate-200 transition group-hover:text-white">{task.title}</h4><div className="mt-2 flex min-w-0 items-center gap-1.5">{task.tags.slice(0, 2).map((value) => <TaskTag key={value} value={value} />)}{duration && <span className="ml-auto flex shrink-0 items-center gap-1 font-mono text-[0.54rem] text-slate-700"><Timer className="h-3 w-3" />{duration}</span>}</div></Link></motion.article>;
}

function ActiveTaskCard({ task, density }: { task: Task; density: BoardDensity }) {
  const reduceMotion = useReducedMotion();
  const stage = taskStage(task);
  const config = statusConfig[stage];
  const duration = task.started_at ? formatDuration(task.started_at, task.completed_at) : null;
  const needsAttention = task.status === "waiting_on_you" || task.status === "failed";
  const tags = [...(stage === "ready_for_review" ? ["Ready to Review"] : needsAttention ? ["Need Attention"] : []), ...task.tags];
  const visibleTags = tags.slice(0, density === "compact" ? 3 : 5);
  const action = task.status === "waiting_on_you"
    ? task.attention_reason === "awaiting_review" ? "Review & complete" : "Respond now"
    : task.status === "failed" ? "Inspect & retry" : task.status === "running" ? "Open live task" : "Review queued task";
  const currentAction = task.status === "running"
    ? "Agent is executing the current turn"
    : task.status === "queued"
      ? "Waiting for an available runtime"
      : task.status === "failed"
        ? "The last run failed and needs review"
        : task.attention_reason === "tool_permission"
          ? "A tool permission decision is blocking progress"
          : task.attention_reason === "blocking_question"
            ? "The agent is waiting for your answer"
            : "The turn finished; verify the delivery outcome";
  return <motion.article layout initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }} whileHover={reduceMotion ? undefined : { y: -2 }} className={cn("group relative min-w-0 overflow-hidden rounded-xl border bg-ink-850/85 shadow-sm transition-colors hover:border-white/[0.16] hover:bg-ink-800/90 hover:shadow-panel", config.border)}>{task.status === "running" && <motion.span className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-signal-400 to-transparent" animate={reduceMotion ? undefined : { x: ["-65%", "65%"] }} transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }} />}<Link href={`/tasks/${task.id}`} className={cn("block rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-400/40", density === "compact" ? "p-3" : "p-4")}><div className="flex items-center gap-2"><span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", config.dot, task.status === "running" && "animate-pulse motion-reduce:animate-none")} /><span className={cn("text-[0.56rem] font-semibold uppercase tracking-[0.12em]", config.tone)}>{config.shortLabel}</span><span className="ml-auto font-mono text-[0.53rem] text-slate-700">#{shortId(task.id)}</span></div><h4 className="mt-2.5 line-clamp-2 text-sm font-medium leading-5 text-slate-100 transition group-hover:text-white">{task.title}</h4><p className="mt-2 line-clamp-2 min-h-8 text-[0.65rem] leading-4 text-slate-500">{currentAction}</p><div className="mt-2.5 flex flex-wrap gap-1">{visibleTags.map((item) => <TaskTag key={item} value={item} />)}{tags.length > visibleTags.length && <span className="rounded-md border border-white/[0.06] px-1.5 py-0.5 text-[0.52rem] text-slate-600">+{tags.length - visibleTags.length}</span>}</div><div className="mt-2 flex flex-wrap items-center gap-1.5"><TaskChip>{backendLabel(task.backend)}</TaskChip><TaskChip>{task.model || "Default model"}</TaskChip>{task.cron_job_id && <TaskChip>Scheduled</TaskChip>}</div><div className="mt-3 flex items-center justify-between gap-2 border-t border-white/[0.06] pt-2.5"><span className="flex min-w-0 items-center gap-1.5 truncate text-[0.57rem] text-slate-600"><Clock3 className="h-3 w-3 shrink-0" /> Active {formatRelativeTime(task.updated_at)}{duration ? ` · ${duration}` : ""}</span><span className={cn("inline-flex shrink-0 items-center gap-1 text-[0.62rem] font-medium", stage === "ready_for_review" ? "text-violet-300" : needsAttention ? "text-amber-300" : "text-signal-300")}>{action}<ArrowUpRight className="h-3 w-3" /></span></div></Link></motion.article>;
}

function TaskTag({ value }: { value: string }) {
  const style = value === "Need Attention" ? "border-amber-400/25 bg-amber-400/[0.09] text-amber-300" : value === "Ready to Review" ? "border-violet-400/25 bg-violet-400/[0.09] text-violet-300" : TASK_TAG_COLORS[value] || "border-white/[0.08] bg-white/[0.035] text-slate-400";
  return <span className={cn("rounded-md border px-1.5 py-0.5 text-[0.52rem] font-medium", style)}>{value}</span>;
}

function TaskChip({ children }: { children: ReactNode }) {
  return <span className="max-w-32 truncate rounded-md border border-white/[0.06] bg-white/[0.025] px-1.5 py-0.5 text-[0.54rem] text-slate-500">{children}</span>;
}

function TaskList({ tasks }: { tasks: Task[] }) {
  const [visibleCount, setVisibleCount] = useState(100);
  const visible = tasks.slice(0, visibleCount);
  return <section className="surface mt-3 overflow-hidden rounded-2xl"><div className="grid grid-cols-[minmax(0,1fr)_9rem_9rem_10rem_6rem] gap-3 border-b border-white/[0.07] bg-black/15 px-4 py-2.5 text-[0.55rem] font-semibold uppercase tracking-[0.13em] text-slate-600 max-lg:grid-cols-[minmax(0,1fr)_8rem_6rem] max-sm:grid-cols-[minmax(0,1fr)_6.5rem]"><span>Task</span><span>Status</span><span className="max-sm:hidden">Runtime</span><span className="max-lg:hidden">Timing</span><span className="text-right max-lg:hidden">ID</span></div><motion.div layout><AnimatePresence mode="popLayout">{visible.map((task) => { const stage = taskStage(task); const config = statusConfig[stage]; const Icon = config.icon; const tags = [...(stage === "ready_for_review" ? ["Ready to Review"] : taskNeedsAttention(task) ? ["Need Attention"] : []), ...task.tags]; return <motion.div key={task.id} layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="group grid grid-cols-[minmax(0,1fr)_9rem_9rem_10rem_6rem] items-center gap-3 border-b border-white/[0.05] px-4 py-2.5 transition last:border-0 hover:bg-white/[0.025] max-lg:grid-cols-[minmax(0,1fr)_8rem_6rem] max-sm:grid-cols-[minmax(0,1fr)_6.5rem]"><Link href={`/tasks/${task.id}`} className="flex min-w-0 items-center gap-3 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-400/40"><span className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-white/[0.06] bg-white/[0.025]", config.tone)}><Icon className={cn("h-3.5 w-3.5", task.status === "running" && "animate-spin motion-reduce:animate-none")} /></span><span className="min-w-0 flex-1"><span className="flex min-w-0 items-center gap-2"><span className="min-w-0 flex-1 truncate text-xs font-medium text-slate-200 transition group-hover:text-white">{task.title}</span><span className="hidden shrink-0 gap-1 xl:flex">{tags.slice(0, 2).map((item) => <TaskTag key={item} value={item} />)}</span></span><span className="mt-0.5 block truncate text-[0.58rem] text-slate-700">{task.status === "done" ? "Completed conversation" : task.initial_prompt}</span></span></Link><span className={cn("flex items-center gap-1.5 text-[0.62rem]", config.tone)}><span className={cn("h-1.5 w-1.5 rounded-full", config.dot)} />{config.shortLabel}</span><span className="min-w-0 max-sm:hidden"><span className="block truncate text-[0.62rem] text-slate-400">{backendLabel(task.backend)}</span><span className="mt-0.5 block truncate text-[0.55rem] text-slate-700">{task.model || "Default model"}</span></span><span className="max-lg:hidden"><span className="block text-[0.6rem] text-slate-500">{formatRelativeTime(task.updated_at)}</span><span className="mt-0.5 block font-mono text-[0.54rem] text-slate-700">{task.started_at ? formatDuration(task.started_at, task.completed_at) : "Not started"}</span></span><Link href={`/tasks/${task.id}`} className="flex items-center justify-end gap-1 font-mono text-[0.55rem] text-slate-700 transition hover:text-signal-400 max-lg:hidden">{shortId(task.id)}<ArrowUpRight className="h-3 w-3" /></Link></motion.div>; })}</AnimatePresence></motion.div>{visibleCount < tasks.length && <button type="button" onClick={() => setVisibleCount((count) => count + 100)} className="w-full border-t border-white/[0.06] px-4 py-3 text-xs text-slate-500 transition hover:bg-white/[0.025] hover:text-white">Show more tasks</button>}</section>;
}

function BoardSkeleton() {
  return <div className="mt-4 space-y-3">{Array.from({ length: 3 }).map((_, index) => <div key={index} className="rounded-2xl border border-white/[0.06] p-3"><Skeleton className="h-9 w-56" /><div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4"><Skeleton className="h-36" /><Skeleton className="h-36" /><Skeleton className="h-36" /><Skeleton className="h-36" /></div></div>)}</div>;
}

function sortTasks(tasks: Task[], sort: BoardSort): Task[] {
  return [...tasks].sort((left, right) => {
    if (sort === "title") return left.title.localeCompare(right.title);
    if (sort === "oldest") return new Date(left.created_at).getTime() - new Date(right.created_at).getTime();
    const field = sort === "created" ? "created_at" : "updated_at";
    return new Date(right[field]).getTime() - new Date(left[field]).getTime();
  });
}

function getMetrics(tasks: Task[]) {
  const running = tasks.filter((task) => task.status === "running").length;
  const active = tasks.filter((task) => task.status === "running" || task.status === "queued").length;
  const attention = tasks.filter(taskNeedsAttention).length;
  const done = tasks.filter((task) => task.status === "done").length;
  const outcomes = tasks.filter((task) => ["done", "failed", "cancelled"].includes(task.status));
  const closedToday = outcomes.filter((task) => Date.now() - new Date(task.completed_at || task.updated_at).getTime() <= 86_400_000).length;
  return { total: tasks.length, running, active, attention, done, closedToday, successRate: outcomes.length ? Math.round((done / outcomes.length) * 100) : 100 };
}

function formatDuration(start: string, end: string | null): string {
  const elapsed = Math.max(0, new Date(end ?? Date.now()).getTime() - new Date(start).getTime());
  const minutes = Math.floor(elapsed / 60_000);
  if (minutes < 1) return "<1m";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}
