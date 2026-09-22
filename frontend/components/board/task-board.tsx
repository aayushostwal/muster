"use client";

import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { AlertCircle, CheckCircle2, CircleDot, Clock3, Filter, LoaderCircle, PauseCircle, Plus, Search, StopCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { CreateTaskModal } from "@/components/board/create-task-modal";
import { ProjectHeader } from "@/components/project/project-header";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import type { AgentBackend, Task, TaskStatus } from "@/lib/types";
import { backendLabel, cn, formatRelativeTime } from "@/lib/utils";

const columns: Array<{ status: TaskStatus; label: string; icon: typeof CircleDot; tone: string }> = [
  { status: "queued", label: "Queued", icon: Clock3, tone: "text-slate-400" },
  { status: "running", label: "Running", icon: LoaderCircle, tone: "text-signal-400" },
  { status: "waiting_on_you", label: "Needs input", icon: PauseCircle, tone: "text-amber-400" },
  { status: "done", label: "Complete", icon: CheckCircle2, tone: "text-emerald-400" },
  { status: "failed", label: "Failed", icon: AlertCircle, tone: "text-red-400" },
  { status: "cancelled", label: "Cancelled", icon: StopCircle, tone: "text-slate-600" },
];

export function TaskBoard({ projectId }: { projectId: string }) {
  const [createOpen, setCreateOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [backend, setBackend] = useState<AgentBackend | "all">("all");
  const searchRef = useRef<HTMLInputElement>(null);
  const tasks = useQuery({ queryKey: ["tasks", projectId], queryFn: () => api.tasks(projectId), refetchInterval: 5_000 });
  useEffect(() => { const focus = () => searchRef.current?.focus(); window.addEventListener("muster:focus-search", focus); return () => window.removeEventListener("muster:focus-search", focus); }, []);
  const filtered = useMemo(() => { const value = query.trim().toLowerCase(); return (tasks.data?.items ?? []).filter((task) => (backend === "all" || task.backend === backend) && (!value || task.title.toLowerCase().includes(value) || task.initial_prompt.toLowerCase().includes(value))); }, [backend, query, tasks.data]);
  const activeCount = (tasks.data?.items ?? []).filter((task) => task.status === "running" || task.status === "queued").length;
  const attentionCount = (tasks.data?.items ?? []).filter((task) => task.status === "waiting_on_you" || task.status === "failed").length;

  return (
    <div className="mx-auto max-w-[120rem] px-5 py-6 md:px-8 md:py-8">
      <ProjectHeader projectId={projectId} />
      <div className="mt-5 flex flex-col justify-between gap-5 rounded-panel border border-white/[0.07] bg-white/[0.018] px-5 py-5 md:flex-row md:items-end md:px-7">
        <div><p className="eyebrow">Execution pipeline</p><h2 className="mt-2 text-2xl font-semibold tracking-[-0.035em] text-white">Task board</h2><p className="mt-2 text-sm text-slate-500"><span className="text-signal-400">{activeCount} active</span><span className="mx-2 text-slate-700">·</span>{attentionCount} need attention</p></div>
        <Button variant="primary" onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" /> Launch task</Button>
      </div>
      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1 sm:max-w-sm"><Search className="absolute left-3.5 top-3 h-4 w-4 text-slate-600" /><input ref={searchRef} className="field h-10 pl-10" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search tasks" aria-label="Search tasks" /></div>
        <div className="flex w-full items-center gap-2 sm:w-52"><Filter className="h-4 w-4 shrink-0 text-slate-600" /><Select className="h-10 min-h-10 py-0" label="Filter backend" value={backend} onChange={(value) => setBackend(value as AgentBackend | "all")} options={[{ value: "all", label: "All backends" }, { value: "claude_code", label: "Claude Code" }, { value: "codex", label: "Codex" }]} /></div>
      </div>
      {tasks.isPending && <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-6">{columns.map((item) => <Skeleton key={item.status} className="h-96" />)}</div>}
      {tasks.isError && <div className="mt-5"><ErrorState message={tasks.error.message} retry={() => tasks.refetch()} /></div>}
      {tasks.isSuccess && tasks.data.items.length === 0 && <div className="mt-5"><EmptyState title="The board is clear" description="Launch a task to put an agent to work. Its status will update here automatically." action={<Button variant="primary" onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" /> Launch first task</Button>} /></div>}
      {tasks.isSuccess && tasks.data.items.length > 0 && (
        <div className="mt-5 flex snap-x gap-3 overflow-x-auto pb-4 xl:grid xl:grid-cols-6 xl:overflow-visible">
          {columns.map((column) => <BoardColumn key={column.status} {...column} tasks={filtered.filter((task) => task.status === column.status)} />)}
        </div>
      )}
      <CreateTaskModal projectId={projectId} open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}

function BoardColumn({ status, label, icon: Icon, tone, tasks }: { status: TaskStatus; label: string; icon: typeof CircleDot; tone: string; tasks: Task[] }) {
  return (
    <section className="w-72 shrink-0 snap-start rounded-panel border border-white/[0.07] bg-white/[0.018] p-2.5 xl:w-auto" aria-labelledby={`column-${status}`}>
      <div className="flex items-center justify-between px-2 py-2"><div className="flex items-center gap-2"><Icon className={cn("h-3.5 w-3.5", tone, status === "running" && "animate-spin")} /><h3 id={`column-${status}`} className="text-[0.68rem] font-semibold uppercase tracking-wider text-slate-400">{label}</h3></div><span className="rounded-md bg-white/[0.05] px-1.5 py-0.5 font-mono text-[0.62rem] text-slate-600">{tasks.length}</span></div>
      <motion.div layout className="mt-1 min-h-48 space-y-2">
        <AnimatePresence mode="popLayout">
          {tasks.map((task) => <TaskCard key={task.id} task={task} />)}
        </AnimatePresence>
        {tasks.length === 0 && <div className="grid min-h-32 place-items-center rounded-xl border border-dashed border-white/[0.06]"><p className="text-[0.66rem] text-slate-700">No tasks</p></div>}
      </motion.div>
    </section>
  );
}

function TaskCard({ task }: { task: Task }) {
  return (
    <motion.article layout initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.94 }} whileHover={{ y: -2 }} className="group rounded-xl border border-white/[0.075] bg-ink-850/85 p-3.5 shadow-sm transition-colors hover:border-white/[0.15] hover:shadow-panel">
      <Link href={`/tasks/${task.id}`} className="block focus:outline-none"><h4 className="line-clamp-2 text-sm font-medium leading-5 text-slate-100 group-hover:text-white">{task.title}</h4><p className="mt-2 line-clamp-2 text-[0.68rem] leading-5 text-slate-600">{task.initial_prompt}</p><div className="mt-4 flex items-center justify-between gap-2"><span className="truncate rounded-md border border-white/[0.06] px-1.5 py-1 text-[0.58rem] text-slate-500">{backendLabel(task.backend)}</span><span className="shrink-0 font-mono text-[0.58rem] text-slate-700">{formatRelativeTime(task.updated_at)}</span></div></Link>
    </motion.article>
  );
}
