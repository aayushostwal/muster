"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowUpRight, Bot, FolderKanban, Plus, Search, Settings2, Trash2 } from "lucide-react";
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
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });

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
    return (projects.data?.items ?? []).filter((project) =>
      !value || project.name.toLowerCase().includes(value) || project.description?.toLowerCase().includes(value),
    );
  }, [projects.data, query]);

  return (
    <div className="mx-auto max-w-screen-xl px-4 py-6 sm:px-6 md:py-8 xl:px-8">
      <header className="flex flex-col gap-5 border-b border-white/[0.07] pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="eyebrow">Workspace administration</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-[-0.035em] text-white md:text-3xl">Projects</h1>
          <p className="mt-1.5 max-w-xl text-sm text-slate-500">Configure project workspaces and jump directly into their task boards.</p>
        </div>
        <Button variant="primary" onClick={() => setCreateOpen(true)} className="self-start sm:self-auto"><Plus className="h-4 w-4" /> New project</Button>
      </header>

      <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative flex-1 sm:max-w-lg">
          <Search className="absolute left-3.5 top-3 h-4 w-4 text-slate-600" />
          <input ref={searchRef} className="field h-10 pl-10" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search projects" placeholder="Search projects" />
        </div>
        <p className="font-mono text-[0.68rem] text-slate-600">{visible.length} workspace{visible.length === 1 ? "" : "s"}</p>
      </div>

      <div className="mt-5">
        {projects.isPending && <div className="grid gap-3 lg:grid-cols-2">{Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="h-44" />)}</div>}
        {projects.isError && <ErrorState message={projects.error.message} retry={() => projects.refetch()} />}
        {projects.isSuccess && visible.length === 0 && (
          <EmptyState title={query ? "No matching projects" : "Create your first project"} description={query ? "Try a different project name or clear the search." : "Bind a working directory, choose an agent runtime, and start coordinating tasks."} action={!query ? <Button variant="primary" onClick={() => setCreateOpen(true)}><Plus className="h-4 w-4" /> Create project</Button> : undefined} />
        )}
        <motion.div layout className="grid gap-3 lg:grid-cols-2">
          <AnimatePresence mode="popLayout">
            {visible.map((project, index) => <ProjectRow key={project.id} project={project} index={index} onDelete={() => remove.mutate(project.id)} deleting={remove.isPending} />)}
          </AnimatePresence>
        </motion.div>
      </div>
      <CreateProjectModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}

function ProjectRow({ project, index, onDelete, deleting }: { project: Project; index: number; onDelete: () => void; deleting: boolean }) {
  const [confirming, setConfirming] = useState(false);
  return (
    <motion.article layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.98 }} transition={{ delay: Math.min(index * 0.035, 0.16) }} className="group relative overflow-hidden rounded-2xl border border-white/[0.075] bg-white/[0.022] p-4 transition hover:border-white/[0.14] hover:bg-white/[0.035]">
      <div className="flex items-start gap-3.5">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-signal-400/15 bg-gradient-to-br from-signal-400/10 to-pulse-500/[0.06] text-[0.68rem] font-semibold text-signal-300">{initials(project.name)}</div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0"><h2 className="truncate text-sm font-semibold text-white">{project.name}</h2><p className="mt-1 line-clamp-2 min-h-8 text-xs leading-4 text-slate-600">{project.description || "No project description has been added."}</p></div>
            <button onClick={() => confirming ? onDelete() : setConfirming(true)} onBlur={() => setConfirming(false)} disabled={deleting} className={cn("shrink-0 rounded-lg p-2 opacity-0 transition group-hover:opacity-100 focus:opacity-100", confirming ? "bg-red-400/10 text-red-300" : "text-slate-700 hover:bg-white/[0.06] hover:text-slate-300")} aria-label={confirming ? `Confirm deletion of ${project.name}` : `Delete ${project.name}`}><Trash2 className="h-3.5 w-3.5" /></button>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[0.62rem]">
            <span className="inline-flex items-center gap-1.5 rounded-md border border-white/[0.07] bg-black/15 px-2 py-1 text-slate-400"><Bot className="h-3 w-3 text-signal-400" />{backendLabel(project.default_backend)}</span>
            <span className="max-w-40 truncate rounded-md border border-white/[0.07] bg-black/15 px-2 py-1 text-slate-500">{project.default_model || "Default model"}</span>
            <span className="ml-auto font-mono text-slate-700">Updated {formatRelativeTime(project.updated_at)}</span>
          </div>
        </div>
      </div>
      <div className="mt-4 flex items-center gap-2 border-t border-white/[0.06] pt-3">
        <Link href={`/projects/${project.id}/board`} className="inline-flex h-8 flex-1 items-center justify-center gap-1.5 rounded-lg bg-signal-400/[0.08] text-xs font-medium text-signal-300 transition hover:bg-signal-400/[0.13]"><FolderKanban className="h-3.5 w-3.5" /> Task board <ArrowUpRight className="h-3 w-3" /></Link>
        <Link href={`/projects/${project.id}`} className="inline-flex h-8 flex-1 items-center justify-center gap-1.5 rounded-lg border border-white/[0.08] text-xs font-medium text-slate-400 transition hover:bg-white/[0.05] hover:text-white"><Settings2 className="h-3.5 w-3.5" /> Configure</Link>
      </div>
    </motion.article>
  );
}
