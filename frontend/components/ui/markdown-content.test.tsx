import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MarkdownContent } from "./markdown-content";

describe("MarkdownContent", () => {
  it("renders Markdown while dropping raw HTML", () => {
    const { container } = render(
      <MarkdownContent content={'# Safe prompt\n\n<script>alert("x")</script>\n\n**Follow instructions.**'} />,
    );

    expect(screen.getByRole("heading", { name: "Safe prompt" })).toBeInTheDocument();
    expect(screen.getByText("Follow instructions.")).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).not.toContain("alert");
  });
});
