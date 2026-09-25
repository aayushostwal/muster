import { afterEach, describe, expect, it, vi } from "vitest";

import { backendLabel, cn, formatDateTime, formatRelativeTime, initials, shortId } from "./utils";

describe("frontend formatting utilities", () => {
  afterEach(() => vi.useRealTimers());

  it("merges conditional Tailwind classes", () => {
    expect(cn("px-2", false && "hidden", "px-4")).toBe("px-4");
  });

  it.each([
    [null, "Never"],
    ["2025-01-02T11:59:40Z", "Just now"],
    ["2025-01-02T11:45:00Z", "15m ago"],
    ["2025-01-02T09:00:00Z", "3h ago"],
    ["2024-12-30T12:00:00Z", "3d ago"],
  ])("formats relative time %s", (value, expected) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2025-01-02T12:00:00Z"));
    expect(formatRelativeTime(value)).toBe(expected);
  });

  it("uses a calendar date for older timestamps", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2025-01-20T12:00:00Z"));
    expect(formatRelativeTime("2025-01-01T12:00:00Z")).toMatch(/Jan 1/);
  });

  it("formats absolute timestamps and null values", () => {
    expect(formatDateTime(null)).toBe("Not available");
    expect(formatDateTime("2025-01-02T12:00:00Z")).toMatch(/Jan 2/);
  });

  it("labels backends and compact identifiers", () => {
    expect(backendLabel("claude_code")).toBe("Claude Code");
    expect(backendLabel("codex")).toBe("Codex");
    expect(initials("  ada   lovelace byron ")).toBe("AL");
    expect(initials(" ")).toBe("");
    expect(shortId("1234567890")).toBe("12345678");
  });
});
