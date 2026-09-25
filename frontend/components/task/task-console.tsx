"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  Activity,
  ArrowLeft,
  ArrowRightLeft,
  BrainCircuit,
  CheckCircle2,
  CircleStop,
  Clock3,
  FileText,
  GitPullRequest,
  History,
  MoreHorizontal,
  Network,
  PanelRightOpen,
  RefreshCcw,
  RotateCcw,
  Send,
  Settings2,
  ShieldAlert,
  Sparkles,
  TerminalSquare,
  Trash2,
  Wifi,
  WifiOff,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/drawer";
import { Modal } from "@/components/ui/modal";
import { MultiSelect, Select } from "@/components/ui/select";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { Tooltip } from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/toast";
import { ActivityFeed, AgentActivity } from "@/components/task/activity-panels";
import { TaskTokenHud } from "@/components/task/task-token-hud";
import { TerminalFrame, TerminalThread } from "@/components/task/terminal-thread";
import { MagicCanvas } from "@/components/task/magic-canvas";
import { LiveTerminal } from "@/components/task/live-terminal";
import { PrDeliveryPanel } from "@/components/task/pr-delivery-bar";
import { SlashCommandMenu } from "@/components/task/slash-command-menu";
import { useTaskStream } from "@/hooks/use-task-stream";
import { SLASH_PATTERN, useSlashCommands, type SlashCommandItem } from "@/hooks/use-slash-commands";
import { api } from "@/lib/api";
import { storedMagicCanvasContext } from "@/lib/magic-canvas";
import { SYSTEM_TASK_TAGS } from "@/lib/task-tags";
import { taskStage, type TaskStage } from "@/lib/task-status";
import type { AgentBackend, ListResponse, Message, RunAttempt, Task, TaskInvocation, TaskStatus, ToolApproval } from "@/lib/types";
import { backendLabel, cn, formatDateTime, shortId } from "@/lib/utils";

type ConsoleStage = TaskStage | "reopening";

const statusMeta: Record<ConsoleStage, { label: string; color: string }> = {
  queued: { label: "Queued", color: "bg-slate-400" },
  running: { label: "Running", color: "bg-signal-400" },
  waiting_on_you: { label: "Needs your input", color: "bg-amber-400" },
  ready_for_review: { label: "Ready for review", color: "bg-violet-400" },
  reopening: { label: "Reopening…", color: "bg-sky-400" },
  done: { label: "Complete", color: "bg-emerald-400" },
  failed: { label: "Failed", color: "bg-red-400" },
  cancelled: { label: "Cancelled", color: "bg-slate-600" },
};

export function TaskConsole({ taskId }: { taskId: string }) {
  const router = useRouter();
  const task = useQuery({ queryKey: ["task", taskId], queryFn: () => api.task(taskId), refetchInterval: 10_000 });
  const messages = useQuery({ queryKey: ["messages", taskId], queryFn: () => api.messages(taskId) });
  const attempts = useQuery({ queryKey: ["attempts", taskId], queryFn: () => api.attempts(taskId) });
  const events = useQuery({ queryKey: ["task-events", taskId], queryFn: () => api.taskEvents(taskId) });
  const invocations = useQuery({ queryKey: ["invocations", taskId], queryFn: () => api.invocations(taskId) });
  const approvals = useQuery({ queryKey: ["tool-approvals", taskId], queryFn: () => api.toolApprovals(taskId) });
  const project = useQuery({ queryKey: ["project", task.data?.project_id], queryFn: () => api.project(task.data!.project_id), enabled: Boolean(task.data?.project_id) });
  const { connection, tokenUsage, prSuggestion } = useTaskStream(taskId);
  const [prRequestOpen, setPrRequestOpen] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [mobileActionsOpen, setMobileActionsOpen] = useState(false);
  const [restartOpen, setRestartOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [canvasOpen, setCanvasOpen] = useState(false);
  const [reopening, setReopening] = useState(false);
  const [view, setView] = useState<"terminal" | "activity" | "agents">("terminal");
  const queryClient = useQueryClient(); const toast = useToast();
  const action = useMutation({
    mutationFn: (name: "cancel" | "restart" | "retry-now" | "complete") => api.taskAction(taskId, name),
    onSuccess: (updated, name) => {
      queryClient.setQueryData(["task", taskId], updated);
      queryClient.invalidateQueries({ queryKey: ["messages", taskId] });
      queryClient.invalidateQueries({ queryKey: ["invocations", taskId] });
      queryClient.invalidateQueries({ queryKey: ["tool-approvals", taskId] });
      if (name === "restart") setRestartOpen(false);
      toast(name === "restart" ? "New session started from the original brief" : updated.status === "done" ? "Task marked complete" : "Task state updated", "success");
    },
    onError: (error: Error) => toast(error.message, "error"),
  });
  const deleteTask = useMutation({
    mutationFn: () => api.deleteTask(taskId),
    onSuccess: () => {
      const projectId = task.data?.project_id;
      queryClient.removeQueries({ queryKey: ["task", taskId] });
      if (projectId) queryClient.invalidateQueries({ queryKey: ["tasks", projectId] });
      queryClient.invalidateQueries({ queryKey: ["tasks", "global"] });
      toast("Task deleted", "success");
      router.replace(projectId ? `/projects/${projectId}/board` : "/");
    },
    onError: (error: Error) => toast(error.message, "error"),
  });
  const runAction = (name: "cancel" | "restart" | "retry-now" | "complete") => { if (!action.isPending) action.mutate(name); };

  if (task.isPending) return <div className="mx-auto max-w-screen-2xl space-y-4 p-5 md:p-8"><Skeleton className="h-24" /><Skeleton className="h-[36rem]" /></div>;
  if (task.isError) return <div className="mx-auto max-w-3xl p-6"><ErrorState message={task.error.message} retry={() => task.refetch()} /></div>;
  const current = task.data;
  const currentStage: ConsoleStage = reopening ? "reopening" : taskStage(current);
  const latestAttempt = attempts.data?.items.at(-1);
  const retrying = current.status === "running" && latestAttempt?.failure_class === "transient" && latestAttempt.backoff_seconds;
  const pendingApproval = approvals.data?.items.find((approval) => approval.status === "pending");
  const availableViews = current.runtime_mode === "interactive" ? (["terminal"] as const) : (["terminal", "activity", "agents"] as const);
  const interactiveInvocationId = invocations.data?.items
    .filter((invocation) => invocation.runtime_mode === "interactive")
    .at(-1)?.id;

  return (
    <div className="mx-auto flex h-[calc(100dvh-var(--header-height))] max-w-[112rem] flex-col overflow-hidden px-2 py-2 md:px-3 md:py-3">
      <header className="surface relative z-20 flex min-h-14 shrink-0 items-center gap-2 rounded-xl px-2.5 py-2">
        <Tooltip label="Back to board" side="bottom" align="start"><Link href={`/projects/${current.project_id}/board`} className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/[0.08] text-slate-500 transition hover:border-white/15 hover:text-white" aria-label="Back to task board"><ArrowLeft className="h-4 w-4" /></Link></Tooltip>
        <div className="min-w-0 flex-1 px-1">
          <div className="flex min-w-0 items-center gap-1.5 text-[0.62rem] text-slate-600">
            <Link href={`/projects/${current.project_id}/board`} className="max-w-28 truncate transition hover:text-signal-300">{project.data?.name ?? "Project"}</Link>
            <span className="text-slate-800">/</span>
            <span className="font-mono text-[0.56rem] text-slate-700">{shortId(current.id)}</span>
          </div>
          <div className="mt-0.5 flex min-w-0 items-center gap-2">
            <h1 className="truncate text-sm font-semibold text-white">{current.title}</h1>
            <span className="hidden shrink-0 items-center gap-1.5 rounded-md border border-white/[0.06] bg-white/[0.025] px-1.5 py-0.5 text-[0.56rem] text-slate-500 md:inline-flex"><span className={cn("h-1.5 w-1.5 rounded-full", statusMeta[currentStage].color, (currentStage === "running" || currentStage === "reopening") && "animate-pulse")} />{statusMeta[currentStage].label}</span>
            <span className="hidden shrink-0 text-[0.6rem] text-slate-600 xl:inline">{backendLabel(current.backend)}{current.model ? ` · ${current.model}` : ""}</span>
          </div>
        </div>

        <nav className="hidden shrink-0 rounded-lg border border-white/[0.06] bg-black/15 p-1 lg:flex" aria-label="Task views">
          {availableViews.map((item) => {
            const Icon = item === "terminal" ? TerminalSquare : item === "activity" ? Activity : Network;
            return <button key={item} onClick={() => setView(item)} aria-pressed={view === item} className={cn("flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[0.64rem] font-medium capitalize transition", view === item ? "bg-white/[0.08] text-white" : "text-slate-600 hover:text-slate-300")}><Icon className="h-3.5 w-3.5" />{item}{item === "activity" && events.data?.items.length ? <span className="font-mono text-[0.53rem] text-slate-600">{events.data.items.length}</span> : null}</button>;
          })}
        </nav>

        {current.runtime_mode === "structured" && <TaskTokenHud tokenUsage={tokenUsage} task={current} invocations={invocations.data?.items ?? []} />}
        <Tooltip label="Open Magic Canvas" side="bottom"><Button size="icon" variant={canvasOpen ? "primary" : "ghost"} onClick={() => setCanvasOpen((value) => !value)} aria-label="Toggle Magic Canvas"><PanelRightOpen className="h-4 w-4" /></Button></Tooltip>
        <Tooltip label={connection === "live" ? "Runtime stream connected" : connection === "connecting" ? "Connecting to runtime" : "Runtime stream reconnecting"} side="bottom"><span className={cn("hidden h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/[0.07] bg-white/[0.02] sm:grid", connection === "live" ? "text-signal-400" : "text-slate-600")}>{connection === "live" ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}</span></Tooltip>
        <div className="hidden shrink-0 items-center gap-0.5 border-l border-white/[0.07] pl-1.5 sm:flex">
          {(current.status === "waiting_on_you" || (current.runtime_mode === "interactive" && current.status === "running")) && <Tooltip label="Mark conversation complete" side="bottom"><Button size="icon" variant="primary" loading={action.isPending} onClick={() => runAction("complete")} aria-label="Mark conversation complete"><CheckCircle2 className="h-3.5 w-3.5" /></Button></Tooltip>}
          {current.status === "failed" && <Tooltip label="Retry now" side="bottom"><Button size="icon" variant="primary" loading={action.isPending} onClick={() => runAction("retry-now")} aria-label="Retry task now"><RefreshCcw className="h-3.5 w-3.5" /></Button></Tooltip>}
          <Tooltip label="Restart from beginning" side="bottom"><Button size="icon" loading={action.isPending && action.variables === "restart"} onClick={() => setRestartOpen(true)} aria-label="Restart task from beginning"><RotateCcw className="h-3.5 w-3.5" /></Button></Tooltip>
          {(current.status === "running" || current.status === "queued" || current.status === "waiting_on_you") && <Tooltip label="Cancel task" side="bottom"><Button size="icon" variant="danger" loading={action.isPending} onClick={() => runAction("cancel")} aria-label="Cancel task"><CircleStop className="h-3.5 w-3.5" /></Button></Tooltip>}
          <Tooltip label="Run details" side="bottom"><Button size="icon" variant="ghost" onClick={() => setDetailsOpen(true)} aria-label="Open task details"><History className="h-4 w-4" /></Button></Tooltip>
          <Tooltip label="Task controls" side="bottom"><Button size="icon" variant="ghost" onClick={() => setSettingsOpen(true)} aria-label="Open task settings"><Settings2 className="h-4 w-4" /></Button></Tooltip>
          {current.runtime_mode === "structured" && <Tooltip label="Raw transcript" side="bottom" align="end"><Button className="hidden md:inline-flex" size="icon" variant="ghost" onClick={() => setTranscriptOpen(true)} aria-label="Open raw transcript"><FileText className="h-4 w-4" /></Button></Tooltip>}
          <Tooltip label="Delete task" side="bottom" align="end"><Button size="icon" variant="ghost" onClick={() => setDeleteOpen(true)} aria-label="Delete task"><Trash2 className="h-4 w-4" /></Button></Tooltip>
        </div>
        <Button className="shrink-0 sm:hidden" size="icon" variant="ghost" onClick={() => setMobileActionsOpen(true)} aria-label="Open task actions"><MoreHorizontal className="h-4 w-4" /></Button>
      </header>

      {retrying && <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mt-3 flex items-center justify-between gap-4 rounded-xl border border-amber-400/15 bg-amber-400/[0.045] px-4 py-3"><div className="flex items-center gap-3"><Clock3 className="h-4 w-4 text-amber-400" /><p className="text-xs text-amber-100/70">Transient failure detected. Automatic retry scheduled in {latestAttempt.backoff_seconds} seconds.</p></div><Button size="sm" variant="ghost" onClick={() => runAction("retry-now")}>Retry now</Button></motion.div>}
      {current.status === "waiting_on_you" && current.attention_reason === "awaiting_review" && (
        <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mt-3 flex items-center justify-between gap-4 rounded-xl border border-amber-400/15 bg-amber-400/[0.045] px-4 py-3">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="h-4 w-4 text-amber-400" />
            <p className="text-xs text-amber-100/70">The agent finished this turn, but there&apos;s no verified delivery signal yet. Review the conversation, then mark it complete or send a follow-up.</p>
          </div>
          <Button size="sm" variant="primary" loading={action.isPending} onClick={() => runAction("complete")}>Mark complete</Button>
        </motion.div>
      )}
      {pendingApproval && <ToolApprovalBar approval={pendingApproval} />}
      <PrDeliveryPanel
        taskId={taskId}
        suggestion={prSuggestion}
        requestOpen={prRequestOpen}
        onOpenHandled={() => undefined}
      />
      <div className={cn("mt-2 min-h-0 flex-1 gap-2", canvasOpen && "xl:grid xl:grid-cols-[minmax(28rem,0.92fr)_minmax(30rem,1.08fr)]")}>
        <section className="surface flex h-full min-h-0 flex-col overflow-hidden rounded-xl">
          {availableViews.length > 1 && <nav className="flex shrink-0 border-b border-white/[0.06] bg-black/10 p-1.5 lg:hidden" aria-label="Task views">{availableViews.map((item) => <button key={item} onClick={() => setView(item)} className={cn("flex-1 rounded-md px-3 py-1.5 text-[0.66rem] font-medium capitalize transition", view === item ? "bg-white/[0.08] text-white" : "text-slate-600")}>{item}</button>)}</nav>}
          <div className="min-h-0 flex-1 overflow-hidden">{view === "terminal" && <TerminalFrame>{current.runtime_mode === "interactive" ? <LiveTerminal key={interactiveInvocationId ?? taskId} taskId={taskId} /> : <TerminalThread task={current} messages={messages.data?.items ?? []} invocations={invocations.data?.items ?? []} loading={messages.isPending} onOpenCanvas={() => setCanvasOpen(true)} />}</TerminalFrame>}{view === "activity" && <ActivityFeed events={events.data?.items ?? []} />}{view === "agents" && <AgentActivity invocations={invocations.data?.items ?? []} events={events.data?.items ?? []} />}</div>
          {view === "terminal" && current.runtime_mode === "structured" && <Composer taskId={taskId} status={current.status} attentionReason={current.attention_reason} onReopeningChange={setReopening} onPreparePr={() => setPrRequestOpen((value) => value + 1)} />}
        </section>
        <div className={cn("h-full min-h-0", canvasOpen ? "fixed inset-x-2 bottom-2 top-[calc(var(--header-height)+0.5rem)] z-40 xl:static xl:z-auto" : "hidden")}><MagicCanvas taskId={taskId} messages={messages.data?.items ?? []} open={canvasOpen} onOpenChange={setCanvasOpen} /></div>
      </div>
      <TaskSettings key={current.backend} task={current} open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <TranscriptDrawer taskId={taskId} open={transcriptOpen} onClose={() => setTranscriptOpen(false)} />
      <TaskDetailsDrawer task={current} projectName={project.data?.name} attempts={attempts.data?.items ?? []} invocations={invocations.data?.items ?? []} open={detailsOpen} onClose={() => setDetailsOpen(false)} onOpenTranscript={() => { setDetailsOpen(false); setTranscriptOpen(true); }} />
      <TaskMobileActions task={current} open={mobileActionsOpen} busy={action.isPending} onClose={() => setMobileActionsOpen(false)} onAction={(name) => { setMobileActionsOpen(false); if (name === "restart") setRestartOpen(true); else runAction(name); }} onOpenDetails={() => { setMobileActionsOpen(false); setDetailsOpen(true); }} onOpenSettings={() => { setMobileActionsOpen(false); setSettingsOpen(true); }} onOpenTranscript={() => { setMobileActionsOpen(false); setTranscriptOpen(true); }} onDelete={() => { setMobileActionsOpen(false); setDeleteOpen(true); }} />
      <RestartTaskModal task={current} open={restartOpen} busy={action.isPending && action.variables === "restart"} onClose={() => setRestartOpen(false)} onConfirm={() => runAction("restart")} />
      <DeleteTaskModal task={current} open={deleteOpen} busy={deleteTask.isPending} onClose={() => setDeleteOpen(false)} onConfirm={() => deleteTask.mutate()} />
    </div>
  );
}

function ToolApprovalBar({ approval }: { approval: ToolApproval }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const resolve = useMutation({
    mutationFn: (decision: "approve_once" | "always_allow" | "deny") => api.resolveToolApproval(approval.task_id, approval.id, decision),
    onSuccess: (updated) => {
      queryClient.setQueryData<ListResponse<ToolApproval>>(["tool-approvals", approval.task_id], (current) => ({ items: (current?.items ?? []).map((item) => item.id === updated.id ? updated : item) }));
      queryClient.invalidateQueries({ queryKey: ["task", approval.task_id] });
      queryClient.invalidateQueries({ queryKey: ["messages", approval.task_id] });
      toast(updated.status === "denied" ? "Tool request denied" : "Tool request approved", updated.status === "denied" ? "error" : "success");
    },
    onError: (error: Error) => toast(error.message, "error"),
  });
  const command = typeof approval.tool_input.command === "string" ? approval.tool_input.command : JSON.stringify(approval.tool_input);
  return <motion.section initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mt-2 flex flex-col gap-3 rounded-xl border border-amber-400/20 bg-amber-400/[0.05] px-3 py-3 sm:flex-row sm:items-center"><div className="flex min-w-0 flex-1 items-center gap-3"><span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-amber-400/20 bg-amber-400/[0.07] text-amber-400"><ShieldAlert className="h-4 w-4" /></span><div className="min-w-0"><p className="text-xs font-medium text-amber-100">{approval.tool_name} needs permission</p><p className="mt-1 truncate font-mono text-[0.62rem] text-amber-100/50" title={command}>{command || approval.reason || "Runtime permission escalation"}</p></div></div><div className="flex shrink-0 gap-1.5"><Button size="sm" variant="ghost" loading={resolve.isPending} onClick={() => resolve.mutate("deny")}>Deny</Button><Button size="sm" loading={resolve.isPending} onClick={() => resolve.mutate("approve_once")}>Allow once</Button><Button size="sm" variant="primary" loading={resolve.isPending} onClick={() => resolve.mutate("always_allow")}>Always allow</Button></div></motion.section>;
}

function Composer({ taskId, status, attentionReason, onReopeningChange, onPreparePr }: { taskId: string; status: TaskStatus; attentionReason: Task["attention_reason"]; onReopeningChange: (reopening: boolean) => void; onPreparePr: () => void }) {
  const [value, setValue] = useState(""); const [error, setError] = useState(""); const queryClient = useQueryClient(); const toast = useToast();
  const [slashQuery, setSlashQuery] = useState<string | null>(null);
  const [slashActiveIndex, setSlashActiveIndex] = useState(0);
  const slashCommands = useSlashCommands(slashQuery);
  const send = useMutation({
    mutationFn: (content: string) => {
      const canvas = storedMagicCanvasContext(taskId);
      return api.sendMessage(taskId, content, canvas ? [canvas] : []);
    },
    onMutate: async (content) => {
      await Promise.all([
        queryClient.cancelQueries({ queryKey: ["messages", taskId] }),
        queryClient.cancelQueries({ queryKey: ["task", taskId] }),
      ]);
      const previousMessages = queryClient.getQueryData<ListResponse<Message>>(["messages", taskId]);
      const previousTask = queryClient.getQueryData<Task>(["task", taskId]);
      const shouldReopen = status === "waiting_on_you" || status === "done" || status === "failed" || status === "cancelled";
      if (shouldReopen) {
        onReopeningChange(true);
        queryClient.setQueryData<Task>(["task", taskId], (current) => current ? {
          ...current,
          status: "queued",
          attention_reason: null,
          completed_at: null,
        } : current);
      }
      const optimistic: Message = { id: `optimistic-${Date.now()}`, task_id: taskId, sender: "user", content_text: content, media: [], is_blocking_question: false, created_at: new Date().toISOString(), optimistic: true };
      queryClient.setQueryData<ListResponse<Message>>(["messages", taskId], { items: [...(previousMessages?.items ?? []), optimistic] });
      setValue("");
      return { previousMessages, previousTask, shouldReopen };
    },
    onError: (cause: Error, _content, context) => {
      queryClient.setQueryData(["messages", taskId], context?.previousMessages);
      if (context?.shouldReopen) queryClient.setQueryData(["task", taskId], context.previousTask);
      setError(cause.message);
      toast("Message was not sent", "error");
    },
    onSuccess: async (saved) => {
      queryClient.setQueryData<ListResponse<Message>>(["messages", taskId], (current) => ({ items: [...(current?.items.filter((item) => !item.optimistic) ?? []), saved] }));
      await queryClient.invalidateQueries({ queryKey: ["task", taskId] });
      setError("");
    },
    onSettled: () => onReopeningChange(false),
  });
  const submit = (event: FormEvent) => { event.preventDefault(); const content = value.trim(); if (content && !send.isPending) send.mutate(content); };
  const changeValue = (next: string) => {
    setValue(next);
    setError("");
    const match = next.match(SLASH_PATTERN);
    setSlashQuery(match?.[1] ?? null);
    setSlashActiveIndex(0);
  };
  const selectSlashCommand = (item: SlashCommandItem) => {
    if (item.kind === "action" && item.name === "pr") {
      setValue("");
      setSlashQuery(null);
      setSlashActiveIndex(0);
      onPreparePr();
      return;
    }
    const match = value.match(SLASH_PATTERN);
    const insertion = `/${item.name} `;
    setValue(match ? `${value.slice(0, match.index)}${match[0].startsWith(" ") ? " " : ""}${insertion}` : `${insertion}${value}`);
    setSlashQuery(null);
    setSlashActiveIndex(0);
  };
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.nativeEvent.isComposing) return;
    if (slashQuery !== null && slashCommands.suggestions.length > 0) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        setSlashActiveIndex((current) =>
          event.key === "ArrowDown"
            ? (current + 1) % slashCommands.suggestions.length
            : (current - 1 + slashCommands.suggestions.length) % slashCommands.suggestions.length,
        );
        return;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        selectSlashCommand(slashCommands.suggestions[slashActiveIndex] ?? slashCommands.suggestions[0]);
        return;
      }
      if (event.key === "Escape") { event.preventDefault(); setSlashQuery(null); return; }
    }
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); }
  };
  const placeholder = attentionReason === "awaiting_review"
    ? "Ask a follow-up, or mark the task complete"
    : status === "waiting_on_you"
      ? "Respond to the agent"
      : status === "done" || status === "failed" || status === "cancelled"
        ? "Send a follow-up to reopen this task"
        : "Send a follow-up instruction, / for a command, agent, or skill";
  return <form onSubmit={submit} className="border-t border-white/[0.07] bg-black/10 p-3"><div className="mx-auto max-w-3xl"><div className="relative flex items-end gap-2 rounded-xl border border-white/10 bg-ink-950/70 p-1.5 transition focus-within:border-signal-400/30 focus-within:ring-4 focus-within:ring-signal-400/[0.05]"><Button type="button" size="icon" variant="ghost" onClick={onPreparePr} aria-label="Prepare pull request" title="Prepare pull request"><GitPullRequest className="h-4 w-4" /></Button><textarea value={value} onChange={(event) => changeValue(event.target.value)} onKeyDown={handleKeyDown} rows={1} className="max-h-28 min-h-9 flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-5 text-white placeholder:text-slate-700 focus:outline-none" placeholder={placeholder} aria-label="Message agent" role="combobox" aria-haspopup="listbox" aria-autocomplete="list" aria-controls={slashQuery !== null ? "slash-command-list" : undefined} aria-expanded={slashQuery !== null} aria-activedescendant={slashQuery !== null && slashCommands.suggestions[slashActiveIndex] ? `slash-command-${slashCommands.suggestions[slashActiveIndex].id}` : undefined} /><Button type="submit" size="icon" variant="primary" loading={send.isPending} disabled={!value.trim()} aria-label="Send message"><Send className="h-4 w-4" /></Button><SlashCommandMenu open={slashQuery !== null} loading={slashCommands.isPending} error={slashCommands.isError} items={slashCommands.suggestions} activeIndex={slashActiveIndex} onHover={setSlashActiveIndex} onSelect={selectSlashCommand} className="absolute inset-x-1.5 bottom-full mb-2" /></div>{error && <p className="mt-2 text-xs text-red-400" role="alert">{error}</p>}<p className="mt-1.5 px-1 text-[0.56rem] text-slate-700">Enter to send · Shift + Enter for a new line · /pr to prepare delivery</p></div></form>;
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
            <Detail label="Status" value={statusMeta[taskStage(task)].label} />
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
  onDelete,
}: {
  task: Task;
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onAction: (name: "cancel" | "restart" | "retry-now" | "complete") => void;
  onOpenDetails: () => void;
  onOpenSettings: () => void;
  onOpenTranscript: () => void;
  onDelete: () => void;
}) {
  const stage = taskStage(task);
  return (
    <Drawer open={open} onClose={onClose} title="Task actions">
      <div className="space-y-5">
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
          <div className="flex items-center gap-2"><span className={cn("h-2 w-2 rounded-full", statusMeta[stage].color, task.status === "running" && "animate-pulse")} /><span className="text-sm font-medium text-white">{statusMeta[stage].label}</span></div>
          <p className="mt-2 text-xs text-slate-600">{backendLabel(task.backend)} · {task.model || "Runtime default"}</p>
        </div>
        <div className="grid gap-2">
          {(task.status === "waiting_on_you" || (task.runtime_mode === "interactive" && task.status === "running")) && <Button variant="primary" loading={busy} onClick={() => onAction("complete")}><CheckCircle2 className="h-4 w-4" /> Mark conversation complete</Button>}
          {task.status === "failed" && <Button variant="primary" loading={busy} onClick={() => onAction("retry-now")}><RefreshCcw className="h-4 w-4" /> Retry now</Button>}
          <Button loading={busy} onClick={() => onAction("restart")}><RotateCcw className="h-4 w-4" /> Restart from beginning</Button>
          {(task.status === "running" || task.status === "queued" || task.status === "waiting_on_you") && <Button variant="danger" loading={busy} onClick={() => onAction("cancel")}><CircleStop className="h-4 w-4" /> Cancel task</Button>}
        </div>
        <div className="grid gap-2 border-t border-white/[0.07] pt-5">
          <Button onClick={onOpenDetails}><History className="h-4 w-4" /> Run details</Button>
          <Button onClick={onOpenSettings}><Settings2 className="h-4 w-4" /> Task controls</Button>
          <Button onClick={onOpenTranscript}><FileText className="h-4 w-4" /> Raw transcript</Button>
          <Button variant="danger" onClick={onDelete}><Trash2 className="h-4 w-4" /> Delete task</Button>
        </div>
      </div>
    </Drawer>
  );
}

function RestartTaskModal({
  task,
  open,
  busy,
  onClose,
  onConfirm,
}: {
  task: Task;
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const active = task.status === "running" || task.status === "queued" || task.status === "waiting_on_you";
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Restart from the beginning?"
      description="Muster will create a new agent session and send the original brief as its first prompt."
    >
      <div className="space-y-5">
        <div className="rounded-xl border border-white/[0.08] bg-black/15 p-4">
          <p className="text-[0.6rem] font-medium uppercase tracking-[0.16em] text-signal-400">Original brief</p>
          <p className="mt-2 max-h-36 overflow-y-auto whitespace-pre-wrap text-sm leading-6 text-slate-300">{task.initial_prompt}</p>
        </div>
        <ul className="space-y-2 text-xs leading-5 text-slate-500">
          {active && <li>The current invocation will be stopped before the new one starts.</li>}
          <li>The saved Claude Code or Codex session ID will not be reused.</li>
          <li>Existing messages, activity, and invocation history will remain visible.</li>
        </ul>
        <div className="flex justify-end gap-2 border-t border-white/[0.07] pt-5">
          <Button variant="ghost" onClick={onClose} disabled={busy}>Keep current session</Button>
          <Button variant="primary" onClick={onConfirm} loading={busy}><RotateCcw className="h-4 w-4" /> Restart from beginning</Button>
        </div>
      </div>
    </Modal>
  );
}

function DeleteTaskModal({
  task,
  open,
  busy,
  onClose,
  onConfirm,
}: {
  task: Task;
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const active = task.status === "running" || task.status === "queued" || task.status === "waiting_on_you";
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Delete this task?"
      description="This permanently removes the task and its messages, activity, and invocation history."
    >
      <div className="space-y-5">
        <div className="rounded-xl border border-red-400/15 bg-red-400/[0.04] p-4">
          <p className="text-sm font-medium text-white">{task.title}</p>
          {active && <p className="mt-2 text-xs leading-5 text-red-200/65">The current agent run will be stopped before this task is deleted.</p>}
        </div>
        <div className="flex justify-end gap-2 border-t border-white/[0.07] pt-5">
          <Button variant="ghost" onClick={onClose} disabled={busy}>Keep task</Button>
          <Button variant="danger" onClick={onConfirm} loading={busy}><Trash2 className="h-4 w-4" /> Delete task</Button>
        </div>
      </div>
    </Modal>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-white/[0.06] bg-black/10 px-3 py-2.5"><dt className="text-[0.56rem] uppercase tracking-wider text-slate-700">{label}</dt><dd className="mt-1 truncate text-xs text-slate-300">{value}</dd></div>;
}

function RuntimeSwitchControl({ task }: { task: Task }) {
  const [runtime, setRuntime] = useState<AgentBackend>(task.backend);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const queryClient = useQueryClient();
  const toast = useToast();
  const switchRuntime = useMutation({
    mutationFn: () => api.updateTaskBackend(task.id, runtime),
    onSuccess: (updated) => {
      queryClient.setQueryData(["task", task.id], updated);
      queryClient.invalidateQueries({ queryKey: ["messages", task.id] });
      queryClient.invalidateQueries({ queryKey: ["invocations", task.id] });
      queryClient.invalidateQueries({ queryKey: ["tool-approvals", task.id] });
      queryClient.invalidateQueries({ queryKey: ["tasks", task.project_id] });
      queryClient.invalidateQueries({ queryKey: ["tasks", "global"] });
      setConfirmOpen(false);
      toast(`Runtime switched to ${backendLabel(updated.backend)}`, "success");
    },
    onError: (error: Error) => toast(error.message, "error"),
  });
  const active = task.status === "running" || task.status === "queued";

  return (
    <>
      <div>
        <div className="flex items-center gap-2">
          <ArrowRightLeft className="h-4 w-4 text-signal-400" />
          <h3 className="text-sm font-medium text-white">Agent runtime</h3>
        </div>
        <p className="mt-2 text-xs leading-5 text-slate-600">
          Move this task between Claude Code and Codex without losing its visible history.
        </p>
        <div className="mt-3 flex gap-2">
          <Select
            label="Agent runtime"
            value={runtime}
            onChange={(value) => setRuntime(value as AgentBackend)}
            options={[
              { value: "claude_code", label: "Claude Code", description: "Anthropic CLI runtime" },
              { value: "codex", label: "Codex", description: "OpenAI CLI runtime" },
            ]}
          />
          <Button
            onClick={() => setConfirmOpen(true)}
            disabled={runtime === task.backend}
          >
            Switch
          </Button>
        </div>
        <p className="mt-2 font-mono text-[0.6rem] text-slate-700">
          Current: {backendLabel(task.backend)}
        </p>
      </div>

      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={`Switch to ${backendLabel(runtime)}?`}
        description="The destination runtime will continue this task in a new native session."
      >
        <div className="space-y-5">
          <div className="flex items-center justify-center gap-4 rounded-xl border border-white/[0.08] bg-black/15 p-5">
            <span className="rounded-lg border border-white/[0.08] bg-white/[0.035] px-3 py-2 text-xs font-medium text-slate-300">{backendLabel(task.backend)}</span>
            <ArrowRightLeft className="h-4 w-4 text-signal-400" />
            <span className="rounded-lg border border-signal-400/20 bg-signal-400/[0.07] px-3 py-2 text-xs font-medium text-signal-300">{backendLabel(runtime)}</span>
          </div>
          <ul className="space-y-2 text-xs leading-5 text-slate-500">
            {active && <li>The active invocation will be stopped before the new runtime starts.</li>}
            <li>The existing conversation and invocation history will remain visible.</li>
            <li>A structured handoff of the prior conversation will seed the new session.</li>
            <li>The old session ID, selected agent, and model chain cannot cross runtimes and will be reset.</li>
          </ul>
          <div className="flex justify-end gap-2 border-t border-white/[0.07] pt-5">
            <Button variant="ghost" onClick={() => setConfirmOpen(false)} disabled={switchRuntime.isPending}>Keep {backendLabel(task.backend)}</Button>
            <Button variant="primary" onClick={() => switchRuntime.mutate()} loading={switchRuntime.isPending}><ArrowRightLeft className="h-4 w-4" /> Switch runtime</Button>
          </div>
        </div>
      </Modal>
    </>
  );
}

function TaskSettings({ task, open, onClose }: { task: Task; open: boolean; onClose: () => void }) {
  const [models, setModels] = useState([task.model, ...task.fallback_models].filter((value): value is string => Boolean(value))); const [thinking, setThinking] = useState(task.thinking_level); const [context, setContext] = useState(task.context_strategy); const [tags, setTags] = useState(task.tags); const queryClient = useQueryClient(); const toast = useToast();
  const catalog = useQuery({ queryKey: ["models", task.backend], queryFn: () => api.models(task.backend), enabled: open, staleTime: 60 * 60 * 1000 });
  const tagCatalog = useQuery({ queryKey: ["project-task-tags", task.project_id], queryFn: () => api.projectTaskTags(task.project_id), enabled: open });
  const refreshModels = useMutation({ mutationFn: () => api.models(task.backend, true), onSuccess: (nextCatalog) => queryClient.setQueryData(["models", task.backend], nextCatalog), onError: (error: Error) => toast(error.message, "error") });
  const updateModels = useMutation({ mutationFn: () => api.updateTaskModels(task.id, models), onSuccess: (updated) => { queryClient.setQueryData(["task", task.id], updated); toast("Model chain updated", "success"); }, onError: (error: Error) => toast(error.message, "error") });
  const updateThinking = useMutation({ mutationFn: () => api.updateTaskThinking(task.id, thinking), onSuccess: (updated) => { queryClient.setQueryData(["task", task.id], updated); toast("Thinking level updated", "success"); }, onError: (error: Error) => toast(error.message, "error") });
  const updateContext = useMutation({ mutationFn: () => api.updateTaskContext(task.id, context), onSuccess: (updated) => { queryClient.setQueryData(["task", task.id], updated); toast("Context strategy updated", "success"); }, onError: (error: Error) => toast(error.message, "error") });
  const updateTags = useMutation({ mutationFn: () => api.updateTaskTags(task.id, tags.filter((tag) => !SYSTEM_TASK_TAGS.has(tag))), onSuccess: (updated) => { queryClient.setQueryData(["task", task.id], updated); queryClient.invalidateQueries({ queryKey: ["tasks", task.project_id] }); toast("Task tags updated", "success"); }, onError: (error: Error) => toast(error.message, "error") });
  const compress = useMutation({ mutationFn: () => api.compressContext(task.id), onSuccess: () => toast("Context compressed; raw transcript preserved", "success"), onError: (error: Error) => toast(error.message, "error") });
  return <Drawer open={open} onClose={onClose} title="Task controls"><div className="space-y-7"><RuntimeSwitchControl task={task} /><div className="border-t border-white/[0.07] pt-6"><div className="flex items-center justify-between"><div className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-pulse-400" /><h3 className="text-sm font-medium text-white">Model chain</h3></div><button onClick={() => refreshModels.mutate()} disabled={refreshModels.isPending} className="text-[0.65rem] text-signal-400 disabled:opacity-50">{refreshModels.isPending ? "Refreshing…" : "Refresh from CLI"}</button></div><p className="mt-2 text-xs leading-5 text-slate-600">The first model is primary; remaining models are fallbacks when supported.</p><div className="mt-3"><MultiSelect label={catalog.isPending ? "Discovering models" : "Select models"} values={models} onChange={setModels} options={(catalog.data?.items ?? []).map((item) => ({ value: item.id, label: item.label, description: item.id }))} disabled={catalog.isPending} /></div><Button className="mt-3" onClick={() => updateModels.mutate()} loading={updateModels.isPending} disabled={models.length === 0}>Save model chain</Button></div><div className="border-t border-white/[0.07] pt-6"><h3 className="text-sm font-medium text-white">Workflow tags</h3><p className="mt-2 text-xs leading-5 text-slate-600">Assign project tags. Evidence labels such as PR Raised and Canvas are managed automatically.</p><div className="mt-3"><MultiSelect label={tagCatalog.isPending ? "Loading project tags" : "Add task tags"} values={tags} onChange={setTags} options={(tagCatalog.data?.items ?? []).filter((item) => item.kind !== "system").map((item) => ({ value: item.name, label: item.name, description: item.kind === "preset" ? "Workflow preset" : "Project tag" }))} disabled={tagCatalog.isPending} /></div><Button className="mt-3" onClick={() => updateTags.mutate()} loading={updateTags.isPending}>Save tags</Button></div><div className="border-t border-white/[0.07] pt-6"><div className="flex items-center gap-2"><BrainCircuit className="h-4 w-4 text-signal-400" /><h3 className="text-sm font-medium text-white">Thinking level</h3></div><p className="mt-2 text-xs leading-5 text-slate-600">Applied to new Claude and Codex invocations.</p><div className="mt-3 flex gap-2"><Select label="Thinking level" value={thinking} onChange={setThinking} options={["low", "medium", "high", "xhigh", "max"].map((value) => ({ value, label: value[0].toUpperCase() + value.slice(1) }))} /><Button onClick={() => updateThinking.mutate()} loading={updateThinking.isPending}>Save</Button></div></div><div className="border-t border-white/[0.07] pt-6"><h3 className="text-sm font-medium text-white">Context strategy</h3><p className="mt-2 text-xs leading-5 text-slate-600">Control how conversation history is passed into subsequent turns.</p><div className="mt-3 flex gap-2"><Select label="Context strategy" value={context} onChange={setContext} options={[{ value: "full", label: "Full conversation" }, { value: "compressed", label: "Compressed context" }]} /><Button onClick={() => updateContext.mutate()} loading={updateContext.isPending}>Save</Button></div></div><div className="border-t border-white/[0.07] pt-6"><h3 className="text-sm font-medium text-white">Compress now</h3><p className="mt-2 text-xs leading-5 text-slate-600">Summarize older turns while retaining the ten most recent. The full transcript remains available.</p><Button className="mt-4" onClick={() => compress.mutate()} loading={compress.isPending}><BrainCircuit className="h-4 w-4" /> Compress context</Button></div></div></Drawer>;
}

function TranscriptDrawer({ taskId, open, onClose }: { taskId: string; open: boolean; onClose: () => void }) {
  const transcript = useQuery({ queryKey: ["transcript", taskId], queryFn: () => api.transcript(taskId), enabled: open, retry: false });
  return <Drawer open={open} onClose={onClose} title="Raw transcript">{transcript.isPending ? <ListTranscriptSkeleton /> : transcript.isError ? <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-5 text-sm leading-6 text-slate-500">A raw transcript becomes available after context compression.</div> : <pre className="whitespace-pre-wrap break-words rounded-xl border border-white/[0.07] bg-black/20 p-4 font-mono text-[0.68rem] leading-6 text-slate-400">{transcript.data.transcript}</pre>}</Drawer>;
}

function ListTranscriptSkeleton() { return <div className="space-y-3"><Skeleton className="h-24" /><Skeleton className="h-40" /><Skeleton className="h-28" /></div>; }
