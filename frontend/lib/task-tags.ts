export const TASK_TAG_OPTIONS = [
  { value: "PR Raised", label: "PR Raised" },
  { value: "PR Reviewed", label: "PR Reviewed" },
  { value: "Canvas", label: "Canvas" },
  { value: "Bug", label: "Bug" },
  { value: "Feature", label: "Feature" },
  { value: "Research", label: "Research" },
  { value: "Release", label: "Release" },
] as const;

export const TASK_TAG_COLORS: Record<string, string> = {
  "PR Raised": "border-pulse-400/20 bg-pulse-400/[0.08] text-pulse-400",
  "PR Reviewed": "border-emerald-400/20 bg-emerald-400/[0.08] text-emerald-300",
  Canvas: "border-sky-400/20 bg-sky-400/[0.08] text-sky-300",
  Bug: "border-red-400/20 bg-red-400/[0.08] text-red-300",
  Feature: "border-signal-400/20 bg-signal-400/[0.08] text-signal-300",
  Research: "border-amber-400/20 bg-amber-400/[0.08] text-amber-300",
  Release: "border-fuchsia-400/20 bg-fuchsia-400/[0.08] text-fuchsia-300",
};
