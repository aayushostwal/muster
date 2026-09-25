import { describe, expect, it, vi } from "vitest";

import { changedLineIndexes, extractMagicArtifact, storedMagicCanvasContext } from "./magic-canvas";
import { collectTagSuggestions, normalizeTaskTags, TASK_TAG_MAX_COUNT, TASK_TAG_MAX_LENGTH } from "./task-tags";
import { taskNeedsAttention, taskStage } from "./task-status";

describe("task lifecycle helpers", () => {
  it("maps review attention to its display stage", () => {
    expect(taskStage({ status: "waiting_on_you", attention_reason: "awaiting_review" })).toBe("ready_for_review");
    expect(taskStage({ status: "waiting_on_you", attention_reason: "tool_permission" })).toBe("waiting_on_you");
    expect(taskNeedsAttention({ status: "waiting_on_you", attention_reason: null })).toBe(true);
    expect(taskNeedsAttention({ status: "failed", attention_reason: null })).toBe(true);
    expect(taskNeedsAttention({ status: "done", attention_reason: null })).toBe(false);
  });
});

describe("task tags", () => {
  it("normalizes whitespace and case-insensitive duplicates", () => {
    expect(normalizeTaskTags([" Bug ", "bug", "needs   review", ""])).toEqual({
      tags: ["Bug", "needs review"],
      error: null,
    });
  });

  it("rejects long tags and limits tag count", () => {
    expect(normalizeTaskTags(["x".repeat(TASK_TAG_MAX_LENGTH + 1)])).toMatchObject({ error: expect.stringContaining("32") });
    const result = normalizeTaskTags(Array.from({ length: TASK_TAG_MAX_COUNT + 2 }, (_, index) => `tag-${index}`));
    expect(result.tags).toHaveLength(TASK_TAG_MAX_COUNT);
    expect(result.error).toContain("8");
  });

  it("combines curated and observed tag suggestions in sorted order", () => {
    const suggestions = collectTagSuggestions([{ tags: ["Zebra", "Bug"] }, { tags: ["Alpha"] }]);
    expect(suggestions.find((item) => item.value === "Bug")).toEqual({ value: "Bug", label: "Bug" });
    expect(suggestions.map((item) => item.value)).toEqual([...suggestions.map((item) => item.value)].sort());
  });
});

describe("magic canvas extraction", () => {
  it("ignores user, empty, and undersized artifacts", () => {
    expect(extractMagicArtifact({ sender: "user", content_text: "```ts\n" + "x".repeat(60) + "\n```" })).toBeNull();
    expect(extractMagicArtifact({ sender: "agent", content_text: null })).toBeNull();
    expect(extractMagicArtifact({ sender: "agent", content_text: "```ts\nshort\n```" })).toBeNull();
    expect(extractMagicArtifact({ sender: "agent", content_text: "ordinary reply" })).toBeNull();
  });

  it("prefers Mermaid and derives titles from headings or prose", () => {
    const result = extractMagicArtifact({
      sender: "agent",
      content_text: "# **System**\n```ts\n" + "const value = 1;\n".repeat(5) + "```\n```mermaid\ngraph TD\n" + "A --> B\n".repeat(6) + "```",
    });
    expect(result).toMatchObject({ format: "diagram", language: "mermaid", title: "System" });

    const code = extractMagicArtifact({ sender: "agent", content_text: "Useful generated snippet\n```\n" + "plain output\n".repeat(6) + "```" });
    expect(code).toMatchObject({ format: "code", language: null, title: "Useful generated snippet" });
    const fallback = extractMagicArtifact({ sender: "agent", content_text: "```ts\n" + "const x = 1;\n".repeat(5) + "```" });
    expect(fallback?.title).toBe("Code artifact");
  });

  it("extracts long markdown documents and reports changed lines", () => {
    const document = "- first item\n" + "A useful document paragraph. ".repeat(20);
    expect(extractMagicArtifact({ sender: "agent", content_text: document })).toMatchObject({ format: "markdown", language: "markdown" });
    expect([...changedLineIndexes("a\nb", "a\nc\nd")]).toEqual([1, 2]);
  });

  it("loads valid stored context and rejects malformed storage", () => {
    const values = new Map<string, string>();
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
      },
    });
    window.localStorage.setItem("muster:magic-canvas:one", JSON.stringify([{ content: "x", title: "T", format: "code", language: 3 }]));
    expect(storedMagicCanvasContext("one")).toEqual({ kind: "magic_canvas", content: "x", title: "T", format: "code", language: null });
    window.localStorage.setItem("muster:magic-canvas:bad", "{");
    expect(storedMagicCanvasContext("bad")).toBeNull();
    window.localStorage.setItem("muster:magic-canvas:shape", JSON.stringify([{ content: 4, title: "T", format: "code" }]));
    expect(storedMagicCanvasContext("shape")).toBeNull();
    window.localStorage.setItem("muster:magic-canvas:format", JSON.stringify([{ content: "x", title: "T", format: "pdf" }]));
    expect(storedMagicCanvasContext("format")).toBeNull();
    expect(storedMagicCanvasContext("missing")).toBeNull();
    vi.stubGlobal("window", undefined);
    expect(storedMagicCanvasContext("server")).toBeNull();
  });
});
