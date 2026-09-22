"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, KanbanSquare, Settings2 } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Skeleton } from "@/components/ui/states";
import { api } from "@/lib/api";
import { backendLabel, cn } from "@/lib/utils";

export function ProjectHeader({ projectId }: { projectId: string }) {
  const pathname = usePathname();
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api.project(projectId) });

  if (project.isPending) return <Skeleton className="h-32" />;

  return (
    <header className="surface overflow-hidden rounded-panel">
      <div className="flex flex-col justify-between gap-5 px-5 py-5 md:flex-row md:items-center md:px-7">
        <div className="flex min-w-0 items-center gap-4">
          <Link href="/" className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/[0.08] text-slate-500 transition hover:border-white/15 hover:text-white" aria-label="Back to projects"><ArrowLeft className="h-4 w-4" /></Link>
          <div className="min-w-0">
            <div className="flex items-center gap-2"><h1 className="truncate text-xl font-semibold tracking-tight text-white">{project.data?.name ?? "Project unavailable"}</h1><span className="rounded-md border border-signal-400/15 bg-signal-400/[0.06] px-2 py-0.5 text-[0.6rem] font-semibold uppercase tracking-wider text-signal-400">{project.data ? backendLabel(project.data.default_backend) : "Offline"}</span></div>
            <p className="mt-1 truncate text-xs text-slate-600">{project.data?.description || "Agent operations workspace"}</p>
          </div>
        </div>
        <nav className="flex rounded-xl border border-white/[0.07] bg-black/20 p-1" aria-label="Project navigation">
          <Link href={`/projects/${projectId}/board`} className={cn("flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition", pathname.endsWith("/board") ? "bg-white/[0.09] text-white shadow" : "text-slate-500 hover:text-slate-200")}><KanbanSquare className="h-3.5 w-3.5" /> Task board</Link>
          <Link href={`/projects/${projectId}`} className={cn("flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition", !pathname.endsWith("/board") ? "bg-white/[0.09] text-white shadow" : "text-slate-500 hover:text-slate-200")}><Settings2 className="h-3.5 w-3.5" /> Capabilities</Link>
        </nav>
      </div>
    </header>
  );
}
