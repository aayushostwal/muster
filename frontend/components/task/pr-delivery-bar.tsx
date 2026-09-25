"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  Check,
  ExternalLink,
  GitBranch,
  GitPullRequest,
  Loader2,
  RotateCcw,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { ListResponse, PrDeliveryRun } from "@/lib/types";

/**
 * Inline PR delivery surface for the task terminal: a passive "Changes
 * ready" suggestion, a pre-mutation confirmation card, progress, and
 * success/failure states. Modeled on `ToolApprovalBar` in task-console.tsx
 * (same interaction pattern: nothing external happens without an explicit
 * user decision on an inline card) -- see docs/SPEC.md "PR delivery".
 */
export function PrDeliveryPanel({
  taskId,
  suggestion,
  requestOpen,
  onOpenHandled,
}: {
  taskId: string;
  suggestion: { eligibleFileCount: number } | null;
  /** Bumped by the "Prepare PR" quick action / `/pr` command to trigger prepare(). */
  requestOpen: number;
  onOpenHandled?: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [trackedRunId, setTrackedRunId] = useState<string | null>(null);
  const [dismissedRunId, setDismissedRunId] = useState<string | null>(null);
  const [dismissedSuggestionKey, setDismissedSuggestionKey] = useState<string | null>(null);

  const eligibility = useQuery({
    queryKey: ["pr-delivery-eligibility", taskId],
    queryFn: () => api.prDeliveryEligibility(taskId),
  });
  const runs = useQuery({
    queryKey: ["pr-delivery-runs", taskId],
    queryFn: () => api.prDeliveryRuns(taskId),
  });

  const prepare = useMutation({
    mutationFn: (overrides: { draft?: boolean } = {}) => api.preparePrDelivery(taskId, overrides),
    onSuccess: (run) => {
      setTrackedRunId(run.id);
      setDismissedRunId(null);
      setDismissedSuggestionKey(`prepared:${run.id}`);
      queryClient.setQueryData<ListResponse<PrDeliveryRun>>(["pr-delivery-runs", taskId], (current) => {
        const items = current?.items ?? [];
        const index = items.findIndex((item) => item.id === run.id);
        if (index < 0) return { items: [...items, run] };
        return { items: items.map((item) => (item.id === run.id ? run : item)) };
      });
      queryClient.invalidateQueries({ queryKey: ["pr-delivery-eligibility", taskId] });
      onOpenHandled?.();
    },
    onError: (error: Error) => {
      toast(error.message, "error");
      onOpenHandled?.();
    },
  });

  // Fired by the "Prepare PR" quick action / `/pr` command -- both resolve
  // to this same call, per requirement. Guarded against an in-flight call
  // so rapid repeated clicks collapse into the one already running instead
  // of firing a second request the backend would just 422 as "in progress".
  useEffect(() => {
    if (requestOpen > 0 && !prepare.isPending) prepare.mutate({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestOpen]);

  const activeRunId = eligibility.data?.active_run?.id ?? null;
  const effectiveRunId = trackedRunId ?? (activeRunId !== dismissedRunId ? activeRunId : null);
  const trackedRun = effectiveRunId
    ? runs.data?.items.find((item) => item.id === effectiveRunId)
      ?? (eligibility.data?.active_run?.id === effectiveRunId ? eligibility.data.active_run : null)
    : null;
  const dismiss = () => {
    setDismissedRunId(effectiveRunId);
    setTrackedRunId(null);
  };
  const effectiveSuggestion = suggestion ?? (
    eligibility.data?.eligible && eligibility.data.policy !== "manual"
      ? { eligibleFileCount: eligibility.data.eligible_paths.length }
      : null
  );

  if (trackedRun) {
    return <PrDeliveryRunCard key={trackedRun.id} taskId={taskId} run={trackedRun} onDismiss={dismiss} onRetry={() => prepare.mutate({})} />;
  }

  const suggestionKey = effectiveSuggestion
    ? `${effectiveSuggestion.eligibleFileCount}:${eligibility.data?.eligible_paths.join("|") ?? "live"}`
    : null;
  if (effectiveSuggestion && dismissedSuggestionKey !== suggestionKey) {
    return (
      <PrSuggestionBanner
        fileCount={effectiveSuggestion.eligibleFileCount}
        loading={prepare.isPending}
        onDismiss={() => setDismissedSuggestionKey(suggestionKey)}
        onPrepare={() => prepare.mutate({})}
      />
    );
  }

  return null;
}

function PrSuggestionBanner({
  fileCount,
  loading,
  onDismiss,
  onPrepare,
}: {
  fileCount: number;
  loading: boolean;
  onDismiss: () => void;
  onPrepare: () => void;
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="mt-2 flex flex-col gap-3 rounded-xl border border-signal-400/20 bg-signal-400/[0.05] px-3 py-3 sm:flex-row sm:items-center"
    >
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-signal-400/20 bg-signal-400/[0.07] text-signal-400">
          <GitPullRequest className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="text-xs font-medium text-signal-100">Changes ready</p>
          <p className="mt-1 text-[0.62rem] text-signal-100/50">
            {fileCount} file{fileCount === 1 ? "" : "s"} changed by this task. Raise a PR?
          </p>
        </div>
      </div>
      <div className="flex shrink-0 gap-1.5">
        <Button size="sm" variant="ghost" onClick={onDismiss} aria-label="Dismiss PR suggestion">
          Not now
        </Button>
        <Button size="sm" variant="primary" loading={loading} onClick={onPrepare}>
          <GitPullRequest className="h-3.5 w-3.5" /> Raise PR
        </Button>
      </div>
    </motion.section>
  );
}

const stageLabel: Record<string, string> = {
  awaiting_confirmation: "Awaiting confirmation",
  validating: "Running validation",
  pushing: "Pushing branch",
  creating_pr: "Creating pull request",
  succeeded: "PR delivered",
  failed: "PR delivery failed",
  rejected: "Not delivered",
};

function PrDeliveryRunCard({
  taskId,
  run,
  onDismiss,
  onRetry,
}: {
  taskId: string;
  run: PrDeliveryRun;
  onDismiss: () => void;
  onRetry: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [commitMessage, setCommitMessage] = useState(run.commit_message ?? "");
  const [prTitle, setPrTitle] = useState(run.pr_title ?? "");
  const [prBody, setPrBody] = useState(run.pr_body ?? "");
  const [draft, setDraft] = useState(run.draft);

  const applyRun = (updated: PrDeliveryRun) => {
    queryClient.setQueryData<ListResponse<PrDeliveryRun>>(["pr-delivery-runs", taskId], (current) => ({
      items: (current?.items ?? []).map((item) => (item.id === updated.id ? updated : item)),
    }));
    queryClient.invalidateQueries({ queryKey: ["pr-delivery-eligibility", taskId] });
  };

  const confirm = useMutation({
    mutationFn: () =>
      api.confirmPrDelivery(taskId, run.id, {
        commit_message: commitMessage || undefined,
        pr_title: prTitle || undefined,
        pr_body: prBody || undefined,
        draft,
      }),
    onSuccess: (updated) => {
      applyRun(updated);
      if (updated.status === "succeeded") toast("Pull request raised", "success");
      if (updated.status === "failed") toast(updated.error_message || "PR delivery failed", "error");
    },
    onError: (error: Error) => toast(error.message, "error"),
  });

  const cancel = useMutation({
    mutationFn: () => api.cancelPrDelivery(taskId, run.id),
    onSuccess: (updated) => {
      applyRun(updated);
      onDismiss();
    },
    onError: (error: Error) => toast(error.message, "error"),
  });

  const busy = confirm.isPending;
  const inFlight = ["validating", "pushing", "creating_pr"].includes(run.status);

  if (run.status === "succeeded") {
    return (
      <motion.section initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mt-2 flex flex-col gap-3 rounded-xl border border-emerald-400/20 bg-emerald-400/[0.05] px-3 py-3 sm:flex-row sm:items-center">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-emerald-400/20 bg-emerald-400/[0.07] text-emerald-300">
            <Check className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-medium text-emerald-100">Pull request raised</p>
            <p className="mt-1 truncate text-[0.62rem] text-emerald-100/60">
              {run.repository ?? "Repository"} · {run.head_branch} → {run.base_branch}
              {run.draft ? " · Draft" : ""}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {run.pr_url && (
            <a href={run.pr_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-400/25 bg-emerald-400/10 px-3 py-1.5 text-xs font-medium text-emerald-200 transition hover:bg-emerald-400/15">
              <ExternalLink className="h-3.5 w-3.5" /> {run.pr_number ? `#${run.pr_number}` : "View PR"}
            </a>
          )}
          <Button size="sm" variant="ghost" onClick={onDismiss} aria-label="Dismiss">
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      </motion.section>
    );
  }

  if (run.status === "failed") {
    return (
      <motion.section initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mt-2 flex flex-col gap-3 rounded-xl border border-red-400/20 bg-red-400/[0.05] px-3 py-3 sm:flex-row sm:items-center">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-red-400/20 bg-red-400/[0.07] text-red-300">
            <AlertTriangle className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <p className="text-xs font-medium text-red-100">PR delivery failed</p>
            <p className="mt-1 line-clamp-2 text-[0.62rem] leading-4 text-red-100/60">{run.error_message || "Unknown error"}</p>
          </div>
        </div>
        <div className="flex shrink-0 gap-1.5">
          <Button size="sm" variant="ghost" onClick={onDismiss}>
            Dismiss
          </Button>
          <Button size="sm" variant="primary" onClick={onRetry}>
            <RotateCcw className="h-3.5 w-3.5" /> Prepare again
          </Button>
        </div>
      </motion.section>
    );
  }

  if (inFlight) {
    return (
      <motion.section initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mt-2 flex items-center gap-3 rounded-xl border border-signal-400/20 bg-signal-400/[0.05] px-3 py-3" aria-live="polite">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-signal-400/20 bg-signal-400/[0.07] text-signal-400">
          <Loader2 className="h-4 w-4 animate-spin" />
        </span>
        <p className="text-xs text-signal-100">{stageLabel[run.status]}…</p>
      </motion.section>
    );
  }

  // awaiting_confirmation: full pre-mutation confirmation card.
  return (
    <motion.section initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="mt-2 rounded-xl border border-amber-400/20 bg-amber-400/[0.05] p-3">
      <div className="flex items-start gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-amber-400/20 bg-amber-400/[0.07] text-amber-400">
          <GitPullRequest className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-amber-100">Raise a pull request?</p>
          <p className="mt-1 flex items-center gap-1.5 text-[0.62rem] text-amber-100/60">
            <GitBranch className="h-3 w-3" /> {run.head_branch} <span className="text-amber-100/30">into</span> {run.base_branch}
            <span className="text-amber-100/30">·</span> {run.remote_name}
            {run.draft && <span className="text-amber-100/30">· draft</span>}
          </p>
        </div>
      </div>

      <div className="mt-3 space-y-2.5">
        <div>
          <p className="text-[0.56rem] uppercase tracking-wider text-amber-100/40">
            Files ({run.file_paths.length})
          </p>
          <ul className="mt-1 max-h-28 space-y-0.5 overflow-y-auto rounded-lg border border-amber-400/10 bg-black/15 p-2 font-mono text-[0.62rem] text-amber-100/70">
            {run.file_paths.map((path) => (
              <li key={path} className="truncate">{path}</li>
            ))}
          </ul>
          {run.excluded_paths.length > 0 && (
            <p className="mt-1 text-[0.58rem] text-amber-100/40">
              {run.excluded_paths.length} pre-existing/unrelated file{run.excluded_paths.length === 1 ? "" : "s"} excluded.
            </p>
          )}
        </div>

        <label className="block">
          <span className="text-[0.56rem] uppercase tracking-wider text-amber-100/40">Commit message</span>
          <textarea
            value={commitMessage}
            onChange={(event) => setCommitMessage(event.target.value)}
            rows={2}
            className="mt-1 w-full resize-none rounded-lg border border-amber-400/15 bg-black/15 px-2.5 py-2 font-mono text-[0.62rem] text-amber-100/80 focus:border-amber-400/30 focus:outline-none"
          />
        </label>

        <label className="block">
          <span className="text-[0.56rem] uppercase tracking-wider text-amber-100/40">PR title</span>
          <input
            value={prTitle}
            onChange={(event) => setPrTitle(event.target.value)}
            className="mt-1 w-full rounded-lg border border-amber-400/15 bg-black/15 px-2.5 py-1.5 text-xs text-amber-100/80 focus:border-amber-400/30 focus:outline-none"
          />
        </label>

        <label className="block">
          <span className="text-[0.56rem] uppercase tracking-wider text-amber-100/40">PR body</span>
          <textarea
            value={prBody}
            onChange={(event) => setPrBody(event.target.value)}
            rows={3}
            className="mt-1 w-full resize-none rounded-lg border border-amber-400/15 bg-black/15 px-2.5 py-2 font-mono text-[0.6rem] leading-4 text-amber-100/70 focus:border-amber-400/30 focus:outline-none"
          />
        </label>

        <label className="flex items-center gap-2 text-[0.65rem] text-amber-100/70">
          <input type="checkbox" checked={draft} onChange={(event) => setDraft(event.target.checked)} className="h-3.5 w-3.5 rounded border-amber-400/30 bg-black/20" />
          Open as draft
        </label>
      </div>

      <div className="mt-3 flex flex-wrap justify-end gap-1.5">
        <Button size="sm" variant="ghost" loading={cancel.isPending} onClick={() => cancel.mutate()}>
          Cancel
        </Button>
        <Button size="sm" variant="primary" loading={busy} disabled={run.file_paths.length === 0} onClick={() => confirm.mutate()}>
          <GitPullRequest className="h-3.5 w-3.5" /> Confirm &amp; raise PR
        </Button>
      </div>
    </motion.section>
  );
}
