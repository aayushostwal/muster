"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Bot, Slash, Wand2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type { SlashCommandItem } from "@/hooks/use-slash-commands";

/**
 * `/`-triggered dropdown listing agents and skills, matching the `@project`
 * mention list already used by the task composers.
 */
export function SlashCommandMenu({
  open,
  loading,
  error,
  items,
  activeIndex,
  onHover,
  onSelect,
  className,
}: {
  open: boolean;
  loading: boolean;
  error: boolean;
  items: SlashCommandItem[];
  activeIndex: number;
  onHover: (index: number) => void;
  onSelect: (item: SlashCommandItem) => void;
  className?: string;
}) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          id="slash-command-list"
          role="listbox"
          aria-label="Agents and skills"
          initial={{ opacity: 0, y: 6, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 4, scale: 0.98 }}
          transition={{ duration: 0.14 }}
          className={cn(
            "z-10 max-h-52 overflow-y-auto rounded-xl border border-white/10 bg-ink-850/98 p-1.5 shadow-panel backdrop-blur-xl",
            className,
          )}
        >
          {loading && <p className="px-3 py-4 text-center text-xs text-slate-600">Loading agents and skills…</p>}
          {error && <p className="px-3 py-4 text-center text-xs text-red-300">Could not load agents and skills</p>}
          {!loading && !error && items.map((item, index) => (
            <button
              key={`${item.kind}-${item.id}`}
              id={`slash-command-${item.id}`}
              type="button"
              role="option"
              aria-selected={activeIndex === index}
              onMouseEnter={() => onHover(index)}
              onClick={() => onSelect(item)}
              className={cn(
                "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition",
                activeIndex === index ? "bg-white/[0.065] text-white" : "text-slate-400",
              )}
            >
              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-white/[0.08] bg-white/[0.03] text-slate-400">
                {item.kind === "agent" ? <Bot className="h-3.5 w-3.5" /> : <Wand2 className="h-3.5 w-3.5" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium">/{item.name}</span>
                <span className="mt-0.5 block truncate text-[0.6rem] text-slate-600">
                  {item.description || (item.kind === "agent" ? "Agent" : "Skill")}
                </span>
              </span>
            </button>
          ))}
          {!loading && !error && items.length === 0 && (
            <div className="px-3 py-5 text-center">
              <Slash className="mx-auto h-4 w-4 text-slate-700" />
              <p className="mt-2 text-xs text-slate-500">No matching agent or skill</p>
            </div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
