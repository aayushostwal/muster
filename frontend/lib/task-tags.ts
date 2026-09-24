export const TASK_TAG_OPTIONS = [
  { value: "PR Raised", label: "PR Raised" },
  { value: "PR Reviewed", label: "PR Reviewed" },
  { value: "Canvas", label: "Canvas" },
  { value: "Bug", label: "Bug" },
  { value: "Feature", label: "Feature" },
  { value: "Research", label: "Research" },
  { value: "Release", label: "Release" },
] as const;

export const SYSTEM_TASK_TAGS = new Set(["PR Raised", "PR Reviewed", "Canvas"]);

export const TASK_TAG_COLORS: Record<string, string> = {
  "PR Raised": "border-pulse-400/20 bg-pulse-400/[0.08] text-pulse-400",
  "PR Reviewed": "border-emerald-400/20 bg-emerald-400/[0.08] text-emerald-300",
  Canvas: "border-sky-400/20 bg-sky-400/[0.08] text-sky-300",
  Bug: "border-red-400/20 bg-red-400/[0.08] text-red-300",
  Feature: "border-signal-400/20 bg-signal-400/[0.08] text-signal-300",
  Research: "border-amber-400/20 bg-amber-400/[0.08] text-amber-300",
  Release: "border-fuchsia-400/20 bg-fuchsia-400/[0.08] text-fuchsia-300",
};

export const TASK_TAG_MAX_COUNT = 8;
export const TASK_TAG_MAX_LENGTH = 32;

/** Mirrors the backend's TaskTagsMixin.normalize_tags exactly: trims and
 * collapses whitespace, drops empties, and de-dupes case-insensitively while
 * keeping the first-seen casing. Rejecting long tags here (rather than
 * silently truncating) keeps client-side and server-side validation from
 * ever quietly disagreeing. */
export function normalizeTaskTags(values: string[]): { tags: string[]; error: string | null } {
  const normalized: string[] = [];
  for (const value of values) {
    const clean = value.trim().replace(/\s+/g, " ");
    if (!clean) continue;
    if (clean.length > TASK_TAG_MAX_LENGTH) {
      return { tags: normalized, error: `Tags must be ${TASK_TAG_MAX_LENGTH} characters or fewer.` };
    }
    if (!normalized.some((item) => item.toLowerCase() === clean.toLowerCase())) {
      normalized.push(clean);
    }
  }
  if (normalized.length > TASK_TAG_MAX_COUNT) {
    return { tags: normalized.slice(0, TASK_TAG_MAX_COUNT), error: `Up to ${TASK_TAG_MAX_COUNT} tags per task.` };
  }
  return { tags: normalized, error: null };
}

/** Unions the curated presets with every tag actually used across a set of
 * tasks (e.g. a project's task list), so filter/creation UIs surface real
 * project history instead of just the 7 canned labels. */
export function collectTagSuggestions(tasks: Array<{ tags: string[] }>): Array<{ value: string; label: string }> {
  const values = new Set<string>(TASK_TAG_OPTIONS.map((item) => item.value));
  for (const task of tasks) for (const tag of task.tags) values.add(tag);
  return [...values].sort((a, b) => a.localeCompare(b)).map((value) => ({ value, label: value }));
}
