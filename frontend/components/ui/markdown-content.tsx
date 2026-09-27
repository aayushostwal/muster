"use client";

import { Check, Copy } from "lucide-react";
import { Children, isValidElement, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

export function MarkdownContent({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn("min-w-0 break-words text-sm leading-6 text-slate-300", className)}>
      <ReactMarkdown
        skipHtml
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 className="mb-3 mt-5 text-xl font-semibold tracking-tight text-white first:mt-0">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-2.5 mt-5 text-lg font-semibold tracking-tight text-white first:mt-0">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-2 mt-4 text-base font-semibold text-slate-100 first:mt-0">{children}</h3>,
          h4: ({ children }) => <h4 className="mb-2 mt-4 text-sm font-semibold text-slate-100 first:mt-0">{children}</h4>,
          p: ({ children }) => <p className="my-2.5 first:mt-0 last:mb-0">{children}</p>,
          strong: ({ children }) => <strong className="font-semibold text-slate-100">{children}</strong>,
          em: ({ children }) => <em className="text-slate-200">{children}</em>,
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer noopener"
              className="text-signal-300 underline decoration-signal-400/35 underline-offset-4 transition hover:text-signal-200 hover:decoration-signal-300"
            >
              {children}
            </a>
          ),
          ul: ({ children }) => <ul className="my-3 list-disc space-y-1.5 pl-5 marker:text-slate-600">{children}</ul>,
          ol: ({ children }) => <ol className="my-3 list-decimal space-y-1.5 pl-5 marker:font-mono marker:text-slate-600">{children}</ol>,
          li: ({ children }) => <li className="pl-1">{children}</li>,
          blockquote: ({ children }) => <blockquote className="my-3 border-l-2 border-pulse-400/45 bg-pulse-400/[0.035] py-1 pl-4 text-slate-400">{children}</blockquote>,
          hr: () => <hr className="my-5 border-white/[0.08]" />,
          code: ({ className: codeClassName, children }) => (
            <code className={cn("rounded bg-white/[0.07] px-1.5 py-0.5 font-mono text-[0.82em] text-signal-200", codeClassName)}>
              {children}
            </code>
          ),
          pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
          table: ({ children }) => (
            <div className="my-4 overflow-x-auto rounded-xl border border-white/[0.08]">
              <table className="w-full min-w-[30rem] border-collapse text-left text-xs">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-white/[0.045] text-slate-200">{children}</thead>,
          th: ({ children }) => <th className="border-b border-white/[0.08] px-3 py-2.5 font-medium">{children}</th>,
          td: ({ children }) => <td className="border-b border-white/[0.05] px-3 py-2.5 align-top text-slate-400 last:border-b-0">{children}</td>,
          input: ({ checked, ...props }) => (
            <input
              {...props}
              checked={checked}
              disabled
              className="mr-2 h-3.5 w-3.5 rounded border-white/15 accent-signal-400"
            />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function CodeBlock({ children }: { children: ReactNode }) {
  const [copied, setCopied] = useState(false);
  const code = textContent(children).replace(/\n$/, "");
  const language = detectLanguage(children);

  const copy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  };

  return (
    <div className="group/code relative my-4 overflow-hidden rounded-xl border border-white/[0.08] bg-[#05070b]">
      <div className="flex h-8 items-center justify-between border-b border-white/[0.06] px-3">
        <span className="font-mono text-[0.58rem] uppercase tracking-wider text-slate-700">{language || "code"}</span>
        <button
          type="button"
          onClick={copy}
          className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[0.6rem] text-slate-600 transition hover:bg-white/[0.05] hover:text-slate-300"
          aria-label="Copy code block"
        >
          {copied ? <Check className="h-3 w-3 text-signal-400" /> : <Copy className="h-3 w-3" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="max-h-[32rem] overflow-auto p-3.5 font-mono text-xs leading-5 text-slate-300 [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-inherit">
        {children}
      </pre>
    </div>
  );
}

function textContent(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textContent).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return textContent(node.props.children);
  return "";
}

function detectLanguage(node: ReactNode): string | null {
  const child = Children.toArray(node).find(isValidElement);
  if (!isValidElement<{ className?: string }>(child)) return null;
  return child.props.className?.match(/language-([^\s]+)/)?.[1] ?? null;
}
