"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowUpRight, Boxes, Bot, Clock3, Plus, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { CreateProjectModal } from "@/components/projects/create-project-modal";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { backendLabel, cn, formatRelativeTime, initials } from "@/lib/utils";

export function ProjectsCommandCenter() {
  const [createOpen, setCreateOpen] = useState(false);
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const toast = useToast();

  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: api.projects,
  });

  useEffect(() => {
    const focus = () => searchRef.current?.focus();
    window.addEventListener("muster:focus-search", focus);
    return () => window.removeEventListener("muster:focus-search", focus);
  }, []);

  const remove = useMutation({
    mutationFn: api.deleteProject,
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ["projects"] });
      const previous = queryClient.getQueryData<{ items: Project[] }>(["projects"]);
      queryClient.setQueryData<{ items: Project[] }>(["projects"], (current) => ({
        items: current?.items.filter((item) => item.id !== id) ?? [],
      }));
      return { previous };
    },
    onError: (error: Error, _variables, context) => {
      queryClient.setQueryData(["projects"], context?.previous);
      toast(error.message, "error");
    },
    onSuccess: () => toast("Project permanently deleted", "success"),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["projects"] }),
  });

  const visible = useMemo(() => {
    const value = query.trim().toLowerCase();
    return (projects.data?.items ?? []).filter((project) => {
      return !value || project.name.toLowerCase().includes(value) || project.description?.toLowerCase().includes(value);
    });
  }, [projects.data, query]);

  return (
    <div className="mx-auto max-w-screen-2xl px-5 py-7 md:px-8 md:py-10">
      <section className="relative overflow-hidden rounded-panel border border-white/[0.08] bg-gradient-to-br from-white/[0.055] to-white/[0.018] px-6 py-8 shadow-panel md:px-9 md:py-10">
        <div className="absolute -right-20 -top-28 h-72 w-72 rounded-full bg-pulse-500/10 blur-3xl" aria-hidden="true" />
        <div className="relative flex flex-col justify-between gap-7 xl:flex-row xl:items-end">
          <div>
            <p className="eyebrow">Mission control</p>
            <h1 className="mt-3 max-w-3xl text-3xl font-semibold tracking-[-0.045em] text-white md:text-5xl">Coordinate every agent from one clear surface.</h1>
            <p className="mt-4 max-w-2xl text-sm leading-6 text-slate-400 md:text-base">Build focused workspaces, grant the exact capabilities they need, and watch execution move in real time.</p>
          </div>
          <Button variant="primary" onClick={() => setCreateOpen(true)} className="shrink-0"><Plus className="h-4 w-4" /> New project</Button>
        </div>
        <div className="relative mt-8 grid grid-cols-2 gap-3 md:max-w-xl md:grid-cols-3">
          <Metric icon={Boxes} value={projects.data?.items.length ?? 0} label="Projects" />
          <Metric icon={Bot} value="2" label="Agent runtimes" />
          <Metric icon={Clock3} value="Live" label="Event stream" className="col-span-2 md:col-span-1" />
        </div>
      </section>

      <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative flex-1 sm:max-w-md">
          <Search className="absolute left-3.5 top-3 h-4 w-4 text-slate-600" />
          <input ref={searchRef} className="field h-10 pl-10" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search projects" placeholder="Search projects" />
        </div>
        <p className="text-xs text-slate-600">{visible.length} project{visible.length === 1 ? "" : "s"}</p>
      </div>

      <div className="mt-5">
        {projects.isPending && <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="h-64" />)}</div>}
        {projects.isError && <ErrorState message={projects.error.message} retry={() => projects.refetch()} />}
        {projects.isSuccess && visible.length === 0 && (
          <EmptyState title={query ? "No matching projects" : "Your command center is ready"} description={query ? "Try a different project name or clear the search." : "Create a project to bind directories, configure capabilities, and launch your first agent task."} action={!query ? <Button variant="primary" onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" /> Create project</Button> : undefined} />
        )}
        <motion.div layout className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <AnimatePresence mode="popLayout">
            {visible.map((project, index) => (
              <ProjectCard key={project.id} project={project} index={index} onDelete={() => remove.mutate(project.id)} deleting={remove.isPending} />
            ))}
          </AnimatePresence>
        </motion.div>
      </div>
      <CreateProjectModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}

function Metric({ icon: Icon, value, label, className }: { icon: typeof Boxes; value: string | number; label: string; className?: string }) {
  return <div className={cn("rounded-xl border border-white/[0.07] bg-black/15 p-3.5", className)}><div className="flex items-center gap-2"><Icon className="h-3.5 w-3.5 text-signal-400" /><span className="font-mono text-sm font-semibold text-white">{value}</span></div><p className="mt-1.5 text-[0.68rem] text-slate-600">{label}</p></div>;
}

function ProjectCard({ project, index, onDelete, deleting }: { project: Project; index: number; onDelete: () => void; deleting: boolean }) {
  const [confirming, setConfirming] = useState(false);
  return (
    <motion.article layout initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.96 }} transition={{ delay: Math.min(index * 0.045, 0.2) }} whileHover={{ y: -4 }} className="group surface relative flex min-h-64 flex-col overflow-hidden rounded-panel p-5 transition-colors hover:border-white/[0.14]">
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-signal-400/0 to-transparent transition group-hover:via-signal-400/50" />
      <div className="flex items-start justify-between gap-4">
        <div className="grid h-11 w-11 place-items-center rounded-xl border border-white/10 bg-gradient-to-br from-signal-400/15 to-pulse-500/10 text-xs font-semibold text-signal-300">{initials(project.name)}</div>
        <button onClick={() => confirming ? onDelete() : setConfirming(true)} onBlur={() => setConfirming(false)} disabled={deleting} className={cn("rounded-lg p-2 opacity-0 transition group-hover:opacity-100 focus:opacity-100", confirming ? "bg-red-400/10 text-red-300" : "text-slate-700 hover:bg-white/[0.06] hover:text-slate-300")} aria-label={confirming ? `Confirm deletion of ${project.name}` : `Delete ${project.name}`}><Trash2 className="h-4 w-4" /></button>
      </div>
      <h2 className="mt-5 truncate text-lg font-semibold tracking-tight text-white">{project.name}</h2>
      <p className="mt-2 line-clamp-2 min-h-10 text-sm leading-5 text-slate-500">{project.description || "A focused workspace for autonomous agent execution."}</p>
      <div className="mt-5 flex flex-wrap gap-2">
        <span className="rounded-lg border border-white/[0.07] bg-white/[0.03] px-2.5 py-1 text-[0.66rem] text-slate-400">{backendLabel(project.default_backend)}</span>
        <span className="max-w-32 truncate rounded-lg border border-white/[0.07] bg-white/[0.03] px-2.5 py-1 text-[0.66rem] text-slate-500">{project.default_model || "Default model"}</span>
      </div>
      <div className="mt-auto flex items-end justify-between pt-5">
        <div><p className="text-[0.62rem] uppercase tracking-wider text-slate-700">Updated</p><p className="mt-1 font-mono text-[0.68rem] text-slate-500">{formatRelativeTime(project.updated_at)}</p></div>
        <Link href={`/projects/${project.id}/board`} className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium text-signal-400 transition hover:bg-signal-400/[0.07]">Open board <ArrowUpRight className="h-3.5 w-3.5" /></Link>
      </div>
    </motion.article>
  );
}
