import type { ReactNode } from "react";

export function Tooltip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="group/tooltip relative inline-flex">
      {children}
      <span role="tooltip" className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 -translate-x-1/2 whitespace-nowrap rounded-lg border border-white/10 bg-ink-800 px-2.5 py-1.5 text-[0.68rem] font-medium text-slate-200 opacity-0 shadow-panel transition group-hover/tooltip:opacity-100 group-focus-within/tooltip:opacity-100">
        {label}
      </span>
    </span>
  );
}
