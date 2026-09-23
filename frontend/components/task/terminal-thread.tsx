"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowDown,
  Bot,
  ChevronDown,
  CircleAlert,
  Code2,
  CornerDownRight,
  Sparkles,
  User,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode, type UIEvent } from "react";

import { MarkdownContent } from "@/components/ui/markdown-content";
import { Skeleton } from "@/components/ui/states";
import type { Message, Task } from "@/lib/types";
import { backendLabel, cn, formatDateTime } from "@/lib/utils";

type ThreadItem =
  | { type: "message"; message: Message }
  | { type: "intermediate"; id: string; messages: Message[] };

export function TerminalThread({
  task,
  messages,
  loading,
}: {
  task: Task;
  messages: Message[];
  loading: boolean;
}) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const followingRef = useRef(true);
  const initializedRef = useRef(false);
  const [showLatest, setShowLatest] = useState(false);
  const items = useMemo(() => collapseIntermediateResponses(messages), [messages]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !followingRef.current) return;
    const frame = requestAnimationFrame(() => {
      viewport.scrollTo({
        top: viewport.scrollHeight,
        behavior: initializedRef.current ? "smooth" : "instant",
      });
      initializedRef.current = true;
    });
    return () => cancelAnimationFrame(frame);
  }, [messages.length, task.status]);

  const handleScroll = (event: UIEvent<HTMLDivElement>) => {
    const viewport = event.currentTarget;
    const distanceFromBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
    const nearBottom = distanceFromBottom < 96;
    followingRef.current = nearBottom;
    setShowLatest(!nearBottom);
  };

  const jumpToLatest = () => {
    followingRef.current = true;
    setShowLatest(false);
    viewportRef.current?.scrollTo({ top: viewportRef.current.scrollHeight, behavior: "smooth" });
  };

  if (loading) {
    return (
      <div className="flex-1 space-y-3 bg-[#05070b] p-5">
        <Skeleton className="h-14" />
        <Skeleton className="h-28" />
        <Skeleton className="ml-auto h-16 w-2/3" />
      </div>
    );
  }

  return (
    <div className="relative h-full min-h-0 bg-[#05070b]">
      <div
        ref={viewportRef}
        onScroll={handleScroll}
        className="h-full overflow-y-auto scroll-smooth px-3 py-4 sm:px-5"
        aria-live="polite"
        aria-label="Task terminal transcript"
      >
        <div className="mx-auto max-w-5xl overflow-hidden rounded-xl border border-white/[0.065] bg-[#07090e]">
          <TerminalBrief task={task} collapsed={messages.length > 0} />
          <AnimatePresence initial={false}>
            {items.map((item) =>
              item.type === "intermediate" ? (
                <IntermediateResponses key={item.id} messages={item.messages} backend={task.backend} />
              ) : (
                <TerminalMessage key={item.message.id} message={item.message} backend={task.backend} />
              ),
            )}
          </AnimatePresence>
          {task.status === "running" && <WorkingLine backend={task.backend} />}
        </div>
      </div>

      <AnimatePresence>
        {showLatest && (
          <motion.button
            type="button"
            initial={{ opacity: 0, y: 8, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 5, scale: 0.96 }}
            onClick={jumpToLatest}
            className="absolute bottom-4 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-full border border-signal-400/20 bg-ink-850/95 px-3 py-2 text-[0.66rem] font-medium text-signal-300 shadow-panel backdrop-blur-xl"
          >
            <ArrowDown className="h-3.5 w-3.5" />
            Latest output
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}

function TerminalBrief({ task, collapsed }: { task: Task; collapsed: boolean }) {
  const [open, setOpen] = useState(!collapsed);
  return (
    <section className="border-b border-white/[0.065]">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-white/[0.018]"
        aria-expanded={open}
      >
        <span className="font-mono text-xs font-semibold text-pulse-400">$</span>
        <span className="min-w-0 flex-1 truncate font-mono text-xs text-slate-400">
          muster run <span className="text-slate-600">--brief</span> {task.initial_prompt.split("\n")[0]}
        </span>
        <span className="hidden text-[0.58rem] uppercase tracking-wider text-slate-700 sm:inline">initial brief</span>
        <ChevronDown className={cn("h-3.5 w-3.5 text-slate-700 transition-transform", open && "rotate-180")} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="border-t border-white/[0.05] bg-pulse-400/[0.025] px-4 py-3.5 sm:pl-9">
              <MarkdownContent content={task.initial_prompt} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

function TerminalMessage({ message, backend }: { message: Message; backend: Task["backend"] }) {
  if (message.sender === "system") {
    return (
      <motion.div
        layout
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex gap-3 border-b border-white/[0.05] bg-amber-400/[0.02] px-4 py-3 last:border-b-0"
      >
        <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[0.58rem] uppercase tracking-wider text-amber-400/70">system</p>
          <p className="mt-1 whitespace-pre-wrap break-words text-xs leading-5 text-amber-100/55">{message.content_text}</p>
        </div>
      </motion.div>
    );
  }

  const user = message.sender === "user";
  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 5 }}
      animate={{ opacity: message.optimistic ? 0.55 : 1, y: 0 }}
      className={cn(
        "grid grid-cols-[1.75rem_minmax(0,1fr)] gap-3 border-b border-white/[0.055] px-4 py-4 last:border-b-0",
        user ? "bg-pulse-400/[0.025]" : "bg-transparent",
      )}
    >
      <span className={cn(
        "mt-0.5 grid h-7 w-7 place-items-center rounded-lg border",
        user
          ? "border-pulse-400/15 bg-pulse-400/[0.07] text-pulse-400"
          : "border-signal-400/15 bg-signal-400/[0.065] text-signal-400",
      )}>
        {user ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
      </span>
      <div className="min-w-0">
        <div className="mb-2 flex items-center gap-2 font-mono text-[0.58rem] uppercase tracking-wider">
          <span className={user ? "text-pulse-400/80" : "text-signal-400/80"}>
            {user ? "you" : backendLabel(backend)}
          </span>
          {!user && message.is_blocking_question && <span className="rounded bg-amber-400/10 px-1.5 py-0.5 text-amber-300">input required</span>}
          <span className="ml-auto normal-case tracking-normal text-slate-800">{formatDateTime(message.created_at)}</span>
        </div>
        <MarkdownContent content={message.content_text ?? ""} />
      </div>
    </motion.article>
  );
}

function IntermediateResponses({ messages, backend }: { messages: Message[]; backend: Task["backend"] }) {
  const [open, setOpen] = useState(false);
  return (
    <motion.section layout className="border-b border-white/[0.055] bg-white/[0.008] last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-white/[0.02]"
        aria-expanded={open}
      >
        <span className="grid h-7 w-7 place-items-center rounded-lg border border-white/[0.07] bg-white/[0.025] text-slate-600">
          <Code2 className="h-3.5 w-3.5" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-xs text-slate-400">
            {messages.length} intermediate {messages.length === 1 ? "update" : "updates"}
          </span>
          <span className="mt-0.5 block truncate text-[0.62rem] text-slate-700">
            {messages.at(-1)?.content_text?.split("\n")[0] || `${backendLabel(backend)} progress`}
          </span>
        </span>
        <span className="hidden font-mono text-[0.56rem] uppercase tracking-wider text-slate-700 sm:block">collapsed</span>
        <ChevronDown className={cn("h-3.5 w-3.5 text-slate-700 transition-transform", open && "rotate-180")} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="border-t border-white/[0.05]">
              {messages.map((message, index) => (
                <div key={message.id} className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-3 border-b border-white/[0.045] px-4 py-3.5 last:border-b-0">
                  <span className="flex justify-center pt-1 font-mono text-[0.6rem] text-slate-700">{String(index + 1).padStart(2, "0")}</span>
                  <div className="min-w-0">
                    <div className="mb-1.5 flex items-center gap-2 font-mono text-[0.56rem] uppercase tracking-wider text-slate-700">
                      <CornerDownRight className="h-3 w-3" /> {backendLabel(backend)} update
                      <span className="ml-auto normal-case tracking-normal text-slate-800">{formatDateTime(message.created_at)}</span>
                    </div>
                    <MarkdownContent content={message.content_text ?? ""} className="text-slate-400" />
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.section>
  );
}

function WorkingLine({ backend }: { backend: Task["backend"] }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="flex items-center gap-3 px-4 py-3 font-mono text-[0.66rem] text-slate-600"
    >
      <span className="text-signal-400">›</span>
      <span>{backendLabel(backend)} is working</span>
      <span className="flex gap-1">
        <i className="h-1 w-1 animate-bounce rounded-full bg-signal-400 [animation-delay:-0.2s]" />
        <i className="h-1 w-1 animate-bounce rounded-full bg-signal-400 [animation-delay:-0.1s]" />
        <i className="h-1 w-1 animate-bounce rounded-full bg-signal-400" />
      </span>
    </motion.div>
  );
}

function collapseIntermediateResponses(messages: Message[]): ThreadItem[] {
  const items: ThreadItem[] = [];
  let agentMessages: Message[] = [];

  const flushAgents = () => {
    if (agentMessages.length > 1) {
      items.push({
        type: "intermediate",
        id: `intermediate-${agentMessages[0].id}`,
        messages: agentMessages.slice(0, -1),
      });
    }
    const latest = agentMessages.at(-1);
    if (latest) items.push({ type: "message", message: latest });
    agentMessages = [];
  };

  for (const message of messages) {
    if (message.sender === "agent" && !message.is_blocking_question) {
      agentMessages.push(message);
      continue;
    }
    flushAgents();
    items.push({ type: "message", message });
  }
  flushAgents();
  return items;
}

export function TerminalFrame({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-[#05070b]">
      <div className="flex h-8 shrink-0 items-center gap-1.5 border-b border-white/[0.06] bg-[#090b10] px-3" aria-hidden="true">
        <span className="h-2 w-2 rounded-full bg-red-400/55" />
        <span className="h-2 w-2 rounded-full bg-amber-400/55" />
        <span className="h-2 w-2 rounded-full bg-signal-400/55" />
        <span className="ml-2 flex items-center gap-1.5 font-mono text-[0.56rem] uppercase tracking-[0.12em] text-slate-700">
          <Sparkles className="h-3 w-3" /> live agent terminal
        </span>
      </div>
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  );
}
