import type { ReactNode } from "react";

export function Tooltip({
  label,
  children,
  side = "top",
  align = "center",
}: {
  label: string;
  children: ReactNode;
  side?: "top" | "bottom";
  align?: "start" | "center" | "end";
}) {
  const alignment = align === "start" ? "left-0" : align === "end" ? "right-0" : "left-1/2 -translate-x-1/2";

  return (
    <span className="group/tooltip relative inline-flex">
      {children}
      <span
        role="tooltip"
        className={`pointer-events-none absolute z-50 whitespace-nowrap rounded-lg border border-white/10 bg-ink-800 px-2.5 py-1.5 text-[0.68rem] font-medium text-slate-200 opacity-0 shadow-panel transition group-hover/tooltip:opacity-100 group-focus-within/tooltip:opacity-100 ${alignment} ${side === "bottom" ? "top-full mt-2" : "bottom-full mb-2"}`}
      >
        {label}
      </span>
    </span>
  );
}
