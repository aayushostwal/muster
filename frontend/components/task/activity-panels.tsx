"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Bot, Braces, Check, ChevronDown, CircleDot, Copy, FileDiff, Network, ScrollText, Sparkles, TerminalSquare } from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/states";
import type { TaskEvent, TaskInvocation } from "@/lib/types";
import { cn, formatDateTime } from "@/lib/utils";

const eventVisual = {
  invocation: { icon: CircleDot, color: "text-signal-400" },
  log: { icon: TerminalSquare, color: "text-slate-500" },
  tool_call: { icon: Braces, color: "text-pulse-400" },
  tool_result: { icon: Check, color: "text-emerald-400" },
  agent_call: { icon: Network, color: "text-amber-400" },
  reasoning: { icon: Sparkles, color: "text-purple-400" },
  diff: { icon: FileDiff, color: "text-blue-400" },
};

export function ActivityFeed({ events }: { events: TaskEvent[] }) {
  const [filter, setFilter] = useState("all");
  const visible = useMemo(() => events.filter((event) => filter === "all" || event.kind === filter), [events, filter]);
  const filters = [{ value: "all", label: "All activity" }, { value: "tool_call", label: "Tools" }, { value: "diff", label: "Diffs" }, { value: "reasoning", label: "Reasoning" }, { value: "log", label: "Logs" }, { value: "agent_call", label: "Agents" }];
  return <div className="h-full overflow-y-auto px-4 py-4"><div className="mx-auto max-w-3xl"><div className="mb-4 flex gap-1 overflow-x-auto rounded-xl border border-white/[0.07] bg-black/15 p-1">{filters.map((item) => <button key={item.value} onClick={() => setFilter(item.value)} className={cn("shrink-0 rounded-lg px-3 py-1.5 text-[0.66rem] font-medium transition", filter === item.value ? "bg-white/[0.08] text-white" : "text-slate-600 hover:text-slate-300")}>{item.label}</button>)}</div>{visible.length === 0 ? <EmptyState title="No execution activity" description="Tool calls, diffs, reasoning, logs, and agent delegation will stream into this timeline." /> : <div className="space-y-2">{visible.map((event) => <ActivityRow key={event.id} event={event} />)}</div>}</div></div>;
}

function ActivityRow({ event }: { event: TaskEvent }) {
  const [open, setOpen] = useState(event.kind === "diff");
  const visual = eventVisual[event.kind as keyof typeof eventVisual] ?? { icon: ScrollText, color: "text-slate-500" }; const Icon = visual.icon;
  return <motion.article layout className="overflow-hidden rounded-xl border border-white/[0.07] bg-white/[0.018]"><button onClick={() => setOpen((value) => !value)} className="flex w-full items-center gap-3 px-3.5 py-3 text-left" aria-expanded={open}><span className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-white/[0.07] bg-white/[0.03]", visual.color)}><Icon className="h-3.5 w-3.5" /></span><span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium text-slate-200">{event.title}</span><span className="mt-0.5 block font-mono text-[0.58rem] uppercase tracking-wider text-slate-700">{event.kind.replace("_", " ")} · {formatDateTime(event.created_at)}</span></span><ChevronDown className={cn("h-4 w-4 text-slate-700 transition-transform", open && "rotate-180")} /></button><AnimatePresence initial={false}>{open && <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden"><div className="border-t border-white/[0.06] bg-black/15 p-3.5">{event.kind === "diff" ? <DiffView content={event.content ?? ""} /> : <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-[0.66rem] leading-5 text-slate-400">{event.content || JSON.stringify(event.event_metadata, null, 2)}</pre>}</div></motion.div>}</AnimatePresence></motion.article>;
}

function DiffView({ content }: { content: string }) {
  return <pre className="max-h-80 overflow-auto rounded-lg bg-ink-950/70 py-2 font-mono text-[0.65rem] leading-5">{content.split("\n").map((line, index) => <div key={`${index}-${line.slice(0, 12)}`} className={cn("px-3 text-slate-500", line.startsWith("+") && !line.startsWith("+++") && "bg-emerald-400/[0.07] text-emerald-300", line.startsWith("-") && !line.startsWith("---") && "bg-red-400/[0.07] text-red-300", line.startsWith("@@") && "text-blue-300")}><span className="mr-3 inline-block w-6 select-none text-right text-slate-800">{index + 1}</span>{line || " "}</div>)}</pre>;
}

export function AgentActivity({ invocations, events }: { invocations: TaskInvocation[]; events: TaskEvent[] }) {
  const agentCalls = events.filter((event) => event.kind === "agent_call");
  return <div className="h-full overflow-y-auto px-4 py-4"><div className="mx-auto max-w-3xl space-y-4">{invocations.length === 0 ? <EmptyState title="No invocations yet" description="Backend sessions and delegated agent work will appear here." /> : invocations.slice().reverse().map((invocation) => <InvocationCard key={invocation.id} invocation={invocation} childEvents={agentCalls.filter((event) => event.invocation_id === invocation.id)} />)}</div></div>;
}

function InvocationCard({ invocation, childEvents }: { invocation: TaskInvocation; childEvents: TaskEvent[] }) {
  const [copied, setCopied] = useState(false); const total = invocation.input_tokens + invocation.output_tokens;
  return <section className="rounded-panel border border-white/[0.08] bg-white/[0.02] p-4"><div className="flex items-start justify-between gap-4"><div className="flex items-start gap-3"><div className="grid h-10 w-10 place-items-center rounded-xl border border-signal-400/15 bg-signal-400/[0.06] text-signal-400"><Bot className="h-4 w-4" /></div><div><div className="flex items-center gap-2"><h3 className="text-sm font-medium text-white">Invocation {invocation.sequence}</h3><span className={cn("rounded-md px-1.5 py-0.5 text-[0.55rem] uppercase tracking-wider", invocation.status === "running" ? "bg-signal-400/10 text-signal-400" : invocation.status === "failed" ? "bg-red-400/10 text-red-400" : "bg-white/[0.05] text-slate-500")}>{invocation.status}</span></div><p className="mt-1 text-[0.65rem] text-slate-600">{invocation.model || "Runtime default"} · {invocation.thinking_level || "default"} thinking</p></div></div><span className="font-mono text-[0.6rem] text-slate-700">{formatDateTime(invocation.started_at)}</span></div><div className="mt-4 grid grid-cols-3 gap-2"><Metric label="Input" value={invocation.input_tokens} /><Metric label="Output" value={invocation.output_tokens} /><Metric label="Cached" value={invocation.cached_tokens} /></div><div className="mt-3 flex items-center justify-between rounded-lg border border-white/[0.06] bg-black/15 px-3 py-2"><div className="min-w-0"><p className="text-[0.56rem] uppercase tracking-wider text-slate-700">Session ID</p><p className="mt-0.5 truncate font-mono text-[0.65rem] text-slate-400">{invocation.session_id || "Awaiting runtime session"}</p></div>{invocation.session_id && <button onClick={async () => { await navigator.clipboard.writeText(invocation.session_id!); setCopied(true); window.setTimeout(() => setCopied(false), 1400); }} className="ml-3 rounded-lg p-2 text-slate-600 hover:bg-white/[0.05] hover:text-white" aria-label="Copy session ID">{copied ? <Check className="h-3.5 w-3.5 text-signal-400" /> : <Copy className="h-3.5 w-3.5" />}</button>}</div>{childEvents.length > 0 && <div className="mt-4 border-l border-amber-400/20 pl-4"><p className="mb-2 text-[0.6rem] font-semibold uppercase tracking-wider text-amber-400">Delegated agents</p><div className="space-y-2">{childEvents.map((event) => <AgentEventRow key={event.id} event={event} />)}</div></div>}<p className="mt-3 text-right font-mono text-[0.58rem] text-slate-700">{total.toLocaleString()} total API tokens</p></section>;
}

function AgentEventRow({ event }: { event: TaskEvent }) {
  const [open, setOpen] = useState(false);
  return <div className="overflow-hidden rounded-lg border border-amber-400/10 bg-amber-400/[0.025]"><button onClick={() => setOpen((value) => !value)} className="flex w-full items-center gap-2 px-3 py-2.5 text-left" aria-expanded={open}><Network className="h-3.5 w-3.5 shrink-0 text-amber-400" /><span className="min-w-0 flex-1 truncate text-xs text-slate-300">{event.title}</span><ChevronDown className={cn("h-3.5 w-3.5 text-slate-700 transition-transform", open && "rotate-180")} /></button><AnimatePresence initial={false}>{open && <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden"><pre className="max-h-52 overflow-auto whitespace-pre-wrap break-words border-t border-white/[0.06] px-3 py-2.5 font-mono text-[0.62rem] leading-5 text-slate-500">{event.content || JSON.stringify(event.event_metadata, null, 2)}</pre></motion.div>}</AnimatePresence></div>;
}

function Metric({ label, value }: { label: string; value: number }) { return <div className="rounded-lg border border-white/[0.06] bg-black/10 px-3 py-2"><p className="text-[0.56rem] uppercase tracking-wider text-slate-700">{label}</p><p className="mt-1 font-mono text-xs text-slate-300">{value.toLocaleString()}</p></div>; }
