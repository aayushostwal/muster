"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Bot, Code2, Download, FileText, FolderCode, Network, Pencil, Plus, Search, ShieldCheck, Sparkles, Tag, Trash2, X } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import { ImportCapabilitiesModal } from "@/components/registry/import-capabilities-modal";
import { Button } from "@/components/ui/button";
import { MarkdownContent } from "@/components/ui/markdown-content";
import { Modal } from "@/components/ui/modal";
import { Select } from "@/components/ui/select";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { collectSkillTags, filterRegistryResources, normalizeSkillTags, type RegistryKind as Kind, type RegistryResource as Resource, type RegistryStatusFilter } from "@/lib/registry";
import type { AgentProfile, DirectoryResource, GlobalMcpServer, GlobalTool, ListResponse, McpConfig, Skill, ToolRuleConfig } from "@/lib/types";
import { backendLabel, cn, formatRelativeTime } from "@/lib/utils";

const meta = {
  agents: { title: "Agent profiles", description: "Portable roles and system prompts for Claude and Codex.", singular: "agent", icon: Bot },
  skills: { title: "Skills library", description: "Tagged instruction modules available to Claude and Codex when invoked.", singular: "skill", icon: Sparkles },
  tools: { title: "Tool permissions", description: "Safe runtime capabilities inherited by every project, with project-level overrides.", singular: "tool", icon: Code2 },
  mcp: { title: "MCP connectors", description: "Protocol servers attached to both Claude and Codex unless disabled for a project.", singular: "connector", icon: Network },
  directories: { title: "Directory registry", description: "Approved filesystem roots. Projects receive access through explicit bindings.", singular: "directory", icon: FolderCode },
};

export function RegistryManager({ kind }: { kind: Kind }) {
  const [editing, setEditing] = useState<Resource | null | "new">(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<RegistryStatusFilter>("all");
  const [tags, setTags] = useState<string[]>([]);
  const queryClient = useQueryClient();
  const toast = useToast();
  const details = meta[kind];
  const Icon = details.icon;
  const query = useQuery<ListResponse<Resource>>({
    queryKey: ["registry", kind],
    queryFn: async () => {
      if (kind === "agents") return api.agents();
      if (kind === "skills") return api.skills();
      if (kind === "tools") return api.globalTools();
      if (kind === "mcp") return api.globalMcp();
      return api.globalDirectories();
    },
  });
  const resources = useMemo(() => query.data?.items ?? [], [query.data?.items]);
  const selected = resources.find((resource) => resource.id === selectedId) ?? null;
  const availableTags = useMemo(() => collectSkillTags(resources), [resources]);
  const visible = useMemo(() => filterRegistryResources(resources, kind, search, status, tags), [kind, resources, search, status, tags]);
  const filtered = Boolean(search.trim() || status !== "all" || tags.length);
  const remove = useMutation({
    mutationFn: (id: string) => kind === "agents" ? api.deleteAgent(id) : kind === "skills" ? api.deleteSkill(id) : kind === "tools" ? api.deleteGlobalTool(id) : kind === "mcp" ? api.deleteGlobalMcp(id) : api.deleteGlobalDirectory(id),
    onSuccess: (_result, id) => {
      if (selectedId === id) setSelectedId(null);
      queryClient.invalidateQueries({ queryKey: ["registry", kind] });
      queryClient.invalidateQueries({ queryKey: ["capabilities"] });
      toast(`${details.singular} deleted`, "success");
    },
    onError: (error: Error) => toast(error.message, "error"),
  });
  const clearFilters = () => { setSearch(""); setStatus("all"); setTags([]); };

  return <div className="mx-auto max-w-7xl px-5 py-7 md:px-8 md:py-10">
    <div className="surface relative overflow-hidden rounded-panel px-6 py-7 md:px-8">
      <div className="absolute right-0 top-0 h-40 w-40 rounded-full bg-signal-400/[0.05] blur-3xl" />
      <div className="relative flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
        <div>
          <div className="mb-4 grid h-11 w-11 place-items-center rounded-xl border border-signal-400/15 bg-signal-400/[0.06] text-signal-400"><Icon className="h-5 w-5" /></div>
          <p className="eyebrow">Global registry</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.04em] text-white">{details.title}</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">{details.description}</p>
          {kind === "tools" && <div className="mt-4 inline-flex items-center gap-2 rounded-lg border border-signal-400/10 bg-signal-400/[0.035] px-3 py-2 text-[0.68rem] text-slate-400"><ShieldCheck className="h-3.5 w-3.5 text-signal-400" /> Codex commands remain constrained to the workspace-write sandbox.</div>}
        </div>
        <div className="flex flex-wrap gap-2">
          {kind !== "directories" && kind !== "tools" && <Button onClick={() => setImporting(true)}><Download className="h-4 w-4" /> Import</Button>}
          <Button variant="primary" onClick={() => setEditing("new")}><Plus className="h-4 w-4" /> Add {details.singular}</Button>
        </div>
      </div>
    </div>

    {query.isSuccess && resources.length > 0 && <div className="surface mt-5 rounded-panel p-3 md:p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <label className="relative min-w-0 flex-1">
          <span className="sr-only">Search {details.title.toLowerCase()}</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-600" />
          <input value={search} onChange={(event) => setSearch(event.target.value)} className="field h-10 pl-9" placeholder={`Search names, descriptions, and ${kind === "skills" ? "instructions" : kind === "agents" ? "prompts" : "configuration"}…`} />
        </label>
        {kind !== "directories" && <div className="flex rounded-xl border border-white/[0.07] bg-black/10 p-1">
          {(["all", "enabled", "disabled"] as RegistryStatusFilter[]).map((value) => <button key={value} type="button" onClick={() => setStatus(value)} className={cn("rounded-lg px-3 py-1.5 text-[0.68rem] capitalize transition", status === value ? "bg-white/[0.09] text-white" : "text-slate-600 hover:text-slate-300")}>{value}</button>)}
        </div>}
        {filtered && <Button variant="ghost" size="sm" onClick={clearFilters}><X className="h-3.5 w-3.5" /> Clear</Button>}
      </div>
      {kind === "skills" && availableTags.length > 0 && <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-white/[0.06] pt-3"><span className="mr-1 flex items-center gap-1 text-[0.62rem] uppercase tracking-wider text-slate-700"><Tag className="h-3 w-3" /> Tags</span>{availableTags.map((tag) => <button key={tag} type="button" onClick={() => setTags((current) => current.includes(tag) ? current.filter((item) => item !== tag) : [...current, tag])} aria-pressed={tags.includes(tag)} className={cn("rounded-full border px-2.5 py-1 text-[0.65rem] transition", tags.includes(tag) ? "border-signal-400/25 bg-signal-400/[0.09] text-signal-300" : "border-white/[0.07] text-slate-500 hover:border-white/15 hover:text-slate-300")}>{tag}</button>)}</div>}
    </div>}

    <div className={cn("mt-4 grid items-start gap-4", selected && "xl:grid-cols-[minmax(0,1.55fr)_minmax(22rem,0.85fr)]")}>
      <div>
        {query.isPending && <div className="space-y-2">{Array.from({ length: 5 }).map((_, index) => <Skeleton key={index} className="h-24" />)}</div>}
        {query.isError && <ErrorState message={query.error.message} retry={() => query.refetch()} />}
        {query.isSuccess && resources.length === 0 && <EmptyState title={`No ${details.title.toLowerCase()} yet`} description={`Add a ${details.singular} to make it available across Muster.`} action={<Button variant="primary" onClick={() => setEditing("new")}><Plus className="h-4 w-4" /> Add {details.singular}</Button>} />}
        {query.isSuccess && resources.length > 0 && visible.length === 0 && <EmptyState title="No matching resources" description="Clear a filter or try a broader search." action={<Button onClick={clearFilters}>Clear filters</Button>} />}
        {query.isSuccess && visible.length > 0 && <div className="overflow-hidden rounded-panel border border-white/[0.08] bg-white/[0.015]">
          <div className="flex items-center justify-between border-b border-white/[0.07] px-4 py-2.5"><p className="text-xs text-slate-500">{visible.length} of {resources.length} {resources.length === 1 ? details.singular : details.title.toLowerCase()}</p><p className="hidden text-[0.62rem] text-slate-700 sm:block">Select a row to inspect its full configuration</p></div>
          <div className="divide-y divide-white/[0.06]">{visible.map((resource) => <RegistryRow key={resource.id} kind={kind} resource={resource} selected={selectedId === resource.id} onSelect={() => setSelectedId(resource.id)} onEdit={() => setEditing(resource)} onDelete={() => remove.mutate(resource.id)} />)}</div>
        </div>}
      </div>
      {selected && <RegistryInspector kind={kind} resource={selected} onClose={() => setSelectedId(null)} onEdit={() => setEditing(selected)} />}
    </div>

    {editing && <RegistryForm key={editing === "new" ? "new" : editing.id} kind={kind} resource={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    {kind !== "directories" && kind !== "tools" && <ImportCapabilitiesModal open={importing} onClose={() => setImporting(false)} initialKind={kind === "agents" ? "agent" : kind === "skills" ? "skill" : "mcp"} />}
  </div>;
}

function RegistryRow({ kind, resource, selected, onSelect, onEdit, onDelete }: { kind: Kind; resource: Resource; selected: boolean; onSelect: () => void; onEdit: () => void; onDelete: () => void }) {
  const [armed, setArmed] = useState(false);
  const Icon = meta[kind].icon;
  const enabled = "enabled" in resource ? resource.enabled : true;
  const detail = resourceDetail(kind, resource);
  const skill = kind === "skills" ? resource as Skill : null;
  return <motion.article layout className={cn("group flex items-stretch transition-colors", selected ? "bg-signal-400/[0.045]" : "hover:bg-white/[0.025]")}>
    <button type="button" onClick={onSelect} aria-pressed={selected} className="flex min-w-0 flex-1 items-start gap-3 px-4 py-4 text-left md:items-center">
      <div className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-xl border", selected ? "border-signal-400/20 bg-signal-400/[0.08] text-signal-300" : "border-white/[0.07] bg-white/[0.025] text-slate-500")}><Icon className="h-4 w-4" /></div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2"><h2 className="truncate text-sm font-medium text-white">{resource.name}</h2>{"enabled" in resource && <span className={cn("rounded-full px-2 py-0.5 text-[0.58rem]", enabled ? "bg-signal-400/[0.08] text-signal-300" : "bg-white/[0.045] text-slate-600")}>{enabled ? "Enabled" : "Disabled"}</span>}{kind === "agents" && <span className="rounded-full border border-pulse-400/15 bg-pulse-400/[0.05] px-2 py-0.5 text-[0.58rem] text-pulse-300">Claude + Codex</span>}</div>
        <p className="mt-1 line-clamp-1 text-xs text-slate-500">{resource.description || "No description"}</p>
        {skill && skill.tags.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{skill.tags.slice(0, 4).map((tag) => <span key={tag} className="rounded-md bg-white/[0.045] px-1.5 py-0.5 text-[0.58rem] text-slate-500">{tag}</span>)}{skill.tags.length > 4 && <span className="text-[0.58rem] text-slate-700">+{skill.tags.length - 4}</span>}</div>}
      </div>
      <div className="hidden w-44 shrink-0 md:block"><p className="text-xs capitalize text-slate-400">{detail}</p><p className="mt-1 font-mono text-[0.58rem] text-slate-700">Updated {formatRelativeTime(resource.updated_at)}</p></div>
    </button>
    <div className="flex shrink-0 items-center gap-1 pr-3"><Button size="icon" variant="ghost" onClick={onEdit} aria-label={`Edit ${resource.name}`}><Pencil className="h-3.5 w-3.5" /></Button><Button size={armed ? "sm" : "icon"} variant={armed ? "danger" : "ghost"} onClick={() => armed ? onDelete() : setArmed(true)} onBlur={() => setArmed(false)} aria-label={armed ? `Confirm deletion of ${resource.name}` : `Delete ${resource.name}`}><Trash2 className="h-3.5 w-3.5" />{armed && "Confirm"}</Button></div>
  </motion.article>;
}

function RegistryInspector({ kind, resource, onClose, onEdit }: { kind: Kind; resource: Resource; onClose: () => void; onEdit: () => void }) {
  const Icon = meta[kind].icon;
  const content = kind === "agents" ? (resource as AgentProfile).system_prompt : kind === "skills" ? (resource as Skill).instructions : null;
  return <aside className="surface overflow-hidden rounded-panel xl:sticky xl:top-6 xl:max-h-[calc(100vh-3rem)] xl:overflow-y-auto">
    <div className="flex items-start gap-3 border-b border-white/[0.07] p-5"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-signal-400/15 bg-signal-400/[0.06] text-signal-400"><Icon className="h-4 w-4" /></div><div className="min-w-0 flex-1"><p className="eyebrow">{meta[kind].singular} details</p><h2 className="mt-1 truncate text-lg font-semibold text-white">{resource.name}</h2></div><Button size="icon" variant="ghost" onClick={onClose} aria-label="Close details"><X className="h-4 w-4" /></Button></div>
    <div className="space-y-5 p-5">
      <p className="text-sm leading-6 text-slate-400">{resource.description || "No description provided."}</p>
      {kind === "agents" && <div className="rounded-xl border border-pulse-400/15 bg-pulse-400/[0.035] px-3 py-2 text-xs text-pulse-200">Portable profile · available to Claude and Codex</div>}
      {kind === "skills" && <div className="flex flex-wrap gap-1.5">{(resource as Skill).tags.length ? (resource as Skill).tags.map((tag) => <span key={tag} className="rounded-full border border-white/[0.08] px-2.5 py-1 text-[0.65rem] text-slate-400">{tag}</span>) : <span className="text-xs text-slate-600">No tags</span>}</div>}
      {content && <section><div className="mb-2 flex items-center justify-between"><h3 className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-slate-500"><FileText className="h-3.5 w-3.5" />{kind === "agents" ? "System prompt" : "Instructions"}</h3><span className="font-mono text-[0.58rem] text-slate-700">{content.length.toLocaleString()} chars</span></div><div className="max-h-[28rem] overflow-y-auto rounded-xl border border-white/[0.07] bg-black/15 p-4"><MarkdownContent content={content} className="text-xs leading-5" /></div></section>}
      {kind === "mcp" && <ConfigDetails values={mcpDetails(resource as GlobalMcpServer)} />}
      {kind === "tools" && <ConfigDetails values={Object.entries((resource as GlobalTool).config).map(([key, value]) => [key, Array.isArray(value) ? value.join(" ") : String(value ?? "—")])} />}
      {kind === "directories" && <ConfigDetails values={[["Path", (resource as DirectoryResource).path]]} />}
      <div className="flex items-center justify-between border-t border-white/[0.07] pt-4"><p className="font-mono text-[0.6rem] text-slate-700">Updated {formatRelativeTime(resource.updated_at)}</p><Button size="sm" onClick={onEdit}><Pencil className="h-3.5 w-3.5" /> Edit</Button></div>
    </div>
  </aside>;
}

function ConfigDetails({ values }: { values: Array<[string, string]> }) {
  return <dl className="space-y-2">{values.map(([label, value]) => <div key={label} className="rounded-xl border border-white/[0.06] bg-black/10 px-3 py-2.5"><dt className="text-[0.58rem] uppercase tracking-wider text-slate-700">{label.replaceAll("_", " ")}</dt><dd className="mt-1 break-all font-mono text-xs text-slate-400">{value || "—"}</dd></div>)}</dl>;
}

function resourceDetail(kind: Kind, resource: Resource): string {
  if (kind === "agents") return `${(resource as AgentProfile).system_prompt.length.toLocaleString()} prompt chars`;
  if (kind === "skills") return `${(resource as Skill).instructions.length.toLocaleString()} instruction chars`;
  if (kind === "mcp") return (resource as GlobalMcpServer).config.transport ?? ((resource as GlobalMcpServer).config.url ? "http" : "stdio");
  if (kind === "tools") { const tool = resource as GlobalTool; return `${tool.config.decision} · ${tool.config.backend === "all" ? "Claude + Codex" : backendLabel(tool.config.backend)}`; }
  return (resource as DirectoryResource).path;
}

function mcpDetails(connector: GlobalMcpServer): Array<[string, string]> {
  return [
    ["Transport", connector.config.transport ?? (connector.config.url ? "http" : "stdio")],
    ["Endpoint", connector.config.url ?? connector.config.command ?? "—"],
    ["Arguments", connector.config.args?.join(" ") || "—"],
    ["Environment", Object.keys(connector.config.env ?? {}).join(", ") || "—"],
  ];
}

function RegistryForm({ kind, resource, onClose }: { kind: Kind; resource: Resource | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [error, setError] = useState("");
  const [preview, setPreview] = useState(false);
  const [name, setName] = useState(resource?.name ?? "");
  const [description, setDescription] = useState(resource?.description ?? "");
  const [path, setPath] = useState(kind === "directories" && resource ? (resource as DirectoryResource).path : "");
  const agent = kind === "agents" ? resource as AgentProfile | null : null;
  const connector = kind === "mcp" ? resource as GlobalMcpServer | null : null;
  const skill = kind === "skills" ? resource as Skill | null : null;
  const tool = kind === "tools" ? resource as GlobalTool | null : null;
  const [systemPrompt, setSystemPrompt] = useState(agent?.system_prompt ?? "");
  const [enabled, setEnabled] = useState("enabled" in (resource ?? {}) ? Boolean((resource as AgentProfile).enabled) : true);
  const [instructions, setInstructions] = useState(skill?.instructions ?? "");
  const [skillTags, setSkillTags] = useState(skill?.tags.join(", ") ?? "");
  const [transport, setTransport] = useState<"stdio" | "http" | "sse">(connector?.config.transport ?? (connector?.config.url ? "http" : "stdio"));
  const [command, setCommand] = useState(connector?.config.command ?? "");
  const [args, setArgs] = useState(connector?.config.args?.join(" ") ?? "");
  const [env, setEnv] = useState(connector ? Object.entries(connector.config.env ?? {}).map(([key, value]) => `${key}=${value}`).join("\n") : "");
  const [url, setUrl] = useState(connector?.config.url ?? "");
  const [headers, setHeaders] = useState(connector ? Object.entries(connector.config.headers ?? {}).map(([key, value]) => `${key}=${value}`).join("\n") : "");
  const [bearerTokenEnv, setBearerTokenEnv] = useState(connector?.config.bearer_token_env_var ?? "");
  const [toolBackend, setToolBackend] = useState<ToolRuleConfig["backend"]>(tool?.config.backend ?? "all");
  const [decision, setDecision] = useState<ToolRuleConfig["decision"]>(tool?.config.decision ?? "allow");
  const [claudePattern, setClaudePattern] = useState(tool?.config.claude_pattern ?? "");
  const [codexPrefix, setCodexPrefix] = useState(tool?.config.codex_prefix.join(" ") ?? "");
  const save = useMutation({ mutationFn: async () => {
    if (!name.trim()) throw new Error("Name is required.");
    if (kind === "directories") { if (!path.startsWith("/")) throw new Error("Use an absolute directory path."); const body = { name: name.trim(), path, description: description.trim() || null }; return resource ? api.updateGlobalDirectory(resource.id, body) : api.createGlobalDirectory(body); }
    if (kind === "skills") { if (!instructions.trim()) throw new Error("Skill instructions are required."); const normalized = normalizeSkillTags(skillTags.split(",")); if (normalized.error) throw new Error(normalized.error); const body = { name: name.trim(), description: description.trim() || null, instructions, tags: normalized.tags, enabled }; return resource ? api.updateSkill(resource.id, body) : api.createSkill(body); }
    if (kind === "tools") { if (toolBackend !== "codex" && !claudePattern.trim()) throw new Error("A Claude tool pattern is required."); if (toolBackend !== "claude_code" && !codexPrefix.trim()) throw new Error("A Codex command prefix is required."); const config = { backend: toolBackend, decision, claude_pattern: toolBackend === "codex" ? null : claudePattern.trim(), codex_prefix: toolBackend === "claude_code" ? [] : codexPrefix.trim().split(/\s+/).filter(Boolean) }; const body = { name: name.trim(), description: description.trim() || null, config, enabled }; return resource ? api.updateGlobalTool(resource.id, body) : api.createGlobalTool(body); }
    if (kind === "mcp") { if (transport === "stdio" && !command.trim()) throw new Error("Connector command is required."); if (transport !== "stdio" && !url.trim()) throw new Error("Connector URL is required."); const parsePairs = (value: string) => Object.fromEntries(value.split("\n").filter(Boolean).map((line) => { const [key, ...rest] = line.split("="); return [key.trim(), rest.join("=").trim()]; })); const config: McpConfig = transport === "stdio" ? { transport, command: command.trim(), args: args.split(/\s+/).filter(Boolean), env: parsePairs(env), headers: {} } : { transport, command: null, args: [], env: {}, url: url.trim(), headers: parsePairs(headers), bearer_token_env_var: bearerTokenEnv.trim() || null }; const body = { name: name.trim(), description: description.trim() || null, enabled, config }; return resource ? api.updateGlobalMcp(resource.id, body) : api.createGlobalMcp(body); }
    if (!systemPrompt.trim()) throw new Error("Agent system prompt is required."); const body = { name: name.trim(), description: description.trim() || null, system_prompt: systemPrompt, config: {}, enabled }; return resource ? api.updateAgent(resource.id, body) : api.createAgent(body);
  }, onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["registry", kind] }); queryClient.invalidateQueries({ queryKey: ["capabilities"] }); toast(`${meta[kind].singular} ${resource ? "updated" : "created"}`, "success"); onClose(); }, onError: (cause: Error) => setError(cause.message) });
  const submit = (event: FormEvent) => { event.preventDefault(); setError(""); save.mutate(); };
  const markdown = kind === "agents" ? systemPrompt : instructions;
  return <Modal open onClose={onClose} title={`${resource ? "Edit" : "Add"} ${meta[kind].singular}`} description={kind === "agents" ? "This portable profile is available to Claude and Codex." : "Changes become available to project sessions immediately."} wide><form onSubmit={submit} className="space-y-5">
    <div className="grid gap-4 sm:grid-cols-2"><div><label className="label" htmlFor="registry-name">Name</label><input id="registry-name" className="field" value={name} onChange={(event) => setName(event.target.value)} autoFocus /></div>{kind === "directories" && <div><label className="label" htmlFor="registry-path">Absolute path</label><input id="registry-path" className="field font-mono" value={path} onChange={(event) => setPath(event.target.value)} /></div>}</div>
    <div><label className="label" htmlFor="registry-description">Description</label><textarea id="registry-description" className="field min-h-20" value={description} onChange={(event) => setDescription(event.target.value)} /></div>
    {(kind === "agents" || kind === "skills") && <><div className="flex items-center justify-between"><label className="label mb-0" htmlFor={kind === "agents" ? "agent-prompt" : "skill-instructions"}>{kind === "agents" ? "System prompt" : "Instructions"}</label><div className="flex rounded-lg border border-white/[0.07] p-0.5"><button type="button" onClick={() => setPreview(false)} className={cn("rounded-md px-2.5 py-1 text-[0.65rem]", !preview ? "bg-white/[0.09] text-white" : "text-slate-600")}>Write</button><button type="button" onClick={() => setPreview(true)} className={cn("rounded-md px-2.5 py-1 text-[0.65rem]", preview ? "bg-white/[0.09] text-white" : "text-slate-600")}>Preview</button></div></div>{preview ? <div className="min-h-52 rounded-xl border border-white/[0.08] bg-black/15 p-4"><MarkdownContent content={markdown || "_Nothing to preview yet._"} /></div> : <textarea id={kind === "agents" ? "agent-prompt" : "skill-instructions"} className="field min-h-52 font-mono text-xs leading-6" value={markdown} onChange={(event) => kind === "agents" ? setSystemPrompt(event.target.value) : setInstructions(event.target.value)} />}</>}
    {kind === "skills" && <div><label className="label" htmlFor="skill-tags">Tags</label><input id="skill-tags" className="field" value={skillTags} onChange={(event) => setSkillTags(event.target.value)} placeholder="review, security, deployment" /><p className="mt-1.5 text-[0.62rem] text-slate-600">Comma-separated · up to 12 tags</p></div>}
    {kind === "tools" && <><div className="grid gap-4 sm:grid-cols-2"><div><label className="label">Runtime</label><Select label="Select runtime" value={toolBackend} onChange={(value) => setToolBackend(value as ToolRuleConfig["backend"])} options={[{ value: "all", label: "Claude + Codex" }, { value: "claude_code", label: "Claude Code" }, { value: "codex", label: "Codex" }]} /></div><div><label className="label">Decision</label><Select label="Select decision" value={decision} onChange={(value) => setDecision(value as ToolRuleConfig["decision"])} options={[{ value: "allow", label: "Allow without asking" }, { value: "deny", label: "Always deny" }]} /></div></div>{toolBackend !== "codex" && <div><label className="label" htmlFor="global-tool-claude">Claude tool pattern</label><input id="global-tool-claude" className="field font-mono" value={claudePattern} onChange={(event) => setClaudePattern(event.target.value)} placeholder="Read or Bash(git status *)" /></div>}{toolBackend !== "claude_code" && <div><label className="label" htmlFor="global-tool-codex">Codex command prefix</label><input id="global-tool-codex" className="field font-mono" value={codexPrefix} onChange={(event) => setCodexPrefix(event.target.value)} placeholder="git status" /><p className="mt-2 text-[0.65rem] text-slate-600">Commands still run inside Codex&apos;s workspace-write sandbox.</p></div>}</>}
    {kind === "mcp" && <><div className="rounded-xl border border-pulse-400/15 bg-pulse-400/[0.035] px-3 py-2 text-xs text-pulse-200">This connector will be configured for both Claude and Codex.</div><div><label className="label">Transport</label><Select label="Select transport" value={transport} onChange={(value) => setTransport(value as "stdio" | "http" | "sse")} options={[{ value: "stdio", label: "Local process (stdio)" }, { value: "http", label: "Streamable HTTP" }, { value: "sse", label: "Server-sent events (SSE)" }]} /></div>{transport === "stdio" ? <><div><label className="label" htmlFor="mcp-command-global">Command</label><input id="mcp-command-global" className="field font-mono" value={command} onChange={(event) => setCommand(event.target.value)} /></div><div><label className="label" htmlFor="mcp-args-global">Arguments</label><input id="mcp-args-global" className="field font-mono" value={args} onChange={(event) => setArgs(event.target.value)} /></div><div><label className="label" htmlFor="mcp-env-global">Environment · one KEY=value per line</label><textarea id="mcp-env-global" className="field min-h-28 font-mono" value={env} onChange={(event) => setEnv(event.target.value)} /></div></> : <><div><label className="label" htmlFor="mcp-url-global">Server URL</label><input id="mcp-url-global" type="url" className="field font-mono" value={url} onChange={(event) => setUrl(event.target.value)} /></div><div><label className="label" htmlFor="mcp-headers-global">HTTP headers · one KEY=value per line</label><textarea id="mcp-headers-global" className="field min-h-24 font-mono" value={headers} onChange={(event) => setHeaders(event.target.value)} /></div><div><label className="label" htmlFor="mcp-bearer-global">Bearer-token environment variable</label><input id="mcp-bearer-global" className="field font-mono" placeholder="MCP_TOKEN" value={bearerTokenEnv} onChange={(event) => setBearerTokenEnv(event.target.value)} /></div></>}</>}
    {kind !== "directories" && <label className="flex cursor-pointer items-center justify-between rounded-xl border border-white/[0.08] bg-white/[0.02] px-4 py-3"><span><span className="block text-sm text-slate-200">Enabled globally</span><span className="mt-0.5 block text-[0.65rem] text-slate-600">Projects can override this setting.</span></span><button type="button" role="switch" aria-checked={enabled} onClick={() => setEnabled((value) => !value)} className={cn("relative h-6 w-11 rounded-full border transition", enabled ? "border-signal-400/30 bg-signal-400/20" : "border-white/10 bg-white/[0.04]")}><span className={cn("absolute top-1 h-3.5 w-3.5 rounded-full transition-all", enabled ? "left-6 bg-signal-400" : "left-1 bg-slate-600")} /></button></label>}
    {error && <p role="alert" className="rounded-xl border border-red-400/15 bg-red-400/[0.05] px-3 py-2.5 text-xs text-red-300">{error}</p>}
    <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" variant="primary" loading={save.isPending}>{resource ? "Save changes" : `Create ${meta[kind].singular}`}</Button></div>
  </form></Modal>;
}
