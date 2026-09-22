"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  ChevronDown,
  Clock3,
  Code2,
  ExternalLink,
  FileKey2,
  FolderCode,
  KeyRound,
  Link2,
  Plus,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { AgentBackend, Project } from "@/lib/types";
import { backendLabel, cn, formatDateTime, formatRelativeTime } from "@/lib/utils";

function Panel({ title, description, action, children }: { title: string; description: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="surface min-h-[32rem] rounded-panel">
      <div className="flex flex-col justify-between gap-4 border-b border-white/[0.07] px-5 py-5 sm:flex-row sm:items-center md:px-7">
        <div><h2 className="text-lg font-semibold tracking-tight text-white">{title}</h2><p className="mt-1 text-xs leading-5 text-slate-500">{description}</p></div>
        {action}
      </div>
      <div className="p-5 md:p-7">{children}</div>
    </section>
  );
}

function ResourceRow({ icon, title, meta, detail, actions }: { icon: ReactNode; title: string; meta: string; detail?: ReactNode; actions?: ReactNode }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <motion.div layout className="overflow-hidden rounded-xl border border-white/[0.07] bg-white/[0.02]">
      <div className="flex items-center gap-3 p-3.5">
        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-white/[0.07] bg-white/[0.035] text-slate-500">{icon}</div>
        <button className="min-w-0 flex-1 text-left" onClick={() => detail && setExpanded((value) => !value)} aria-expanded={detail ? expanded : undefined}>
          <span className="block truncate text-sm font-medium text-slate-100">{title}</span>
          <span className="mt-0.5 block truncate font-mono text-[0.66rem] text-slate-600">{meta}</span>
        </button>
        {detail && <button onClick={() => setExpanded((value) => !value)} className="rounded-lg p-2 text-slate-600 transition hover:bg-white/[0.05] hover:text-white" aria-label={`${expanded ? "Collapse" : "Expand"} ${title}`}><ChevronDown className={cn("h-4 w-4 transition-transform", expanded && "rotate-180")} /></button>}
        {actions}
      </div>
      <AnimatePresence initial={false}>
        {expanded && detail && <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden"><div className="border-t border-white/[0.06] bg-black/10 px-4 py-4">{detail}</div></motion.div>}
      </AnimatePresence>
    </motion.div>
  );
}

function DeleteButton({ onDelete, loading, label }: { onDelete: () => void; loading?: boolean; label: string }) {
  const [armed, setArmed] = useState(false);
  return (
    <Button size="sm" variant={armed ? "danger" : "ghost"} loading={loading} onClick={() => armed ? onDelete() : setArmed(true)} onBlur={() => setArmed(false)} aria-label={armed ? `Confirm deletion of ${label}` : `Delete ${label}`}>
      <Trash2 className="h-3.5 w-3.5" /> {armed && <span>Confirm</span>}
    </Button>
  );
}

function ListLoading() {
  return <div className="space-y-2">{Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-16 rounded-xl" />)}</div>;
}

function FormError({ message }: { message: string }) {
  return message ? <p role="alert" className="rounded-xl border border-red-400/15 bg-red-400/[0.05] px-3 py-2.5 text-xs text-red-300">{message}</p> : null;
}

export function ProfilePanel({ projectId }: { projectId: string }) {
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api.project(projectId) });
  return <Panel title="Project profile" description="Defaults inherited by every new agent task.">{project.isPending ? <ListLoading /> : project.isError ? <ErrorState message={project.error.message} retry={() => project.refetch()} /> : <ProfileForm project={project.data} />}</Panel>;
}

function ProfileForm({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const [backend, setBackend] = useState<AgentBackend>(project.default_backend);
  const [model, setModel] = useState(project.default_model ?? "");
  const [context, setContext] = useState(project.default_context_strategy);
  const models = useQuery({ queryKey: ["models", backend], queryFn: () => api.models(backend), staleTime: 60 * 60 * 1000 });
  const save = useMutation({
    mutationFn: () => api.updateProject(project.id, { name: name.trim(), description: description.trim() || null, default_backend: backend, default_model: model.trim() || null, default_context_strategy: context }),
    onSuccess: (updated) => { queryClient.setQueryData(["project", project.id], updated); queryClient.invalidateQueries({ queryKey: ["projects"] }); toast("Project profile updated", "success"); },
    onError: (error: Error) => toast(error.message, "error"),
  });
  return (
    <form onSubmit={(event) => { event.preventDefault(); if (name.trim()) save.mutate(); }} className="max-w-3xl space-y-6">
      <div className="grid gap-5 sm:grid-cols-2">
        <div><label className="label" htmlFor="profile-name">Project name</label><input id="profile-name" className="field" value={name} onChange={(event) => setName(event.target.value)} required /></div>
        <div><label className="label">Default model</label><Select label={models.isPending ? "Discovering models" : "Select default model"} value={model} onChange={setModel} options={(models.data?.items ?? []).map((item) => ({ value: item.id, label: item.label, description: item.id }))} /></div>
      </div>
      <div><label className="label" htmlFor="profile-description">Description</label><textarea id="profile-description" className="field min-h-28 resize-y" value={description} onChange={(event) => setDescription(event.target.value)} /></div>
      <div className="grid gap-5 sm:grid-cols-2">
        <div><label className="label">Default backend</label><Select label="Select backend" value={backend} onChange={(value) => { setBackend(value as AgentBackend); setModel(""); }} options={[{ value: "claude_code", label: "Claude Code" }, { value: "codex", label: "Codex" }]} /></div>
        <div><label className="label">Context strategy</label><Select label="Select context strategy" value={context} onChange={setContext} options={[{ value: "full", label: "Full conversation" }, { value: "compressed", label: "Compressed context" }]} /></div>
      </div>
      <div className="flex items-center justify-between border-t border-white/[0.06] pt-5"><p className="text-[0.68rem] text-slate-600">Last changed {formatRelativeTime(project.updated_at)}</p><Button type="submit" variant="primary" loading={save.isPending}>Save changes</Button></div>
    </form>
  );
}

export function DirectoryPanel({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false);
  const [directoryId, setDirectoryId] = useState("");
  const [scope, setScope] = useState("read_write");
  const [error, setError] = useState("");
  const queryClient = useQueryClient();
  const toast = useToast();
  const query = useQuery({ queryKey: ["directories", projectId], queryFn: () => api.directories(projectId) });
  const globalDirectories = useQuery({ queryKey: ["registry", "directories"], queryFn: api.globalDirectories });
  const create = useMutation({ mutationFn: () => api.createDirectory(projectId, { directory_id: directoryId, access_scope: scope }), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["directories", projectId] }); setOpen(false); setDirectoryId(""); toast("Directory access granted", "success"); }, onError: (cause: Error) => setError(cause.message) });
  const remove = useMutation({ mutationFn: api.deleteDirectory.bind(null, projectId), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["directories", projectId] }); toast("Directory removed", "success"); }, onError: (cause: Error) => toast(cause.message, "error") });
  return (
    <Panel title="Directory access" description="Filesystem roots agents may inspect or modify." action={<Button variant="primary" size="sm" onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Add directory</Button>}>
      {query.isPending ? <ListLoading /> : query.isError ? <ErrorState message={query.error.message} retry={() => query.refetch()} /> : query.data.items.length === 0 ? <EmptyState title="No directories bound" description="Grant a project access to an explicit local path before launching filesystem work." /> : <div className="space-y-2">{query.data.items.map((item) => <ResourceRow key={item.id} icon={<FolderCode className="h-4 w-4" />} title={item.path.split("/").filter(Boolean).at(-1) || item.path} meta={item.path} detail={<div className="flex items-center gap-2 text-xs text-slate-400"><ShieldCheck className="h-4 w-4 text-signal-400" /> {item.access_scope === "read_write" ? "Read and write access" : "Read-only access"}</div>} actions={<DeleteButton label={item.path} loading={remove.isPending} onDelete={() => remove.mutate(item.id)} />} />)}</div>}
      <Modal open={open} onClose={() => setOpen(false)} title="Grant directory access" description="Choose from the global directory registry."><form onSubmit={(event) => { event.preventDefault(); if (!directoryId) return setError("Select a directory."); setError(""); create.mutate(); }} className="space-y-5"><div><label className="label">Global directory</label><Select label="Select a directory" value={directoryId} onChange={setDirectoryId} options={(globalDirectories.data?.items ?? []).filter((item) => !query.data?.items.some((binding) => binding.directory_id === item.id)).map((item) => ({ value: item.id, label: item.name, description: item.path }))} /></div><div><label className="label">Access scope</label><Select label="Select access scope" value={scope} onChange={setScope} options={[{ value: "read_write", label: "Read and write" }, { value: "read", label: "Read only" }]} /></div>{globalDirectories.data?.items.length === 0 && <p className="text-xs text-slate-500">Create a directory in the <Link href="/registry/directories" className="text-signal-400">global registry</Link> first.</p>}<FormError message={error} /><div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" variant="primary" loading={create.isPending} disabled={!directoryId}>Grant access</Button></div></form></Modal>
    </Panel>
  );
}

export function CapabilityPanel({ projectId, type }: { projectId: string; type: "agent" | "skill" | "mcp" }) {
  const queryClient = useQueryClient(); const toast = useToast();
  const query = useQuery({ queryKey: ["capabilities", projectId, type], queryFn: () => api.capabilities(projectId, type) });
  const configure = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => api.configureCapability(projectId, type, id, { enabled }),
    onMutate: async ({ id, enabled }) => {
      await queryClient.cancelQueries({ queryKey: ["capabilities", projectId, type] });
      const previous = query.data;
      queryClient.setQueryData(["capabilities", projectId, type], { items: (query.data?.items ?? []).map((item) => item.resource_id === id ? { ...item, enabled } : item) });
      return { previous };
    },
    onError: (cause: Error, _variables, context) => { queryClient.setQueryData(["capabilities", projectId, type], context?.previous); toast(cause.message, "error"); },
    onSuccess: () => toast("Project capability updated", "success"),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["capabilities", projectId, type] }),
  });
  const labels = type === "agent" ? { title: "Agent access", description: "Global agents are available by default. Disable profiles this project should not invoke.", empty: "No global agents", route: "agents" } : type === "skill" ? { title: "Skill access", description: "Control which global instruction modules agents may use in this project.", empty: "No global skills", route: "skills" } : { title: "MCP connectors", description: "Global connectors are available by default and may be disabled per project.", empty: "No global connectors", route: "mcp" };
  return <Panel title={labels.title} description={labels.description} action={<Link href={`/registry/${labels.route}`} className="inline-flex h-9 items-center rounded-xl border border-white/10 bg-white/[0.045] px-3 text-xs font-medium text-slate-300 transition hover:border-white/20 hover:text-white">Manage globally</Link>}>
    {query.isPending ? <ListLoading /> : query.isError ? <ErrorState message={query.error.message} retry={() => query.refetch()} /> : query.data.items.length === 0 ? <EmptyState title={labels.empty} description="Add resources in the global registry, then configure their project access here." /> : <div className="space-y-2">{query.data.items.map((item) => <ResourceRow key={item.resource_id} icon={type === "agent" ? <BotIcon /> : type === "skill" ? <SparklesIcon /> : <Activity className="h-4 w-4" />} title={item.name} meta={item.description || (item.global_enabled ? "Enabled globally" : "Disabled globally")} detail={Object.keys(item.config).length ? <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[0.68rem] leading-5 text-slate-500">{JSON.stringify(item.config, null, 2)}</pre> : <p className="text-xs text-slate-600">No project-specific configuration.</p>} actions={<button role="switch" aria-checked={item.enabled} onClick={() => configure.mutate({ id: item.resource_id, enabled: !item.enabled })} className={cn("relative h-6 w-11 rounded-full border transition", item.enabled ? "border-signal-400/30 bg-signal-400/20" : "border-white/10 bg-white/[0.04]")}><span className={cn("absolute top-1 h-3.5 w-3.5 rounded-full transition-all", item.enabled ? "left-6 bg-signal-400" : "left-1 bg-slate-600")} /></button>} />)}</div>}
  </Panel>;
}

function BotIcon() { return <span className="text-xs text-signal-400">AI</span>; }
function SparklesIcon() { return <span className="text-xs text-pulse-400">✦</span>; }

export function McpPanel({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(""); const [command, setCommand] = useState(""); const [args, setArgs] = useState(""); const [env, setEnv] = useState(""); const [error, setError] = useState("");
  const queryClient = useQueryClient(); const toast = useToast();
  const query = useQuery({ queryKey: ["mcp", projectId], queryFn: () => api.mcpServers(projectId) });
  const create = useMutation({ mutationFn: () => api.createMcp(projectId, { name: name.trim(), config: { command: command.trim(), args: args.split(/\s+/).filter(Boolean), env: Object.fromEntries(env.split("\n").filter(Boolean).map((line) => { const [key, ...value] = line.split("="); return [key.trim(), value.join("=").trim()]; })) } }), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["mcp", projectId] }); setOpen(false); setName(""); setCommand(""); setArgs(""); setEnv(""); toast("MCP server connected", "success"); }, onError: (cause: Error) => setError(cause.message) });
  const remove = useMutation({ mutationFn: api.deleteMcp.bind(null, projectId), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["mcp", projectId] }); toast("MCP server disconnected", "success"); }, onError: (cause: Error) => toast(cause.message, "error") });
  return <Panel title="MCP servers" description="Protocol servers available to every agent in this project." action={<Button variant="primary" size="sm" onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Connect server</Button>}>
    {query.isPending ? <ListLoading /> : query.isError ? <ErrorState message={query.error.message} retry={() => query.refetch()} /> : query.data.items.length === 0 ? <EmptyState title="No MCP servers connected" description="Connect a server process to extend agent context and capabilities." /> : <div className="space-y-2">{query.data.items.map((item) => <ResourceRow key={item.id} icon={<Activity className="h-4 w-4" />} title={item.name} meta={item.config.command} detail={<pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[0.68rem] leading-5 text-slate-500">{JSON.stringify(item.config, null, 2)}</pre>} actions={<DeleteButton label={item.name} loading={remove.isPending} onDelete={() => remove.mutate(item.id)} />} />)}</div>}
    <Modal open={open} onClose={() => setOpen(false)} title="Connect MCP server" description="Define the local process and optional environment passed to it." wide><form onSubmit={(event) => { event.preventDefault(); if (!name.trim() || !command.trim()) return setError("Name and command are required."); setError(""); create.mutate(); }} className="space-y-5"><div className="grid gap-4 sm:grid-cols-2"><div><label className="label" htmlFor="mcp-name">Display name</label><input id="mcp-name" className="field" value={name} onChange={(e) => setName(e.target.value)} /></div><div><label className="label" htmlFor="mcp-command">Command</label><input id="mcp-command" className="field font-mono" value={command} onChange={(e) => setCommand(e.target.value)} /></div></div><div><label className="label" htmlFor="mcp-args">Arguments <span className="text-slate-600">— space separated</span></label><input id="mcp-args" className="field font-mono" value={args} onChange={(e) => setArgs(e.target.value)} /></div><div><label className="label" htmlFor="mcp-env">Environment <span className="text-slate-600">— one KEY=value per line</span></label><textarea id="mcp-env" className="field min-h-28 font-mono" value={env} onChange={(e) => setEnv(e.target.value)} /></div><FormError message={error} /><div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" variant="primary" loading={create.isPending}>Connect server</Button></div></form></Modal>
  </Panel>;
}

export function ToolPanel({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false); const [name, setName] = useState(""); const [config, setConfig] = useState("{}"); const [error, setError] = useState("");
  const queryClient = useQueryClient(); const toast = useToast();
  const query = useQuery({ queryKey: ["tools", projectId], queryFn: () => api.tools(projectId) });
  const create = useMutation({ mutationFn: (parsed: Record<string, unknown>) => api.createTool(projectId, { name: name.trim(), config: parsed }), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["tools", projectId] }); setOpen(false); setName(""); setConfig("{}"); toast("Tool registered", "success"); }, onError: (cause: Error) => setError(cause.message) });
  const remove = useMutation({ mutationFn: api.deleteTool.bind(null, projectId), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["tools", projectId] }); toast("Tool removed", "success"); }, onError: (cause: Error) => toast(cause.message, "error") });
  const submit = (event: FormEvent) => { event.preventDefault(); try { const parsed = JSON.parse(config) as unknown; if (!name.trim() || !parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("Enter a name and a valid JSON object."); setError(""); create.mutate(parsed as Record<string, unknown>); } catch (cause) { setError(cause instanceof Error ? cause.message : "Invalid JSON configuration."); } };
  return <Panel title="Tool registry" description="Structured tool configurations injected into agent sessions." action={<Button variant="primary" size="sm" onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Register tool</Button>}>
    {query.isPending ? <ListLoading /> : query.isError ? <ErrorState message={query.error.message} retry={() => query.refetch()} /> : query.data.items.length === 0 ? <EmptyState title="No tools registered" description="Register a tool configuration to make it available during execution." /> : <div className="space-y-2">{query.data.items.map((item) => <ResourceRow key={item.id} icon={<Code2 className="h-4 w-4" />} title={item.name} meta={`${Object.keys(item.config).length} configuration keys`} detail={<pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[0.68rem] leading-5 text-slate-500">{JSON.stringify(item.config, null, 2)}</pre>} actions={<DeleteButton label={item.name} loading={remove.isPending} onDelete={() => remove.mutate(item.id)} />} />)}</div>}
    <Modal open={open} onClose={() => setOpen(false)} title="Register a tool" description="Configuration is stored as structured JSON."><form onSubmit={submit} className="space-y-5"><div><label className="label" htmlFor="tool-name">Tool name</label><input id="tool-name" className="field" value={name} onChange={(e) => setName(e.target.value)} /></div><div><label className="label" htmlFor="tool-config">Configuration</label><textarea id="tool-config" className="field min-h-40 font-mono" value={config} onChange={(e) => setConfig(e.target.value)} spellCheck={false} /></div><FormError message={error} /><div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" variant="primary" loading={create.isPending}>Register tool</Button></div></form></Modal>
  </Panel>;
}

export function ArtifactPanel({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false); const [name, setName] = useState(""); const [localPath, setLocalPath] = useState(""); const [remoteUrl, setRemoteUrl] = useState(""); const [error, setError] = useState("");
  const queryClient = useQueryClient(); const toast = useToast();
  const query = useQuery({ queryKey: ["artifacts", projectId], queryFn: () => api.artifacts(projectId) });
  const create = useMutation({ mutationFn: () => api.createArtifact(projectId, { name: name.trim(), local_path: localPath.trim(), remote_url: remoteUrl.trim() || null }), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["artifacts", projectId] }); setOpen(false); setName(""); setLocalPath(""); setRemoteUrl(""); toast("Artifact linked", "success"); }, onError: (cause: Error) => setError(cause.message) });
  const remove = useMutation({ mutationFn: api.deleteArtifact.bind(null, projectId), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["artifacts", projectId] }); toast("Artifact unlinked", "success"); }, onError: (cause: Error) => toast(cause.message, "error") });
  return <Panel title="Artifacts" description="Local outputs and their optional remote destinations." action={<Button variant="primary" size="sm" onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Link artifact</Button>}>
    {query.isPending ? <ListLoading /> : query.isError ? <ErrorState message={query.error.message} retry={() => query.refetch()} /> : query.data.items.length === 0 ? <EmptyState title="No artifacts linked" description="Track a repository, report, or generated output alongside this project." /> : <div className="space-y-2">{query.data.items.map((item) => <ResourceRow key={item.id} icon={<Link2 className="h-4 w-4" />} title={item.name} meta={item.local_path} detail={<div className="space-y-2 text-xs text-slate-500"><p className="font-mono">{item.local_path}</p>{item.remote_url && <a href={item.remote_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-signal-400 hover:text-signal-300">Open remote <ExternalLink className="h-3 w-3" /></a>}</div>} actions={<DeleteButton label={item.name} loading={remove.isPending} onDelete={() => remove.mutate(item.id)} />} />)}</div>}
    <Modal open={open} onClose={() => setOpen(false)} title="Link an artifact" description="Connect a named local output to this project."><form onSubmit={(event) => { event.preventDefault(); if (!name.trim() || !localPath.trim()) return setError("Name and local path are required."); setError(""); create.mutate(); }} className="space-y-5"><div><label className="label" htmlFor="artifact-name">Artifact name</label><input id="artifact-name" className="field" value={name} onChange={(e) => setName(e.target.value)} /></div><div><label className="label" htmlFor="artifact-path">Local path</label><input id="artifact-path" className="field font-mono" value={localPath} onChange={(e) => setLocalPath(e.target.value)} /></div><div><label className="label" htmlFor="artifact-url">Remote URL <span className="text-slate-600">— optional</span></label><input id="artifact-url" type="url" className="field" value={remoteUrl} onChange={(e) => setRemoteUrl(e.target.value)} /></div><FormError message={error} /><div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" variant="primary" loading={create.isPending}>Link artifact</Button></div></form></Modal>
  </Panel>;
}

export function CronPanel({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false); const [name, setName] = useState(""); const [schedule, setSchedule] = useState("0 9 * * 1-5"); const [prompt, setPrompt] = useState(""); const [backend, setBackend] = useState<AgentBackend>("claude_code"); const [model, setModel] = useState(""); const [error, setError] = useState("");
  const queryClient = useQueryClient(); const toast = useToast();
  const query = useQuery({ queryKey: ["cron", projectId], queryFn: () => api.cronJobs(projectId) });
  const modelCatalog = useQuery({ queryKey: ["models", backend], queryFn: () => api.models(backend), enabled: open, staleTime: 60 * 60 * 1000 });
  const create = useMutation({ mutationFn: () => api.createCron(projectId, { name: name.trim(), schedule_expr: schedule.trim(), prompt: prompt.trim(), backend, model: model.trim() || null }), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["cron", projectId] }); setOpen(false); setName(""); setPrompt(""); toast("Schedule activated", "success"); }, onError: (cause: Error) => setError(cause.message) });
  const toggle = useMutation({ mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => api.toggleCron(projectId, id, enabled), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["cron", projectId] }), onError: (cause: Error) => toast(cause.message, "error") });
  const remove = useMutation({ mutationFn: api.deleteCron.bind(null, projectId), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["cron", projectId] }); toast("Schedule removed", "success"); }, onError: (cause: Error) => toast(cause.message, "error") });
  return <Panel title="Schedules" description="Recurring work that enters the same task board as manual requests." action={<Button variant="primary" size="sm" onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> New schedule</Button>}>
    {query.isPending ? <ListLoading /> : query.isError ? <ErrorState message={query.error.message} retry={() => query.refetch()} /> : query.data.items.length === 0 ? <EmptyState title="No recurring work" description="Create a cron schedule to launch routine agent tasks automatically." /> : <div className="space-y-2">{query.data.items.map((item) => <ResourceRow key={item.id} icon={<Clock3 className={cn("h-4 w-4", item.enabled && "text-signal-400")} />} title={item.name} meta={`${item.schedule_expr} · ${backendLabel(item.backend)}`} detail={<div className="space-y-3 text-xs text-slate-500"><p className="leading-5">{item.prompt}</p><p>Last run: {formatDateTime(item.last_run_at)}{item.last_status ? ` · ${item.last_status}` : ""}</p></div>} actions={<div className="flex items-center gap-1"><button role="switch" aria-checked={item.enabled} onClick={() => toggle.mutate({ id: item.id, enabled: !item.enabled })} className={cn("relative h-6 w-11 rounded-full border transition", item.enabled ? "border-signal-400/30 bg-signal-400/20" : "border-white/10 bg-white/[0.04]")}><motion.span layout className={cn("absolute top-1 h-3.5 w-3.5 rounded-full", item.enabled ? "left-6 bg-signal-400" : "left-1 bg-slate-600")} /></button><DeleteButton label={item.name} loading={remove.isPending} onDelete={() => remove.mutate(item.id)} /></div>} />)}</div>}
    <Modal open={open} onClose={() => setOpen(false)} title="Create a schedule" description="Use a standard five-field cron expression." wide><form onSubmit={(event) => { event.preventDefault(); if (!name.trim() || schedule.trim().split(/\s+/).length !== 5 || !prompt.trim()) return setError("Enter a name, five-field cron expression, and task prompt."); setError(""); create.mutate(); }} className="space-y-5"><div className="grid gap-4 sm:grid-cols-2"><div><label className="label" htmlFor="cron-name">Schedule name</label><input id="cron-name" className="field" value={name} onChange={(e) => setName(e.target.value)} /></div><div><label className="label" htmlFor="cron-expression">Cron expression</label><input id="cron-expression" className="field font-mono" value={schedule} onChange={(e) => setSchedule(e.target.value)} /></div></div><div><label className="label" htmlFor="cron-prompt">Task prompt</label><textarea id="cron-prompt" className="field min-h-32" value={prompt} onChange={(e) => setPrompt(e.target.value)} /></div><div className="grid gap-4 sm:grid-cols-2"><div><label className="label">Backend</label><Select label="Select backend" value={backend} onChange={(value) => { setBackend(value as AgentBackend); setModel(""); }} options={[{ value: "claude_code", label: "Claude Code" }, { value: "codex", label: "Codex" }]} /></div><div><label className="label">Model <span className="text-slate-600">— optional</span></label><Select label={modelCatalog.isPending ? "Discovering models" : "Select a model"} value={model} onChange={setModel} options={[{ value: "", label: "Runtime default" }, ...(modelCatalog.data?.items.map((item) => ({ value: item.id, label: item.label, description: item.id })) ?? [])]} /></div></div><FormError message={error} /><div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" variant="primary" loading={create.isPending}>Activate schedule</Button></div></form></Modal>
  </Panel>;
}

export function SecretPanel({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false); const [keyName, setKeyName] = useState(""); const [value, setValue] = useState(""); const [error, setError] = useState("");
  const queryClient = useQueryClient(); const toast = useToast();
  const query = useQuery({ queryKey: ["secrets", projectId], queryFn: () => api.secrets(projectId) });
  const save = useMutation({ mutationFn: () => api.putSecret(projectId, keyName.trim(), value), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["secrets", projectId] }); setOpen(false); setKeyName(""); setValue(""); toast("Secret encrypted and stored", "success"); }, onError: (cause: Error) => setError(cause.message) });
  const remove = useMutation({ mutationFn: api.deleteSecret.bind(null, projectId), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["secrets", projectId] }); toast("Secret deleted", "success"); }, onError: (cause: Error) => toast(cause.message, "error") });
  return <Panel title="Secrets vault" description="Encrypted values are write-only and never returned by the API." action={<Button variant="primary" size="sm" onClick={() => setOpen(true)}><Plus className="h-4 w-4" /> Store secret</Button>}>
    <div className="mb-5 flex items-start gap-3 rounded-xl border border-signal-400/10 bg-signal-400/[0.035] p-4"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-signal-400" /><p className="text-xs leading-5 text-slate-400">Values are encrypted at rest. This interface shows key names and creation dates only.</p></div>
    {query.isPending ? <ListLoading /> : query.isError ? <ErrorState message={query.error.message} retry={() => query.refetch()} /> : query.data.items.length === 0 ? <EmptyState title="Vault is empty" description="Store credentials that agents or MCP servers need during execution." /> : <div className="space-y-2">{query.data.items.map((item) => <ResourceRow key={item.id} icon={<FileKey2 className="h-4 w-4" />} title={item.key_name} meta={`Stored ${formatRelativeTime(item.created_at)}`} actions={<DeleteButton label={item.key_name} loading={remove.isPending} onDelete={() => remove.mutate(item.key_name)} />} />)}</div>}
    <Modal open={open} onClose={() => setOpen(false)} title="Store a secret" description="Saving an existing key replaces its encrypted value."><form onSubmit={(event) => { event.preventDefault(); if (!keyName.trim() || !value) return setError("Key name and value are required."); setError(""); save.mutate(); }} className="space-y-5"><div><label className="label" htmlFor="secret-key">Key name</label><div className="relative"><KeyRound className="absolute left-3.5 top-3.5 h-4 w-4 text-slate-600" /><input id="secret-key" className="field pl-10 font-mono uppercase" value={keyName} onChange={(e) => setKeyName(e.target.value.replace(/\s/g, "_"))} autoComplete="off" /></div></div><div><label className="label" htmlFor="secret-value">Secret value</label><input id="secret-value" type="password" className="field font-mono" value={value} onChange={(e) => setValue(e.target.value)} autoComplete="new-password" /></div><FormError message={error} /><div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" variant="primary" loading={save.isPending}>Encrypt and store</Button></div></form></Modal>
  </Panel>;
}
