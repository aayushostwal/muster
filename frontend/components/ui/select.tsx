"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Check, ChevronDown, X } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/utils";

export interface SelectOption {
  value: string;
  label: string;
  description?: string;
}

interface BaseProps {
  options: SelectOption[];
  label: string;
  disabled?: boolean;
  className?: string;
}

function useFloating(open: boolean) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const update = useCallback(() => {
    if (triggerRef.current) setRect(triggerRef.current.getBoundingClientRect());
  }, []);
  useEffect(() => {
    if (!open) return;
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open, update]);
  return { triggerRef, rect };
}

export function Select({ options, value, onChange, label, disabled, className }: BaseProps & { value: string; onChange: (value: string) => void }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const id = useId();
  const { triggerRef, rect } = useFloating(open);
  const selected = options.find((option) => option.value === value);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!triggerRef.current?.contains(event.target as Node) && !(event.target as Element).closest?.(`[data-select-menu="${id}"]`)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", escape); };
  }, [id, open, triggerRef]);

  return (
    <>
      <button ref={triggerRef} type="button" className={cn("field flex min-h-11 items-center justify-between gap-3 text-left", !selected && "text-slate-600", className)} onClick={() => !disabled && setOpen((current) => !current)} onKeyDown={(event) => {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); setOpen(true); setActive((current) => event.key === "ArrowDown" ? Math.min(current + 1, options.length - 1) : Math.max(current - 1, 0)); }
        if (event.key === "Enter" && open) { event.preventDefault(); const option = options[active]; if (option) { onChange(option.value); setOpen(false); } }
      }} aria-haspopup="listbox" aria-expanded={open} aria-label={label} disabled={disabled}>
        <span className="truncate">{selected?.label ?? label}</span><ChevronDown className={cn("h-4 w-4 shrink-0 text-slate-600 transition-transform", open && "rotate-180")} />
      </button>
      <SelectMenu open={open} rect={rect} id={id}>
        <div role="listbox" aria-label={label} className="p-1.5">
          {options.map((option, index) => <button key={option.value} type="button" role="option" aria-selected={option.value === value} onMouseEnter={() => setActive(index)} onClick={() => { onChange(option.value); setOpen(false); }} className={cn("flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition", active === index && "bg-white/[0.06]", option.value === value ? "text-white" : "text-slate-400")}><span className="min-w-0 flex-1"><span className="block truncate text-sm">{option.label}</span>{option.description && <span className="mt-0.5 block truncate text-[0.62rem] text-slate-600">{option.description}</span>}</span>{option.value === value && <Check className="h-4 w-4 text-signal-400" />}</button>)}
          {options.length === 0 && <p className="px-3 py-4 text-center text-xs text-slate-600">No options available</p>}
        </div>
      </SelectMenu>
    </>
  );
}

export function MultiSelect({ options, values, onChange, label, disabled, className }: BaseProps & { values: string[]; onChange: (values: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const { triggerRef, rect } = useFloating(open);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!triggerRef.current?.contains(event.target as Node) && !(event.target as Element).closest?.(`[data-select-menu="${id}"]`)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", escape); };
  }, [id, open, triggerRef]);
  const toggle = (value: string) => onChange(values.includes(value) ? values.filter((item) => item !== value) : [...values, value]);
  return <>
    <button ref={triggerRef} type="button" className={cn("field flex min-h-11 items-center justify-between gap-3 text-left", className)} onClick={() => !disabled && setOpen((current) => !current)} aria-haspopup="listbox" aria-expanded={open} aria-label={label} disabled={disabled}><span className={cn("flex min-w-0 flex-1 flex-wrap gap-1.5", values.length === 0 && "text-slate-600")}>{values.length === 0 ? label : values.slice(0, 3).map((value) => <span key={value} className="inline-flex items-center gap-1 rounded-md border border-signal-400/15 bg-signal-400/[0.06] px-2 py-0.5 text-[0.66rem] text-signal-300">{options.find((option) => option.value === value)?.label ?? value}<X className="h-2.5 w-2.5" /></span>)}{values.length > 3 && <span className="text-xs text-slate-500">+{values.length - 3}</span>}</span><ChevronDown className={cn("h-4 w-4 shrink-0 text-slate-600 transition-transform", open && "rotate-180")} /></button>
    <SelectMenu open={open} rect={rect} id={id}><div role="listbox" aria-multiselectable="true" aria-label={label} className="p-1.5">{options.map((option) => { const selected = values.includes(option.value); return <button key={option.value} type="button" role="option" aria-selected={selected} onClick={() => toggle(option.value)} className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-slate-400 transition hover:bg-white/[0.06] hover:text-white"><span className={cn("grid h-4 w-4 place-items-center rounded border", selected ? "border-signal-400 bg-signal-400 text-ink-950" : "border-white/15")} >{selected && <Check className="h-3 w-3" />}</span><span className="min-w-0 flex-1"><span className="block truncate text-sm">{option.label}</span>{option.description && <span className="mt-0.5 block truncate text-[0.62rem] text-slate-600">{option.description}</span>}</span></button>; })}{options.length === 0 && <p className="px-3 py-4 text-center text-xs text-slate-600">No options available</p>}</div></SelectMenu>
  </>;
}

function SelectMenu({ open, rect, id, children }: { open: boolean; rect: DOMRect | null; id: string; children: ReactNode }) {
  if (typeof document === "undefined" || !rect) return null;
  const spaceBelow = window.innerHeight - rect.bottom - 12;
  const spaceAbove = rect.top - 12;
  const openAbove = spaceBelow < 220 && spaceAbove > spaceBelow;
  const availableHeight = Math.max(120, Math.min(256, openAbove ? spaceAbove : spaceBelow));
  const left = Math.max(12, Math.min(rect.left, window.innerWidth - rect.width - 12));
  return createPortal(<AnimatePresence>{open && <motion.div data-select-menu={id} initial={{ opacity: 0, y: openAbove ? 6 : -6, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: openAbove ? 4 : -4, scale: 0.98 }} transition={{ duration: 0.16 }} style={{ position: "fixed", left, top: openAbove ? undefined : rect.bottom + 6, bottom: openAbove ? window.innerHeight - rect.top + 6 : undefined, width: rect.width, maxHeight: availableHeight }} className="z-[80] overflow-y-auto rounded-xl border border-white/10 bg-ink-850/95 shadow-panel backdrop-blur-xl">{children}</motion.div>}</AnimatePresence>, document.body);
}
