"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, LockKeyhole, Pencil, Plus, Tags } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { ProjectTaskTag } from "@/lib/types";

export function TagManager({ projectId, open, onClose }: { projectId: string; open: boolean; onClose: () => void }) {
  const catalog = useQuery({
    queryKey: ["project-task-tags", projectId],
    queryFn: () => api.projectTaskTags(projectId),
    enabled: open,
  });
  const [editing, setEditing] = useState<ProjectTaskTag | null>(null);
  const [name, setName] = useState("");
  const queryClient = useQueryClient();
  const toast = useToast();

  const save = useMutation({
    mutationFn: () => editing
      ? api.updateProjectTaskTag(projectId, editing.id, { name: name.trim() })
      : api.createProjectTaskTag(projectId, { name: name.trim() }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-task-tags", projectId] });
      queryClient.invalidateQueries({ queryKey: ["tasks", projectId] });
      toast(editing ? "Tag renamed across project tasks" : "Project tag created", "success");
      setEditing(null);
      setName("");
    },
    onError: (error: Error) => toast(error.message, "error"),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim() && !save.isPending) save.mutate();
  };

  const items = catalog.data?.items ?? [];
  return (
    <Modal open={open} onClose={onClose} title="Manage task tags" description="Tags are shared by every task in this project. Workflow evidence tags are maintained by Muster." wide>
      <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="min-h-64 rounded-xl border border-white/[0.07] bg-black/10 p-2">
          {catalog.isPending && <p className="px-3 py-8 text-center text-xs text-slate-600">Loading project tags…</p>}
          {!catalog.isPending && items.length === 0 && <div className="grid place-items-center px-4 py-10 text-center"><Tags className="h-5 w-5 text-slate-700" /><p className="mt-3 text-xs text-slate-500">No tags yet. Create one to organize this project.</p></div>}
          <ul className="space-y-1">
            {items.map((tag) => (
              <li key={tag.id} className="flex items-center gap-3 rounded-lg border border-transparent px-3 py-2.5 hover:border-white/[0.06] hover:bg-white/[0.025]">
                <span className="h-2 w-2 shrink-0 rounded-full bg-signal-400/70" />
                <span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium text-slate-200">{tag.name}</span><span className="mt-0.5 block text-[0.58rem] capitalize text-slate-700">{tag.kind === "system" ? "Evidence-backed workflow tag" : `${tag.kind} tag`}</span></span>
                {tag.kind === "system" ? <span className="inline-flex items-center gap-1 text-[0.58rem] text-slate-600"><LockKeyhole className="h-3 w-3" /> managed</span> : <button type="button" onClick={() => { setEditing(tag); setName(tag.name); }} className="grid h-8 w-8 place-items-center rounded-lg text-slate-600 transition hover:bg-white/[0.06] hover:text-white" aria-label={`Edit ${tag.name}`}><Pencil className="h-3.5 w-3.5" /></button>}
              </li>
            ))}
          </ul>
        </div>
        <form onSubmit={submit} className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
          <h3 className="text-sm font-medium text-white">{editing ? "Rename tag" : "Create a tag"}</h3>
          <p className="mt-2 text-xs leading-5 text-slate-600">Custom tags become available in task creation, controls, and project filters.</p>
          <label className="label mt-5" htmlFor="project-tag-name">Name</label>
          <input id="project-tag-name" className="field" value={name} onChange={(event) => setName(event.target.value)} maxLength={32} placeholder="e.g. Customer beta" />
          <div className="mt-4 flex gap-2">
            {editing && <Button type="button" variant="ghost" onClick={() => { setEditing(null); setName(""); }}>Cancel</Button>}
            <Button type="submit" variant="primary" loading={save.isPending} disabled={!name.trim()}>{editing ? <Check className="h-4 w-4" /> : <Plus className="h-4 w-4" />}{editing ? "Save rename" : "Create tag"}</Button>
          </div>
        </form>
      </div>
    </Modal>
  );
}
