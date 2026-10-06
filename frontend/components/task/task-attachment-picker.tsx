"use client";

import { FileText, Image as ImageIcon, Paperclip, X } from "lucide-react";
import { useRef, type ChangeEvent } from "react";

import { cn } from "@/lib/utils";

export const MAX_TASK_ATTACHMENTS = 10;
export const MAX_TASK_ATTACHMENT_BYTES = 25 * 1024 * 1024;

export function TaskAttachmentPicker({
  files,
  onChange,
  disabled = false,
  compact = false,
  onError,
}: {
  files: File[];
  onChange: (files: File[]) => void;
  disabled?: boolean;
  compact?: boolean;
  onError?: (message: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const select = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(event.target.files ?? []);
    event.target.value = "";
    const oversized = selected.find((file) => file.size > MAX_TASK_ATTACHMENT_BYTES);
    if (oversized) return onError?.(`${oversized.name} is larger than 25 MB.`);
    const unique = [...files];
    for (const file of selected) {
      if (!unique.some((item) => item.name === file.name && item.size === file.size)) unique.push(file);
    }
    if (unique.length > MAX_TASK_ATTACHMENTS) return onError?.("Attach up to 10 files per task.");
    onError?.("");
    onChange(unique);
  };
  return (
    <div className={cn("space-y-2", compact && "px-1")}>
      <input ref={inputRef} type="file" multiple className="sr-only" onChange={select} disabled={disabled} aria-label="Choose task attachments" />
      {files.length > 0 && (
        <div className="flex max-h-28 flex-wrap gap-1.5 overflow-y-auto">
          {files.map((file, index) => (
            <span key={`${file.name}-${file.size}-${index}`} className="flex max-w-full items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.025] px-2 py-1.5 text-[0.65rem] text-slate-400">
              {file.type.startsWith("image/") ? <ImageIcon className="h-3 w-3 shrink-0 text-pulse-400" /> : <FileText className="h-3 w-3 shrink-0 text-slate-600" />}
              <span className="max-w-40 truncate">{file.name}</span>
              <span className="text-slate-700">{formatBytes(file.size)}</span>
              <button type="button" onClick={() => onChange(files.filter((_, itemIndex) => itemIndex !== index))} disabled={disabled} className="rounded p-0.5 text-slate-700 hover:bg-white/[0.06] hover:text-white" aria-label={`Remove ${file.name}`}><X className="h-3 w-3" /></button>
            </span>
          ))}
        </div>
      )}
      <button type="button" onClick={() => inputRef.current?.click()} disabled={disabled || files.length >= MAX_TASK_ATTACHMENTS} className="flex items-center gap-1.5 text-[0.68rem] text-slate-500 transition hover:text-signal-300 disabled:cursor-not-allowed disabled:opacity-40">
        <Paperclip className="h-3.5 w-3.5" /> Attach images or files{files.length ? ` (${files.length}/${MAX_TASK_ATTACHMENTS})` : ""}
      </button>
    </div>
  );
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.ceil(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
