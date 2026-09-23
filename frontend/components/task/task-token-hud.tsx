"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Gauge, Layers3, Zap } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { Task, TaskInvocation } from "@/lib/types";
import { cn } from "@/lib/utils";

export function TaskTokenHud({
  tokenUsage,
  task,
  invocations,
}: {
  tokenUsage: { used: number; limit: number } | null;
  task: Task;
  invocations: TaskInvocation[];
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const totals = invocations.reduce(
    (sum, item) => ({
      input: sum.input + item.input_tokens,
      output: sum.output + item.output_tokens,
      cached: sum.cached + item.cached_tokens,
    }),
    { input: 0, output: 0, cached: 0 },
  );
  const activeUsed = tokenUsage?.used ?? totals.input + totals.output;
  const percentage = tokenUsage?.limit ? Math.min((activeUsed / tokenUsage.limit) * 100, 100) : 0;

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="dialog"
        className={cn(
          "flex h-9 items-center gap-2 rounded-xl border px-2.5 transition max-sm:w-9 max-sm:justify-center max-sm:px-0",
          open
            ? "border-signal-400/25 bg-signal-400/[0.075] text-signal-200"
            : "border-white/[0.08] bg-white/[0.025] text-slate-400 hover:border-white/15 hover:text-slate-200",
        )}
      >
        <Gauge className="h-3.5 w-3.5 text-signal-400" />
        <span className="hidden font-mono text-[0.68rem] font-medium tabular-nums sm:inline">
          {compact(activeUsed)}
        </span>
        <span className="hidden text-[0.58rem] text-slate-600 sm:inline">tokens</span>
        <span className="hidden h-1 w-12 overflow-hidden rounded-full bg-white/[0.07] lg:block">
          <motion.span
            className="block h-full rounded-full bg-gradient-to-r from-signal-500 to-pulse-500"
            animate={{ width: tokenUsage?.limit ? `${percentage}%` : activeUsed ? "100%" : "0%" }}
          />
        </span>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            role="dialog"
            aria-label="Task token usage"
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.15 }}
            className="surface absolute right-0 top-[calc(100%+0.5rem)] z-30 w-72 rounded-xl p-4 shadow-panel"
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-slate-200">Token activity</p>
                <p className="mt-1 text-[0.62rem] text-slate-600">Across {invocations.length} runtime {invocations.length === 1 ? "call" : "calls"}</p>
              </div>
              <span className="rounded-lg border border-signal-400/15 bg-signal-400/[0.06] px-2 py-1 font-mono text-[0.62rem] text-signal-300">
                {tokenUsage?.limit ? `${Math.round(percentage)}% active` : "session total"}
              </span>
            </div>

            {tokenUsage?.limit ? (
              <div className="mt-4">
                <div className="mb-2 flex items-end justify-between font-mono tabular-nums">
                  <span className="text-lg font-semibold text-white">{activeUsed.toLocaleString()}</span>
                  <span className="text-[0.62rem] text-slate-600">/ {tokenUsage.limit.toLocaleString()}</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${percentage}%` }}
                    className="h-full rounded-full bg-gradient-to-r from-signal-500 to-pulse-500"
                  />
                </div>
              </div>
            ) : null}

            <div className="mt-4 grid grid-cols-3 gap-2">
              <TokenMetric label="Input" value={totals.input} tone="text-signal-300" />
              <TokenMetric label="Output" value={totals.output} tone="text-pulse-300" />
              <TokenMetric label="Cached" value={totals.cached} tone="text-blue-300" />
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2 border-t border-white/[0.06] pt-3">
              <div className="flex items-center gap-2 rounded-lg bg-black/15 px-2.5 py-2">
                <Layers3 className="h-3.5 w-3.5 text-slate-600" />
                <div><p className="text-[0.55rem] uppercase tracking-wider text-slate-700">Context</p><p className="mt-0.5 text-[0.66rem] text-slate-300">{task.context_strategy}</p></div>
              </div>
              <div className="flex items-center gap-2 rounded-lg bg-black/15 px-2.5 py-2">
                <Zap className="h-3.5 w-3.5 text-slate-600" />
                <div><p className="text-[0.55rem] uppercase tracking-wider text-slate-700">Thinking</p><p className="mt-0.5 text-[0.66rem] text-slate-300">{task.thinking_level}</p></div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function TokenMetric({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-black/15 px-2.5 py-2">
      <p className="text-[0.55rem] uppercase tracking-wider text-slate-700">{label}</p>
      <p className={cn("mt-1 font-mono text-xs font-medium tabular-nums", tone)}>{compact(value)}</p>
    </div>
  );
}

function compact(value: number): string {
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}
