import type { Message } from "@/lib/types";

export type CanvasFormat = "code" | "markdown" | "diagram";

export interface CanvasArtifactCandidate {
  content: string;
  format: CanvasFormat;
  language: string | null;
  title: string;
}

export interface MagicCanvasContext extends CanvasArtifactCandidate {
  kind: "magic_canvas";
}

const FENCED_BLOCK = /```([\w+-]*)\s*\n([\s\S]*?)```/g;

export function extractMagicArtifact(message: Pick<Message, "content_text" | "sender">): CanvasArtifactCandidate | null {
  if (message.sender !== "agent" || !message.content_text) return null;
  const text = message.content_text.trim();
  const blocks = [...text.matchAll(FENCED_BLOCK)];
  const preferred = blocks.find((match) => match[1].toLowerCase() === "mermaid") ?? blocks.toSorted((a, b) => b[2].length - a[2].length)[0];

  if (preferred) {
    const language = preferred[1].toLowerCase() || null;
    const content = preferred[2].trim();
    if (content.length < 40) return null;
    return {
      content,
      format: language === "mermaid" ? "diagram" : "code",
      language,
      title: artifactTitle(text, language === "mermaid" ? "Diagram" : "Code artifact"),
    };
  }

  const looksLikeDocument = text.length >= 320 && (/^#{1,3}\s/m.test(text) || /^[-*]\s/m.test(text));
  if (!looksLikeDocument) return null;
  return {
    content: text,
    format: "markdown",
    language: "markdown",
    title: artifactTitle(text, "Document"),
  };
}

function artifactTitle(text: string, fallback: string) {
  const heading = text.match(/^#{1,3}\s+(.+)$/m)?.[1]?.replace(/[*_`]/g, "").trim();
  if (heading) return heading.slice(0, 72);
  const introduction = text
    .replace(FENCED_BLOCK, "")
    .split("\n")
    .map((line) => line.replace(/[*_`:#]/g, "").trim())
    .find((line) => line.length > 5);
  return introduction?.slice(0, 72) || fallback;
}

export function changedLineIndexes(previous: string, next: string): Set<number> {
  const before = previous.split("\n");
  const after = next.split("\n");
  return new Set(after.flatMap((line, index) => (line !== before[index] ? [index] : [])));
}

export function storedMagicCanvasContext(taskId: string): MagicCanvasContext | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(`muster:magic-canvas:${taskId}`);
    const latest = raw ? (JSON.parse(raw) as Array<Partial<CanvasArtifactCandidate>>).at(-1) : null;
    if (!latest || typeof latest.content !== "string" || typeof latest.title !== "string") return null;
    if (!latest.format || !["code", "markdown", "diagram"].includes(latest.format)) return null;
    return {
      kind: "magic_canvas",
      content: latest.content,
      format: latest.format,
      language: typeof latest.language === "string" ? latest.language : null,
      title: latest.title,
    };
  } catch {
    return null;
  }
}
