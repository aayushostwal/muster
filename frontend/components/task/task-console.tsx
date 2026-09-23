"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  Activity,
  ArrowLeft,
  BrainCircuit,
  CircleStop,
  Clock3,
  FileText,
  History,
  MoreHorizontal,
  Network,
  RefreshCcw,
  RotateCcw,
  Send,
  Settings2,
  Sparkles,
  TerminalSquare,
  Wifi,
  WifiOff,
} from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/drawer";
import { MultiSelect, Select } from "@/components/ui/select";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { Tooltip } from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/toast";
import { ActivityFeed, AgentActivity } from "@/components/task/activity-panels";
import { TaskTokenHud } from "@/components/task/task-token-hud";
import { TerminalFrame, TerminalThread } from "@/components/task/terminal-thread";
import { useTaskStream } from "@/hooks/use-task-stream";
import { api } from "@/lib/api";
import type { ListResponse, Message, RunAttempt, Task, TaskInvocation, TaskStatus } from "@/lib/types";
import { backendLabel, cn, formatDateTime, shortId } from "@/lib/utils";

const statusMeta: Record<TaskStatus, { label: string; color: string }> = {
  queued: { label: "Queued", color: "bg-slate-400" },
  running: { label: "Running", color: "bg-signal-400" },
  waiting_on_you: { label: "Waiting on you", color: "bg-amber-400" },
  done: { label: "Complete", color: "bg-emerald-400" },
  failed: { label: "Failed", color: "bg-red-400" },
  cancelled: { label: "Cancelled", color: "bg-slate-600" },
};

export function TaskConsole({ taskId }: { taskId: string }) {
  const task = useQuery({ queryKey: ["task", taskId], queryFn: () => api.task(taskId), refetchInterval: 10_000 });
  const messages = useQuery({ queryKey: ["messages", taskId], queryFn: () => api.messages(taskId) });
  const attempts = useQuery({ queryKey: ["attempts", taskId], queryFn: () => api.attempts(taskId) });
  const events = useQuery({ queryKey: ["task-events", taskId], queryFn: () => api.taskEvents(taskId) });
  const invocations = useQuery({ queryKey: ["invocations", taskId], queryFn: () => api.invocations(taskId) });
  const project = useQuery({ queryKey: ["project", task.data?.project_id], queryFn: () => api.project(task.data!.project_id), enabled: Boolean(task.data?.project_id) });
  const { connection, tokenUsage } = useTaskStream(taskId);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [mobileActionsOpen, setMobileActionsOpen] = useState(false);
  const [view, setView] = useState<"terminal" | "activity" | "agents">("terminal");
  const queryClient = useQueryClient(); const toast = useToast();
  const action = useMutation({ mutationFn: (name: "cancel" | "restart" | "retry-now") => api.taskAction(taskId, name), onSuccess: (updated) => { queryClient.setQueryData(["task", taskId], updated); toast("Task state updated", "success"); }, onError: (error: Error) => toast(error.message, "error") });

  if (task.isPending) return <div className="mx-auto max-w-screen-2xl space-y-4 p-5 md:p-8"><Skeleton className="h-24" /><Skeleton className="h-[36rem]" /></div>;
  if (task.isError) return <div className="mx-auto max-w-3xl p-6"><ErrorState message={task.error.message} retry={() => task.refetch()} /></div>;
  const current = task.data;
  const latestAttempt = attempts.data?.items.at(-1);
  const retrying = current.status === "running" && latestAttempt?.failure_class === "transient" && latestAttempt.backoff_seconds;

  return (
    <div className="mx-auto flex h-[calc(100dvh-var(--header-height))] max-w-[112rem] flex-col overflow-hidden px-2 py-2 md:px-3 md:py-3">
      <header className="surface flex min-h-14 shrink-0 items-center gap-2 rounded-xl px-2.5 py-2">
        <Tooltip label="Back to board" side="bottom" align="start"><Link href={`/projects/${current.project_id}/board`} className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/[0.08] text-slate-500 transition hover:border-white/15 hover:text-white" aria-label="Back to task board"><ArrowLeft className="h-4 w-4" /></Link></Tooltip>
        <div className="min-w-0 flex-1 px-1">
          <div className="flex min-w-0 items-center gap-1.5 text-[0.62rem] text-slate-600">
            <Link href={`/projects/${current.project_id}/board`} className="max-w-28 truncate transition hover:text-signal-300">{project.data?.name ?? "Project"}</Link>
            <span className="text-slate-800">/</span>
            <span className="font-mono text-[0.56rem] text-slate-700">{shortId(current.id)}</span>
          </div>
          <div className="mt-0.5 flex min-w-0 items-center gap-2">
            <h1 className="truncate text-sm font-semibold text-white">{current.title}</h1>
            <span className="hidden shrink-0 items-center gap-1.5 rounded-md border border-white/[0.06] bg-white/[0.025] px-1.5 py-0.5 text-[0.56rem] text-slate-500 md:inline-flex"><span className={cn("h-1.5 w-1.5 rounded-full", statusMeta[current.status].color, current.status === "running" && "animate-pulse")} />{statusMeta[current.status].label}</span>
            <span className="hidden shrink-0 text-[0.6rem] text-slate-600 xl:inline">{backendLabel(current.backend)}{current.model ? ` · ${current.model}` : ""}</span>
          </div>
        </div>

        <nav className="hidden shrink-0 rounded-lg border border-white/[0.06] bg-black/15 p-1 lg:flex" aria-label="Task views">
          {(["terminal", "activity", "agents"] as const).map((item) => {
            const Icon = item === "terminal" ? TerminalSquare : item === "activity" ? Activity : Network;
            return <button key={item} onClick={() => setView(item)} aria-pressed={view === item} className={cn("flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[0.64rem] font-medium capitalize transition", view === item ? "bg-white/[0.08] text-white" : "text-slate-600 hover:text-slate-300")}><Icon className="h-3.5 w-3.5" />{item}{item === "activity" && events.data?.items.length ? <span className="font-mono text-[0.53rem] text-slate-600">{events.data.items.length}</span> : null}</button>;
          })}
        </nav>

        <TaskTokenHud tokenUsage={tokenUsage} task={current} invocations={invocations.data?.items ?? []} />
        <Tooltip label={connection === "live" ? "Runtime stream connected" : connection === "connecting" ? "Connecting to runtime" : "Runtime stream reconnecting"} side="bottom"><span className={cn("hidden h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/[0.07] bg-white/[0.02] sm:grid", connection === "live" ? "text-signal-400" : "text-slate-600")}>{connection === "live" ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}</span></Tooltip>
        <div className="hidden shrink-0 items-center gap-0.5 border-l border-white/[0.07] pl-1.5 sm:flex">
          {current.status === "failed" && <Tooltip label="Retry now" side="bottom"><Button size="icon" variant="primary" loading={action.isPending} onClick={() => action.mutate("retry-now")} aria-label="Retry task now"><RefreshCcw className="h-3.5 w-3.5" /></Button></Tooltip>}
          {(current.status === "done" || current.status === "cancelled") && <Tooltip label="Restart task" side="bottom"><Button size="icon" loading={action.isPending} onClick={() => action.mutate("restart")} aria-label="Restart task"><RotateCcw className="h-3.5 w-3.5" /></Button></Tooltip>}
          {(current.status === "running" || current.status === "queued" || current.status === "waiting_on_you") && <Tooltip label="Cancel task" side="bottom"><Button size="icon" variant="danger" loading={action.isPending} onClick={() => action.mutate("cancel")} aria-label="Cancel task"><CircleStop className="h-3.5 w-3.5" /></Button></Tooltip>}
          <Tooltip label="Run details" side="bottom"><Button size="icon" variant="ghost" onClick={() => setDetailsOpen(true)} aria-label="Open task details"><History className="h-4 w-4" /></Button></Tooltip>
          <Tooltip label="Task controls" side="bottom"><Button size="icon" variant="ghost" onClick={() => setSettingsOpen(true)} aria-label="Open task settings"><Settings2 className="h-4 w-4" /></Button></Tooltip>
          <Tooltip label="Raw transcript" side="bottom" align="end"><Button className="hidden md:inline-flex" size="icon" variant="ghost" onClick={() => setTranscriptOpen(true)} aria-label="Open raw transcript"><FileText className="h-4 w-4" /></Button></Tooltip>
        </div>
        <Button className="shrink-0 sm:hidden" size="icon" variant="ghost" onClick={() => setMobileActionsOpen(true)} aria-label="Open task actions"><MoreHorizontal className="h-4 w-4" /></Button>
      </header>

      {retrying && <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mt-3 flex items-center justify-between gap-4 rounded-xl border border-amber-400/15 bg-amber-400/[0.045] px-4 py-3"><div className="flex items-center gap-3"><Clock3 className="h-4 w-4 text-amber-400" /><p className="text-xs text-amber-100/70">Transient failure detected. Automatic retry scheduled in {latestAttempt.backoff_seconds} seconds.</p></div><Button size="sm" variant="ghost" onClick={() => action.mutate("retry-now")}>Retry now</Button></motion.div>}

      <div className="mt-2 min-h-0 flex-1">
        <section className="surface flex h-full min-h-0 flex-col overflow-hidden rounded-xl">
          <nav className="flex shrink-0 border-b border-white/[0.06] bg-black/10 p-1.5 lg:hidden" aria-label="Task views">{(["terminal", "activity", "agents"] as const).map((item) => <button key={item} onClick={() => setView(item)} className={cn("flex-1 rounded-md px-3 py-1.5 text-[0.66rem] font-medium capitalize transition", view === item ? "bg-white/[0.08] text-white" : "text-slate-600")}>{item}</button>)}</nav>
          <div className="min-h-0 flex-1 overflow-hidden">{view === "terminal" && <TerminalFrame><TerminalThread task={current} messages={messages.data?.items ?? []} invocations={invocations.data?.items ?? []} loading={messages.isPending} /></TerminalFrame>}{view === "activity" && <ActivityFeed events={events.data?.items ?? []} />}{view === "agents" && <AgentActivity invocations={invocations.data?.items ?? []} events={events.data?.items ?? []} />}</div>
          {view === "terminal" && <Composer taskId={taskId} status={current.status} />}
        </section>
      </div>
      <TaskSettings task={current} open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <TranscriptDrawer taskId={taskId} open={transcriptOpen} onClose={() => setTranscriptOpen(false)} />
      <TaskDetailsDrawer task={current} projectName={project.data?.name} attempts={attempts.data?.items ?? []} invocations={invocations.data?.items ?? []} open={detailsOpen} onClose={() => setDetailsOpen(false)} onOpenTranscript={() => { setDetailsOpen(false); setTranscriptOpen(true); }} />
      <TaskMobileActions task={current} open={mobileActionsOpen} busy={action.isPending} onClose={() => setMobileActionsOpen(false)} onAction={(name) => { setMobileActionsOpen(false); action.mutate(name); }} onOpenDetails={() => { setMobileActionsOpen(false); setDetailsOpen(true); }} onOpenSettings={() => { setMobileActionsOpen(false); setSettingsOpen(true); }} onOpenTranscript={() => { setMobileActionsOpen(false); setTranscriptOpen(true); }} />
    </div>
  );
}

function Composer({ taskId, status }: { taskId: string; status: TaskStatus }) {
  const [value, setValue] = useState(""); const [error, setError] = useState(""); const queryClient = useQueryClient(); const toast = useToast();
  const send = useMutation({
    mutationFn: (content: string) => api.sendMessage(taskId, content),
    onMutate: async (content) => { await queryClient.cancelQueries({ queryKey: ["messages", taskId] }); const previous = queryClient.getQueryData<ListResponse<Message>>(["messages", taskId]); const optimistic: Message = { id: `optimistic-${Date.now()}`, task_id: taskId, sender: "user", content_text: content, media: [], is_blocking_question: false, created_at: new Date().toISOString(), optimistic: true }; queryClient.setQueryData<ListResponse<Message>>(["messages", taskId], { items: [...(previous?.items ?? []), optimistic] }); setValue(""); return { previous }; },
    onError: (cause: Error, _content, context) => { queryClient.setQueryData(["messages", taskId], context?.previous); setError(cause.message); toast("Message was not sent", "error"); },
    onSuccess: (saved) => { queryClient.setQueryData<ListResponse<Message>>(["messages", taskId], (current) => ({ items: [...(current?.items.filter((item) => !item.optimistic) ?? []), saved] })); queryClient.invalidateQueries({ queryKey: ["task", taskId] }); setError(""); },
  });
  const submit = (event: FormEvent) => { event.preventDefault(); const content = value.trim(); if (content && !send.isPending) send.mutate(content); };
  return <form onSubmit={submit} className="border-t border-white/[0.07] bg-black/10 p-3"><div className="mx-auto max-w-3xl"><div className="flex items-end gap-2 rounded-xl border border-white/10 bg-ink-950/70 p-1.5 transition focus-within:border-signal-400/30 focus-within:ring-4 focus-within:ring-signal-400/[0.05]"><textarea value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} rows={1} className="max-h-28 min-h-9 flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-5 text-white placeholder:text-slate-700 focus:outline-none" placeholder={status === "waiting_on_you" ? "Respond to the agent" : "Send a follow-up instruction"} aria-label="Message agent" /><Button type="submit" size="icon" variant="primary" loading={send.isPending} disabled={!value.trim()} aria-label="Send message"><Send className="h-4 w-4" /></Button></div>{error && <p className="mt-2 text-xs text-red-400" role="alert">{error}</p>}<p className="mt-1.5 px-1 text-[0.56rem] text-slate-700">Enter to send · Shift + Enter for a new line</p></div></form>;
}

function TaskDetailsDrawer({
  task,
  projectName,
  attempts,
  invocations,
  open,
  onClose,
  onOpenTranscript,
}: {
  task: Task;
  projectName?: string;
  attempts: RunAttempt[];
  invocations: TaskInvocation[];
  open: boolean;
  onClose: () => void;
  onOpenTranscript: () => void;
}) {
  const latestInvocation = invocations.at(-1);
  return (
    <Drawer open={open} onClose={onClose} title="Run details">
      <div className="space-y-7">
        <section>
          <div className="flex items-center gap-2">
            <History className="h-4 w-4 text-pulse-400" />
            <h3 className="text-sm font-medium text-white">Task context</h3>
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-2">
            <Detail label="Project" value={projectName ?? "Loading project"} />
            <Detail label="Status" value={statusMeta[task.status].label} />
            <Detail label="Runtime" value={backendLabel(task.backend)} />
            <Detail label="Model" value={task.model || "Runtime default"} />
            <Detail label="Created" value={formatDateTime(task.created_at)} />
            <Detail label="Context" value={task.context_strategy} />
          </dl>
          <div className="mt-2 rounded-xl border border-white/[0.06] bg-black/15 px-3 py-2.5">
            <p className="text-[0.56rem] uppercase tracking-wider text-slate-700">Latest session ID</p>
            <p className="mt-1 truncate font-mono text-[0.68rem] text-slate-400">{latestInvocation?.session_id || task.session_id || "Awaiting runtime session"}</p>
          </div>
          <Button className="mt-3 md:hidden" onClick={onOpenTranscript}><FileText className="h-4 w-4" /> Open raw transcript</Button>
        </section>

        <section className="border-t border-white/[0.07] pt-6">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-white">Invocations</h3>
            <span className="font-mono text-[0.62rem] text-slate-600">{invocations.length} total</span>
          </div>
          {invocations.length ? (
            <div className="mt-3 space-y-2">
              {invocations.slice().reverse().map((invocation) => (
                <div key={invocation.id} className="flex items-center gap-3 rounded-xl border border-white/[0.06] bg-white/[0.018] px-3 py-2.5">
                  <span className={cn("h-2 w-2 rounded-full", invocation.status === "running" ? "animate-pulse bg-signal-400" : invocation.status === "failed" ? "bg-red-400" : "bg-slate-600")} />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-slate-300">Invocation {invocation.sequence}</p>
                    <p className="mt-0.5 truncate text-[0.62rem] text-slate-600">{invocation.model || "Runtime default"} · {invocation.thinking_level || "default"} thinking</p>
                  </div>
                  <span className="font-mono text-[0.58rem] text-slate-700">{(invocation.input_tokens + invocation.output_tokens).toLocaleString()} tok</span>
                </div>
              ))}
            </div>
          ) : <p className="mt-3 text-xs text-slate-600">No runtime invocations yet.</p>}
        </section>

        <section className="border-t border-white/[0.07] pt-6">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-white">Retry history</h3>
            <span className="font-mono text-[0.62rem] text-slate-600">{attempts.length} attempts</span>
          </div>
          {attempts.length ? (
            <div className="mt-4 space-y-4">
              {attempts.slice().reverse().map((attempt) => (
                <div key={attempt.id} className="border-l border-white/10 pl-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-mono text-[0.66rem] text-slate-300">Attempt {attempt.attempt_number}</span>
                    <span className={cn("text-[0.56rem] uppercase tracking-wider", attempt.failure_class === "transient" ? "text-amber-400" : attempt.failure_class ? "text-red-400" : "text-slate-600")}>{attempt.failure_class || "started"}</span>
                  </div>
                  <p className="mt-1 text-[0.66rem] leading-5 text-slate-600">{attempt.error_message || "Agent process started"}</p>
                </div>
              ))}
            </div>
          ) : <p className="mt-3 text-xs leading-5 text-slate-600">No failures or retries recorded for this task.</p>}
        </section>
      </div>
    </Drawer>
  );
}

function TaskMobileActions({
  task,
  open,
  busy,
  onClose,
  onAction,
  onOpenDetails,
  onOpenSettings,
  onOpenTranscript,
}: {
  task: Task;
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onAction: (name: "cancel" | "restart" | "retry-now") => void;
  onOpenDetails: () => void;
  onOpenSettings: () => void;
  onOpenTranscript: () => void;
}) {
  return (
    <Drawer open={open} onClose={onClose} title="Task actions">
      <div className="space-y-5">
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
          <div className="flex items-center gap-2"><span className={cn("h-2 w-2 rounded-full", statusMeta[task.status].color, task.status === "running" && "animate-pulse")} /><span className="text-sm font-medium text-white">{statusMeta[task.status].label}</span></div>
          <p className="mt-2 text-xs text-slate-600">{backendLabel(task.backend)} · {task.model || "Runtime default"}</p>
        </div>
        <div className="grid gap-2">
          {task.status === "failed" && <Button variant="primary" loading={busy} onClick={() => onAction("retry-now")}><RefreshCcw className="h-4 w-4" /> Retry now</Button>}
          {(task.status === "done" || task.status === "cancelled") && <Button loading={busy} onClick={() => onAction("restart")}><RotateCcw className="h-4 w-4" /> Restart task</Button>}
          {(task.status === "running" || task.status === "queued" || task.status === "waiting_on_you") && <Button variant="danger" loading={busy} onClick={() => onAction("cancel")}><CircleStop className="h-4 w-4" /> Cancel task</Button>}
        </div>
        <div className="grid gap-2 border-t border-white/[0.07] pt-5">
          <Button onClick={onOpenDetails}><History className="h-4 w-4" /> Run details</Button>
          <Button onClick={onOpenSettings}><Settings2 className="h-4 w-4" /> Task controls</Button>
          <Button onClick={onOpenTranscript}><FileText className="h-4 w-4" /> Raw transcript</Button>
        </div>
      </div>
    </Drawer>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-white/[0.06] bg-black/10 px-3 py-2.5"><dt className="text-[0.56rem] uppercase tracking-wider text-slate-700">{label}</dt><dd className="mt-1 truncate text-xs text-slate-300">{value}</dd></div>;
}

function TaskSettings({ task, open, onClose }: { task: Task; open: boolean; onClose: () => void }) {
  const [models, setModels] = useState([task.model, ...task.fallback_models].filter((value): value is string => Boolean(value))); const [thinking, setThinking] = useState(task.thinking_level); const [context, setContext] = useState(task.context_strategy); const queryClient = useQueryClient(); const toast = useToast();
  const catalog = useQuery({ queryKey: ["models", task.backend], queryFn: () => api.models(task.backend), enabled: open, staleTime: 60 * 60 * 1000 });
  const refreshModels = useMutation({ mutationFn: () => api.models(task.backend, true), onSuccess: (nextCatalog) => queryClient.setQueryData(["models", task.backend], nextCatalog), onError: (error: Error) => toast(error.message, "error") });
  const updateModels = useMutation({ mutationFn: () => api.updateTaskModels(task.id, models), onSuccess: (updated) => { queryClient.setQueryData(["task", task.id], updated); toast("Model chain updated", "success"); }, onError: (error: Error) => toast(error.message, "error") });
  const updateThinking = useMutation({ mutationFn: () => api.updateTaskThinking(task.id, thinking), onSuccess: (updated) => { queryClient.setQueryData(["task", task.id], updated); toast("Thinking level updated", "success"); }, onError: (error: Error) => toast(error.message, "error") });
  const updateContext = useMutation({ mutationFn: () => api.updateTaskContext(task.id, context), onSuccess: (updated) => { queryClient.setQueryData(["task", task.id], updated); toast("Context strategy updated", "success"); }, onError: (error: Error) => toast(error.message, "error") });
  const compress = useMutation({ mutationFn: () => api.compressContext(task.id), onSuccess: () => toast("Context compressed; raw transcript preserved", "success"), onError: (error: Error) => toast(error.message, "error") });
  return <Drawer open={open} onClose={onClose} title="Task controls"><div className="space-y-7"><div><div className="flex items-center justify-between"><div className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-pulse-400" /><h3 className="text-sm font-medium text-white">Model chain</h3></div><button onClick={() => refreshModels.mutate()} disabled={refreshModels.isPending} className="text-[0.65rem] text-signal-400 disabled:opacity-50">{refreshModels.isPending ? "Refreshing…" : "Refresh from CLI"}</button></div><p className="mt-2 text-xs leading-5 text-slate-600">The first model is primary; remaining models are fallbacks when supported.</p><div className="mt-3"><MultiSelect label={catalog.isPending ? "Discovering models" : "Select models"} values={models} onChange={setModels} options={(catalog.data?.items ?? []).map((item) => ({ value: item.id, label: item.label, description: item.id }))} disabled={catalog.isPending} /></div><Button className="mt-3" onClick={() => updateModels.mutate()} loading={updateModels.isPending} disabled={models.length === 0}>Save model chain</Button></div><div className="border-t border-white/[0.07] pt-6"><div className="flex items-center gap-2"><BrainCircuit className="h-4 w-4 text-signal-400" /><h3 className="text-sm font-medium text-white">Thinking level</h3></div><p className="mt-2 text-xs leading-5 text-slate-600">Applied to new Claude and Codex invocations.</p><div className="mt-3 flex gap-2"><Select label="Thinking level" value={thinking} onChange={setThinking} options={["low", "medium", "high", "xhigh", "max"].map((value) => ({ value, label: value[0].toUpperCase() + value.slice(1) }))} /><Button onClick={() => updateThinking.mutate()} loading={updateThinking.isPending}>Save</Button></div></div><div className="border-t border-white/[0.07] pt-6"><h3 className="text-sm font-medium text-white">Context strategy</h3><p className="mt-2 text-xs leading-5 text-slate-600">Control how conversation history is passed into subsequent turns.</p><div className="mt-3 flex gap-2"><Select label="Context strategy" value={context} onChange={setContext} options={[{ value: "full", label: "Full conversation" }, { value: "compressed", label: "Compressed context" }]} /><Button onClick={() => updateContext.mutate()} loading={updateContext.isPending}>Save</Button></div></div><div className="border-t border-white/[0.07] pt-6"><h3 className="text-sm font-medium text-white">Compress now</h3><p className="mt-2 text-xs leading-5 text-slate-600">Summarize older turns while retaining the ten most recent. The full transcript remains available.</p><Button className="mt-4" onClick={() => compress.mutate()} loading={compress.isPending}><BrainCircuit className="h-4 w-4" /> Compress context</Button></div></div></Drawer>;
}

function TranscriptDrawer({ taskId, open, onClose }: { taskId: string; open: boolean; onClose: () => void }) {
  const transcript = useQuery({ queryKey: ["transcript", taskId], queryFn: () => api.transcript(taskId), enabled: open, retry: false });
  return <Drawer open={open} onClose={onClose} title="Raw transcript">{transcript.isPending ? <ListTranscriptSkeleton /> : transcript.isError ? <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5 text-sm leading-6 text-slate-500">A raw transcript becomes available after context compression.</div> : <pre className="whitespace-pre-wrap break-words rounded-xl border border-white/[0.07] bg-black/20 p-4 font-mono text-[0.68rem] leading-6 text-slate-400">{transcript.data.transcript}</pre>}</Drawer>;
}

function ListTranscriptSkeleton() { return <div className="space-y-3"><Skeleton className="h-24" /><Skeleton className="h-40" /><Skeleton className="h-28" /></div>; }
