"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  Check,
  ChevronDown,
  Clock3,
  Code2,
  Copy,
  Download,
  Eye,
  FileText,
  GitBranch,
  Pencil,
  RotateCcw,
  Save,
  Sparkles,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { MarkdownContent } from "@/components/ui/markdown-content";
import { useToast } from "@/components/ui/toast";
import { changedLineIndexes, extractMagicArtifact, type CanvasFormat } from "@/lib/magic-canvas";
import type { Message } from "@/lib/types";
import { cn, formatDateTime } from "@/lib/utils";

interface CanvasVersion {
  id: string;
  content: string;
  createdAt: string;
  format: CanvasFormat;
  language: string | null;
  reason: "ai" | "manual" | "revert";
  sourceMessageId?: string;
  title: string;
}

const MAX_VERSIONS = 40;

export function MagicCanvas({
  taskId,
  messages,
  open,
  onOpenChange,
}: {
  taskId: string;
  messages: Message[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const storageKey = `muster:magic-canvas:${taskId}`;
  const [versions, setVersions] = useState<CanvasVersion[]>([]);
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<"preview" | "edit">("preview");
  const [hydrated, setHydrated] = useState(false);
  const [copied, setCopied] = useState(false);
  const [recentlyUpdated, setRecentlyUpdated] = useState(false);
  const updateTimer = useRef<number | undefined>(undefined);
  const toast = useToast();
  const current = versions.at(-1);
  const previous = versions.at(-2);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(storageKey);
      // Hydrate the external browser store after mount to avoid an SSR mismatch.
      if (stored) {
        const parsed: unknown = JSON.parse(stored);
        // eslint-disable-next-line react-hooks/set-state-in-effect
        if (Array.isArray(parsed)) setVersions(parsed as CanvasVersion[]);
      }
    } catch {
      // A malformed local draft should not prevent the task from opening.
    } finally {
      setHydrated(true);
    }
  }, [storageKey]);

  useEffect(() => {
    if (!hydrated) return;
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(versions));
    } catch {
      // Keep the in-memory workspace usable when browser storage is unavailable or full.
    }
    // Keep the editor buffer aligned when AI or history selects a new version.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDraft(versions.at(-1)?.content ?? "");
  }, [hydrated, storageKey, versions]);

  useEffect(() => {
    if (!hydrated) return;
    const knownMessages = new Set(versions.map((version) => version.sourceMessageId).filter(Boolean));
    const incoming = messages.flatMap((message) => {
      if (message.sender !== "agent" || knownMessages.has(message.id)) return [];
      const artifact = extractMagicArtifact(message);
      return artifact ? [{ artifact, sourceMessageId: message.id }] : [];
    });
    if (!incoming.length) return;

    // Ingest history oldest-first so the latest assistant artifact remains current.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setVersions((currentVersions) => {
      const additions = incoming.reduce<CanvasVersion[]>((items, item) => {
        const previousContent = items.at(-1)?.content ?? currentVersions.at(-1)?.content;
        if (item.artifact.content === previousContent) return items;
        items.push({
          id: crypto.randomUUID(),
          ...item.artifact,
          createdAt: new Date().toISOString(),
          reason: "ai",
          sourceMessageId: item.sourceMessageId,
        });
        return items;
      }, []);
      return [...currentVersions, ...additions].slice(-MAX_VERSIONS);
    });
    setMode("preview");
    setRecentlyUpdated(true);
    onOpenChange(true);
    window.clearTimeout(updateTimer.current);
    updateTimer.current = window.setTimeout(() => setRecentlyUpdated(false), 2800);
  }, [hydrated, messages, onOpenChange, versions]);

  useEffect(() => () => window.clearTimeout(updateTimer.current), []);

  const saveDraft = () => {
    if (!current || !draft.trim() || draft === current.content) return;
    setVersions((items) => [...items, { ...current, id: crypto.randomUUID(), content: draft, createdAt: new Date().toISOString(), reason: "manual" as const, sourceMessageId: undefined }].slice(-MAX_VERSIONS));
    setMode("preview");
    toast("Canvas version saved", "success");
  };

  const restoreVersion = (id: string) => {
    const selected = versions.find((version) => version.id === id);
    if (!selected || selected.id === current?.id) return;
    setVersions((items) => [...items, { ...selected, id: crypto.randomUUID(), createdAt: new Date().toISOString(), reason: "revert" as const, sourceMessageId: undefined }].slice(-MAX_VERSIONS));
    setMode("preview");
    toast("Previous version restored", "success");
  };

  const copy = async () => {
    if (!current) return;
    await navigator.clipboard.writeText(current.content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  };

  const download = () => {
    if (!current) return;
    const extension = current.format === "diagram" ? "mmd" : current.format === "markdown" ? "md" : extensionFor(current.language);
    const blob = new Blob([current.content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${slugify(current.title)}.${extension}`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  if (!open) return null;

  return (
    <motion.aside
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      className="surface flex h-full min-h-0 flex-col overflow-hidden rounded-xl"
      aria-label="Magic Canvas"
    >
      <header className="shrink-0 border-b border-white/[0.07] bg-gradient-to-r from-pulse-400/[0.07] to-signal-400/[0.04] px-3 py-3">
        <div className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg border border-pulse-400/20 bg-pulse-400/10 text-pulse-400"><Sparkles className="h-4 w-4" /></span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2"><h2 className="text-sm font-semibold text-white">Magic Canvas</h2>{current && <FormatBadge format={current.format} />}</div>
            <p className="truncate text-[0.62rem] text-slate-600">{current?.title ?? "Your live artifact workspace"}</p>
          </div>
          <Button size="icon" variant="ghost" onClick={() => onOpenChange(false)} aria-label="Close Magic Canvas"><X className="h-4 w-4" /></Button>
        </div>
        {current && (
          <div className="mt-3 flex items-center gap-1.5 overflow-x-auto">
            <div className="flex rounded-lg border border-white/[0.07] bg-black/20 p-0.5">
              <button type="button" onClick={() => setMode("preview")} className={cn("flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[0.62rem] transition", mode === "preview" ? "bg-white/[0.08] text-white" : "text-slate-600 hover:text-slate-300")}><Eye className="h-3 w-3" /> Preview</button>
              <button type="button" onClick={() => setMode("edit")} className={cn("flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[0.62rem] transition", mode === "edit" ? "bg-white/[0.08] text-white" : "text-slate-600 hover:text-slate-300")}><Pencil className="h-3 w-3" /> Edit</button>
            </div>
            <div className="relative ml-auto min-w-0">
              <select value={current.id} onChange={(event) => restoreVersion(event.target.value)} className="h-8 max-w-40 appearance-none rounded-lg border border-white/[0.08] bg-black/20 pl-7 pr-7 text-[0.62rem] text-slate-400 outline-none transition hover:border-white/15 focus:border-signal-400/40" aria-label="Canvas version history">
                {versions.toReversed().map((version, index) => <option key={version.id} value={version.id}>{index === 0 ? "Current" : `Version ${versions.length - index}`} · {version.reason}</option>)}
              </select>
              <Clock3 className="pointer-events-none absolute left-2 top-2 h-3 w-3 text-slate-600" />
              <ChevronDown className="pointer-events-none absolute right-2 top-2 h-3 w-3 text-slate-600" />
            </div>
            <Button size="icon" variant="ghost" onClick={() => previous && restoreVersion(previous.id)} disabled={!previous} aria-label="Undo last Canvas change"><RotateCcw className="h-3.5 w-3.5" /></Button>
          </div>
        )}
      </header>

      <div className="relative min-h-0 flex-1 overflow-auto bg-[#07090e]">
        <AnimatePresence>
          {recentlyUpdated && (
            <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="sticky top-0 z-10 flex items-center gap-2 border-b border-signal-400/15 bg-signal-400/[0.08] px-3 py-2 text-[0.66rem] text-signal-200 backdrop-blur-xl"><Sparkles className="h-3.5 w-3.5" /> Updated in place · changed lines are highlighted</motion.div>
          )}
        </AnimatePresence>
        {!current ? (
          <div className="grid h-full min-h-72 place-items-center p-8 text-center"><div><span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl border border-white/[0.08] bg-white/[0.03] text-slate-600"><FileText className="h-5 w-5" /></span><h3 className="mt-4 text-sm font-medium text-slate-200">Canvas is ready</h3><p className="mx-auto mt-2 max-w-xs text-xs leading-5 text-slate-600">Ask the agent for code, a PRD, Markdown, or a Mermaid diagram. Structured output will open here automatically.</p></div></div>
        ) : mode === "edit" ? (
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)} className="h-full min-h-[28rem] w-full resize-none bg-transparent p-5 font-mono text-xs leading-6 text-slate-300 outline-none placeholder:text-slate-700" spellCheck={current.format === "markdown"} aria-label="Edit Canvas content" />
        ) : current.format === "markdown" ? (
          <div className={cn("mx-auto max-w-3xl p-5 transition", recentlyUpdated && "bg-signal-400/[0.018]")}><MarkdownContent content={current.content} /></div>
        ) : current.format === "diagram" ? (
          <DiagramPreview source={current.content} />
        ) : (
          <CodePreview content={current.content} previous={previous?.content ?? ""} highlight={recentlyUpdated} language={current.language} />
        )}
      </div>

      {current && (
        <footer className="flex shrink-0 items-center gap-1.5 border-t border-white/[0.07] bg-black/10 p-2.5">
          <p className="hidden min-w-0 flex-1 truncate px-1 text-[0.58rem] text-slate-700 sm:block">{versions.length} {versions.length === 1 ? "version" : "versions"} · {formatDateTime(current.createdAt)}</p>
          <Button size="sm" variant="ghost" onClick={copy}>{copied ? <Check className="h-3.5 w-3.5 text-signal-400" /> : <Copy className="h-3.5 w-3.5" />}{copied ? "Copied" : "Copy"}</Button>
          <Button size="sm" variant="ghost" onClick={download}><Download className="h-3.5 w-3.5" /> Export</Button>
          {mode === "edit" && <Button size="sm" variant="primary" onClick={saveDraft} disabled={draft === current.content || !draft.trim()}><Save className="h-3.5 w-3.5" /> Save version</Button>}
        </footer>
      )}
    </motion.aside>
  );
}

function FormatBadge({ format }: { format: CanvasFormat }) {
  const Icon = format === "code" ? Code2 : format === "diagram" ? GitBranch : FileText;
  return <span className="inline-flex items-center gap-1 rounded-md border border-white/[0.07] bg-white/[0.035] px-1.5 py-0.5 font-mono text-[0.52rem] uppercase tracking-wider text-slate-500"><Icon className="h-2.5 w-2.5" />{format}</span>;
}

function CodePreview({ content, previous, highlight, language }: { content: string; previous: string; highlight: boolean; language: string | null }) {
  const changed = useMemo(() => changedLineIndexes(previous, content), [content, previous]);
  return <div className="min-w-max p-4"><div className="mb-3 font-mono text-[0.58rem] uppercase tracking-wider text-slate-700">{language || "code"}</div><pre className="font-mono text-xs leading-6"><code>{content.split("\n").map((line, index) => <span key={`${index}-${line.slice(0, 12)}`} className={cn("grid grid-cols-[2.5rem_minmax(0,1fr)] rounded px-1 transition-colors", highlight && changed.has(index) && "bg-signal-400/[0.09]")}><span className="select-none pr-3 text-right text-slate-800">{index + 1}</span><span className="whitespace-pre text-slate-300"><SyntaxLine line={line} /></span></span>)}</code></pre></div>;
}

const CODE_TOKEN = /(\/\/.*$|#.*$|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\b(?:async|await|break|case|catch|class|const|continue|def|else|export|extends|false|finally|for|from|function|if|import|in|interface|let|new|null|return|throw|true|try|type|undefined|while|yield)\b|\b\d+(?:\.\d+)?\b)/gm;

function SyntaxLine({ line }: { line: string }) {
  return line.split(CODE_TOKEN).map((token, index) => {
    if (!token) return null;
    const className = token.startsWith("//") || token.startsWith("#")
      ? "text-slate-600"
      : /^["'`]/.test(token)
        ? "text-emerald-300"
        : /^\d/.test(token)
          ? "text-amber-300"
          : /^(async|await|break|case|catch|class|const|continue|def|else|export|extends|false|finally|for|from|function|if|import|in|interface|let|new|null|return|throw|true|try|type|undefined|while|yield)$/.test(token)
            ? "text-pulse-400"
            : undefined;
    return <span key={`${index}-${token}`} className={className}>{token}</span>;
  });
}

function DiagramPreview({ source }: { source: string }) {
  const nodes = useMemo(() => diagramNodes(source), [source]);
  return <div className="mx-auto flex min-h-full max-w-2xl flex-col items-center justify-center gap-2 p-8">{nodes.length > 1 ? nodes.map((node, index) => <div key={`${node}-${index}`} className="contents"><div className="w-full max-w-sm rounded-xl border border-pulse-400/20 bg-pulse-400/[0.06] px-4 py-3 text-center text-xs text-slate-200 shadow-panel">{node}</div>{index < nodes.length - 1 && <div className="h-7 w-px bg-gradient-to-b from-pulse-400/50 to-signal-400/50" />}</div>) : <pre className="w-full overflow-auto rounded-xl border border-white/[0.08] bg-black/20 p-4 font-mono text-xs leading-6 text-slate-300">{source}</pre>}<details className="mt-5 w-full max-w-lg"><summary className="cursor-pointer text-center text-[0.62rem] text-slate-600 hover:text-slate-400">View Mermaid source</summary><pre className="mt-3 overflow-auto rounded-xl border border-white/[0.07] bg-black/20 p-3 font-mono text-[0.66rem] leading-5 text-slate-500">{source}</pre></details></div>;
}

function diagramNodes(source: string) {
  const labels = [...source.matchAll(/(?:^|-->|---|==>)[\s]*[\w-]+(?:\[|\(|\{)([^\]\)\}]+)[\]\)\}]/gm)].map((match) => match[1].replace(/["']/g, "").trim());
  return [...new Set(labels)].slice(0, 12);
}

function extensionFor(language: string | null) {
  const extensions: Record<string, string> = { javascript: "js", js: "js", typescript: "ts", ts: "ts", tsx: "tsx", jsx: "jsx", python: "py", py: "py", bash: "sh", shell: "sh", json: "json", html: "html", css: "css", sql: "sql" };
  return extensions[language ?? ""] ?? "txt";
}

function slugify(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "magic-canvas";
}
