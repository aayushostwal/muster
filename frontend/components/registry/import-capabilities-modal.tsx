"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  Bot,
  Check,
  ChevronDown,
  Network,
  PackageSearch,
  RefreshCcw,
  Sparkles,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type {
  CapabilityImportKind,
  CapabilityImportPreview,
  CapabilityImportRuntime,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type FilterKind = CapabilityImportKind | "all";
type FilterRuntime = CapabilityImportRuntime | "all";

const kindMeta = {
  agent: { label: "Agents", icon: Bot },
  skill: { label: "Skills", icon: Sparkles },
  mcp: { label: "MCPs", icon: Network },
};

const statusLabel = {
  new: "New",
  updated: "Source changed",
  unchanged: "Up to date",
};

export function ImportCapabilitiesModal({
  open,
  onClose,
  initialKind,
}: {
  open: boolean;
  onClose: () => void;
  initialKind: CapabilityImportKind;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [kind, setKind] = useState<FilterKind>(initialKind);
  const [runtime, setRuntime] = useState<FilterRuntime>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const query = useQuery({
    queryKey: ["capability-imports", "discovery"],
    queryFn: api.discoverCapabilityImports,
    enabled: open,
  });
  const visible = useMemo(
    () =>
      (query.data?.items ?? []).filter(
        (item) =>
          (kind === "all" || item.resource_type === kind) &&
          (runtime === "all" || item.source_runtime === runtime),
      ),
    [kind, query.data?.items, runtime],
  );

  const close = () => {
    setSelected(new Set());
    setKind(initialKind);
    setRuntime("all");
    onClose();
  };

  const importMutation = useMutation({
    mutationFn: () => api.importCapabilities([...selected]),
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["registry"] }),
        queryClient.invalidateQueries({ queryKey: ["capabilities"] }),
        queryClient.invalidateQueries({ queryKey: ["capability-imports"] }),
      ]);
      const changed = result.items.filter((item) => item.action !== "unchanged").length;
      toast(
        changed === 0
          ? "Selected capabilities are already up to date"
          : `${changed} ${changed === 1 ? "capability" : "capabilities"} imported`,
        "success",
      );
      close();
    },
    onError: (error: Error) => toast(error.message, "error"),
  });

  const toggle = (candidateId: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(candidateId)) next.delete(candidateId);
      else next.add(candidateId);
      return next;
    });
  };
  const allVisibleSelected = visible.length > 0 && visible.every((item) => selected.has(item.candidate_id));
  const toggleVisible = () => {
    setSelected((current) => {
      const next = new Set(current);
      for (const item of visible) {
        if (allVisibleSelected) next.delete(item.candidate_id);
        else next.add(item.candidate_id);
      }
      return next;
    });
  };

  return (
    <Modal
      open={open}
      onClose={close}
      title="Import capabilities"
      description="Copy user-level Claude and Codex capabilities into Muster. Source files are never modified."
      wide
    >
      <div className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap gap-1 rounded-xl border border-white/[0.07] bg-black/10 p-1">
            {(["all", "agent", "skill", "mcp"] as FilterKind[]).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setKind(value)}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-xs transition",
                  kind === value
                    ? "bg-white/[0.09] text-white shadow-sm"
                    : "text-slate-500 hover:text-slate-200",
                )}
              >
                {value === "all" ? "All" : kindMeta[value].label}
              </button>
            ))}
          </div>
          <div className="flex gap-1">
            {(["all", "claude", "codex"] as FilterRuntime[]).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setRuntime(value)}
                className={cn(
                  "rounded-lg border px-2.5 py-1.5 text-[0.68rem] transition",
                  runtime === value
                    ? "border-signal-400/20 bg-signal-400/[0.08] text-signal-300"
                    : "border-white/[0.06] text-slate-600 hover:text-slate-300",
                )}
              >
                {value === "all" ? "Both runtimes" : value === "claude" ? "Claude" : "Codex"}
              </button>
            ))}
          </div>
        </div>

        {query.isPending && (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, index) => (
              <Skeleton key={index} className="h-24" />
            ))}
          </div>
        )}
        {query.isError && <ErrorState message={query.error.message} retry={() => query.refetch()} />}
        {query.data?.warnings.map((warning) => (
          <div
            key={warning}
            role="status"
            className="flex gap-2 rounded-xl border border-amber-400/15 bg-amber-400/[0.05] px-3 py-2.5 text-xs text-amber-200/80"
          >
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {warning}
          </div>
        ))}
        {query.isSuccess && (
          <>
            <div className="flex items-center justify-between px-1">
              <button
                type="button"
                onClick={toggleVisible}
                disabled={visible.length === 0}
                className="flex items-center gap-2 text-xs text-slate-400 transition hover:text-white disabled:opacity-40"
              >
                <CheckBox checked={allVisibleSelected} />
                {allVisibleSelected ? "Clear visible" : "Select visible"}
              </button>
              <button
                type="button"
                onClick={() => query.refetch()}
                disabled={query.isFetching}
                className="flex items-center gap-1.5 text-[0.68rem] text-slate-500 transition hover:text-signal-300 disabled:opacity-40"
              >
                <RefreshCcw className={cn("h-3 w-3", query.isFetching && "animate-spin")} />
                Scan again
              </button>
            </div>
            <motion.div layout className="space-y-2">
              <AnimatePresence mode="popLayout" initial={false}>
                {visible.map((item) => (
                  <CapabilityRow
                    key={item.candidate_id}
                    item={item}
                    selected={selected.has(item.candidate_id)}
                    onToggle={() => toggle(item.candidate_id)}
                  />
                ))}
              </AnimatePresence>
              {visible.length === 0 && (
                <div className="rounded-xl border border-dashed border-white/[0.09] px-5 py-10 text-center">
                  <PackageSearch className="mx-auto h-5 w-5 text-slate-700" />
                  <p className="mt-3 text-sm text-slate-400">No matching capabilities found</p>
                  <p className="mt-1 text-xs text-slate-600">Try another filter or scan the local environments again.</p>
                </div>
              )}
            </motion.div>
          </>
        )}

        <div className="flex items-center justify-between border-t border-white/[0.07] pt-4">
          <p className="text-xs text-slate-600">
            {selected.size} selected · imports are snapshots you can re-sync later
          </p>
          <div className="flex gap-2">
            <Button type="button" variant="ghost" onClick={close}>Cancel</Button>
            <Button
              type="button"
              variant="primary"
              disabled={selected.size === 0}
              loading={importMutation.isPending}
              onClick={() => importMutation.mutate()}
            >
              Import selected
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

function CapabilityRow({
  item,
  selected,
  onToggle,
}: {
  item: CapabilityImportPreview;
  selected: boolean;
  onToggle: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const Icon = kindMeta[item.resource_type].icon;
  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.98 }}
      className={cn(
        "overflow-hidden rounded-xl border transition-colors",
        selected
          ? "border-signal-400/20 bg-signal-400/[0.035]"
          : "border-white/[0.07] bg-white/[0.015]",
      )}
    >
      <div className="flex items-start gap-3 p-3.5">
        <button
          type="button"
          onClick={onToggle}
          aria-label={`${selected ? "Exclude" : "Include"} ${item.name}`}
          className="mt-1"
        >
          <CheckBox checked={selected} />
        </button>
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-white/[0.07] bg-white/[0.025] text-signal-400">
          <Icon className="h-3.5 w-3.5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-medium text-white">{item.target_name}</h3>
            <span className="rounded-md border border-white/[0.07] px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wider text-slate-500">
              {item.source_runtime}
            </span>
            <span className={cn(
              "rounded-md px-1.5 py-0.5 text-[0.58rem]",
              item.status === "updated"
                ? "bg-amber-400/10 text-amber-300"
                : item.status === "new"
                  ? "bg-signal-400/10 text-signal-300"
                  : "bg-white/[0.04] text-slate-600",
            )}>
              {statusLabel[item.status]}
            </span>
          </div>
          <p className="mt-1 truncate text-xs text-slate-500">{item.description || item.source_locator}</p>
          {item.warnings.length > 0 && (
            <p className="mt-1.5 flex items-start gap-1.5 text-[0.66rem] leading-4 text-amber-300/70">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
              {item.warnings.join(" · ")}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          aria-label={`${expanded ? "Hide" : "Show"} import details for ${item.name}`}
          className="rounded-lg p-1.5 text-slate-600 transition hover:bg-white/[0.05] hover:text-white"
        >
          <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", expanded && "rotate-180")} />
        </button>
      </div>
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="border-t border-white/[0.06] px-4 py-3">
              <p className="truncate font-mono text-[0.62rem] text-slate-600">{item.source_locator}</p>
              <dl className="mt-2 grid gap-2 sm:grid-cols-2">
                {Object.entries(item.preview).map(([key, value]) => (
                  <div key={key} className="rounded-lg bg-black/15 px-2.5 py-2">
                    <dt className="text-[0.58rem] uppercase tracking-wider text-slate-700">{key.replaceAll("_", " ")}</dt>
                    <dd className="mt-1 truncate font-mono text-[0.66rem] text-slate-400">
                      {formatPreview(value)}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.article>
  );
}

function CheckBox({ checked }: { checked: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "grid h-4 w-4 place-items-center rounded border transition",
        checked
          ? "border-signal-400 bg-signal-400 text-ink-950"
          : "border-white/15 bg-white/[0.02]",
      )}
    >
      {checked && <Check className="h-3 w-3" />}
    </span>
  );
}

function formatPreview(value: unknown): string {
  if (Array.isArray(value)) return value.length > 0 ? value.join(", ") : "None";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (value === null || value === undefined || value === "") return "Not set";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
