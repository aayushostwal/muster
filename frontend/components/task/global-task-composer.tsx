"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowUp,
  AtSign,
  Check,
  ChevronDown,
  Command,
  CornerDownLeft,
  FolderKanban,
  Sparkles,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { cn, initials } from "@/lib/utils";

const MENTION_PATTERN = /(?:^|\s)@([^@\n]*)$/;

export function GlobalTaskComposer({ compact = false }: { compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [project, setProject] = useState<Project | null>(null);
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [error, setError] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const router = useRouter();
  const queryClient = useQueryClient();
  const toast = useToast();
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });

  const suggestions = useMemo(() => {
    const items = projects.data?.items ?? [];
    if (mentionQuery === null) return [];
    const query = mentionQuery.trim().toLocaleLowerCase();
    return items
      .filter((item) => !query || item.name.toLocaleLowerCase().includes(query))
      .slice(0, 6);
  }, [mentionQuery, projects.data?.items]);

  useEffect(() => {
    const handleShortcut = (event: globalThis.KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLocaleLowerCase() === "j") {
        event.preventDefault();
        setOpen(true);
        requestAnimationFrame(() => textareaRef.current?.focus());
      }
    };
    document.addEventListener("keydown", handleShortcut);
    return () => document.removeEventListener("keydown", handleShortcut);
  }, []);

  useEffect(() => {
    if (!open) return;
    const frame = requestAnimationFrame(() => textareaRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [open]);

  const cleanPrompt = project
    ? prompt.replace(`@${project.name}`, "").replace(/^\s*[-—:]?\s*/, "").trim()
    : prompt.trim();

  const createTask = useMutation({
    mutationFn: () => {
      if (!project) throw new Error("Tag one project before sending this task.");
      if (!cleanPrompt) throw new Error("Describe what the agent should do.");
      const firstLine = cleanPrompt.split("\n").find((line) => line.trim())?.trim() ?? cleanPrompt;
      const title = firstLine.length > 96 ? `${firstLine.slice(0, 95).trimEnd()}…` : firstLine;
      return api.createTask(project.id, {
        title,
        initial_prompt: cleanPrompt,
      });
    },
    onSuccess: async (task) => {
      if (project) {
        await queryClient.invalidateQueries({ queryKey: ["tasks", project.id] });
      }
      toast("Task created and dispatched", "success");
      reset();
      router.push(`/tasks/${task.id}`);
    },
    onError: (cause: Error) => setError(cause.message),
  });

  const reset = () => {
    setOpen(false);
    setPrompt("");
    setProject(null);
    setMentionQuery(null);
    setActiveIndex(0);
    setError("");
  };

  const selectProject = (selection: Project) => {
    const promptWithoutPreviousProject = project
      ? prompt.replace(`@${project.name}`, "").trimStart()
      : prompt;
    const match = promptWithoutPreviousProject.match(MENTION_PATTERN);
    const insertion = `@${selection.name} `;
    setPrompt(
      match
        ? `${promptWithoutPreviousProject.slice(0, match.index)}${match[0].startsWith(" ") ? " " : ""}${insertion}`
        : `${insertion}${promptWithoutPreviousProject}`,
    );
    setProject(selection);
    setMentionQuery(null);
    setActiveIndex(0);
    setError("");
    requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const changePrompt = (value: string) => {
    setPrompt(value);
    setError("");
    const match = value.match(MENTION_PATTERN);
    setMentionQuery(match?.[1] ?? null);
    setActiveIndex(0);
    if (project && !value.includes(`@${project.name}`)) setProject(null);
  };

  const submit = () => {
    setError("");
    createTask.mutate();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.nativeEvent.isComposing) return;
    if (mentionQuery !== null && suggestions.length > 0) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        setActiveIndex((current) =>
          event.key === "ArrowDown"
            ? (current + 1) % suggestions.length
            : (current - 1 + suggestions.length) % suggestions.length,
        );
        return;
      }
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        selectProject(suggestions[activeIndex] ?? suggestions[0]);
        return;
      }
    }
    if (event.key === "Escape") {
      event.preventDefault();
      if (mentionQuery !== null) setMentionQuery(null);
      else reset();
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!createTask.isPending) submit();
    }
  };

  return (
    <div className="fixed bottom-4 right-4 z-[35] sm:bottom-5 sm:right-5">
      <AnimatePresence mode="wait" initial={false}>
        {!open ? (
          <motion.button
            key="launcher"
            type="button"
            initial={{ opacity: 0, y: 10, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.96 }}
            whileHover={{ y: -2 }}
            whileTap={{ scale: 0.98 }}
            transition={{ type: "spring", stiffness: 430, damping: 32 }}
            onClick={() => setOpen(true)}
            className={cn("group flex h-12 items-center gap-3 rounded-2xl border border-signal-400/20 bg-ink-850/95 text-sm font-medium text-white shadow-[0_20px_60px_rgba(0,0,0,0.42)] backdrop-blur-xl", compact ? "w-12 justify-center px-0" : "px-4")}
            aria-label="Create a task from anywhere"
          >
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-signal-400 text-ink-950 shadow-[0_0_20px_rgba(66,232,196,0.2)]">
              <Sparkles className="h-3.5 w-3.5" />
            </span>
            {!compact && <><span>New task</span><kbd className="hidden rounded-md border border-white/10 bg-white/[0.04] px-1.5 py-0.5 font-mono text-[0.58rem] text-slate-500 group-hover:text-slate-300 sm:block">⌘ J</kbd></>}
          </motion.button>
        ) : (
          <motion.section
            key="composer"
            initial={{ opacity: 0, y: 18, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.97 }}
            transition={{ type: "spring", stiffness: 410, damping: 34 }}
            className="surface w-[min(29rem,calc(100vw-2rem))] overflow-hidden rounded-2xl shadow-[0_30px_90px_rgba(0,0,0,0.52)]"
            aria-label="Global task composer"
          >
            <div className="flex items-center justify-between border-b border-white/[0.07] px-4 py-3">
              <div className="flex items-center gap-2.5">
                <span className="grid h-7 w-7 place-items-center rounded-lg border border-signal-400/15 bg-signal-400/[0.07] text-signal-400">
                  <Command className="h-3.5 w-3.5" />
                </span>
                <div>
                  <h2 className="text-sm font-medium text-white">Dispatch a task</h2>
                  <p className="text-[0.62rem] text-slate-600">One project · its default runtime and model</p>
                </div>
              </div>
              <Button size="icon" variant="ghost" onClick={reset} aria-label="Close task composer">
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>

            <div className="relative p-3">
              {project && (
                <div className="mb-2 flex items-center justify-between rounded-xl border border-signal-400/15 bg-signal-400/[0.045] px-3 py-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-signal-400/10 text-[0.58rem] font-semibold text-signal-300">
                      {initials(project.name)}
                    </span>
                    <span className="truncate text-xs text-signal-200">@{project.name}</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setPrompt((current) => current.replace(`@${project.name}`, "").trimStart());
                      setProject(null);
                      requestAnimationFrame(() => textareaRef.current?.focus());
                    }}
                    className="rounded-md p-1 text-slate-600 transition hover:bg-white/[0.06] hover:text-white"
                    aria-label={`Remove ${project.name} from task`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              )}
              <textarea
                ref={textareaRef}
                value={prompt}
                onChange={(event) => changePrompt(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Describe the task and type @ to choose a project…"
                className="min-h-28 w-full resize-none bg-transparent px-1 py-1 text-sm leading-6 text-slate-200 outline-none placeholder:text-slate-700"
                aria-label="Task instructions"
                role="combobox"
                aria-haspopup="listbox"
                aria-autocomplete="list"
                aria-controls={mentionQuery !== null ? "project-mention-list" : undefined}
                aria-activedescendant={
                  mentionQuery !== null && suggestions[activeIndex]
                    ? `project-mention-${suggestions[activeIndex].id}`
                    : undefined
                }
                aria-expanded={mentionQuery !== null}
                disabled={createTask.isPending}
              />

              <AnimatePresence>
                {mentionQuery !== null && (
                  <motion.div
                    id="project-mention-list"
                    role="listbox"
                    aria-label="Projects"
                    initial={{ opacity: 0, y: 6, scale: 0.98 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: 4, scale: 0.98 }}
                    transition={{ duration: 0.14 }}
                    className="absolute inset-x-3 bottom-3 z-10 max-h-52 overflow-y-auto rounded-xl border border-white/10 bg-ink-850/98 p-1.5 shadow-panel backdrop-blur-xl"
                  >
                    {projects.isPending && <p className="px-3 py-4 text-center text-xs text-slate-600">Loading projects…</p>}
                    {projects.isError && <p className="px-3 py-4 text-center text-xs text-red-300">Could not load projects</p>}
                    {projects.isSuccess && suggestions.map((item, index) => (
                      <button
                        key={item.id}
                        id={`project-mention-${item.id}`}
                        type="button"
                        role="option"
                        aria-selected={project?.id === item.id}
                        onMouseEnter={() => setActiveIndex(index)}
                        onClick={() => selectProject(item)}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition",
                          activeIndex === index ? "bg-white/[0.065] text-white" : "text-slate-400",
                        )}
                      >
                        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-white/[0.08] bg-white/[0.03] text-[0.58rem] font-semibold">
                          {initials(item.name)}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-xs font-medium">{item.name}</span>
                          <span className="mt-0.5 block truncate text-[0.6rem] text-slate-600">{item.description || "Project workspace"}</span>
                        </span>
                        {project?.id === item.id && <Check className="h-3.5 w-3.5 text-signal-400" />}
                      </button>
                    ))}
                    {projects.isSuccess && suggestions.length === 0 && (
                      <div className="px-3 py-5 text-center">
                        <FolderKanban className="mx-auto h-4 w-4 text-slate-700" />
                        <p className="mt-2 text-xs text-slate-500">No matching project</p>
                      </div>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {error && (
              <p role="alert" className="mx-3 mb-2 rounded-lg border border-red-400/15 bg-red-400/[0.05] px-3 py-2 text-xs text-red-300">
                {error}
              </p>
            )}
            <div className="flex items-center justify-between border-t border-white/[0.07] px-3 py-2.5">
              <div className="flex items-center gap-3 text-[0.6rem] text-slate-700">
                <span className="flex items-center gap-1"><AtSign className="h-3 w-3" /> choose project</span>
                <span className="hidden items-center gap-1 sm:flex"><CornerDownLeft className="h-3 w-3" /> shift + enter for line</span>
              </div>
              <button
                type="button"
                onClick={submit}
                disabled={createTask.isPending || !project || !cleanPrompt}
                className="grid h-8 w-8 place-items-center rounded-lg bg-signal-400 text-ink-950 transition hover:bg-signal-300 disabled:cursor-not-allowed disabled:bg-white/[0.05] disabled:text-slate-700"
                aria-label="Create and dispatch task"
              >
                {createTask.isPending ? <ChevronDown className="h-3.5 w-3.5 animate-bounce" /> : <ArrowUp className="h-3.5 w-3.5" />}
              </button>
            </div>
          </motion.section>
        )}
      </AnimatePresence>
    </div>
  );
}
