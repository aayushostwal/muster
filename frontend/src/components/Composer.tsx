import { useRef, useState } from "react";
import type { MediaAttachment } from "../types";

interface ComposerProps {
  onSend: (payload: { content_text?: string; media?: MediaAttachment[] }) => void;
  disabled?: boolean;
}

/**
 * Text + file composer. Since SPEC.md defines no separate media-upload
 * endpoint, selected files are attached as lightweight metadata
 * (name/content_type) alongside the message; the backend is expected to
 * treat `media` on POST /api/tasks/{id}/messages as the attachment payload.
 */
export default function Composer({ onSend, disabled }: ComposerProps) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim() && files.length === 0) return;

    const media: MediaAttachment[] | undefined =
      files.length > 0
        ? files.map((f) => ({ name: f.name, content_type: f.type || "application/octet-stream" }))
        : undefined;

    onSend({ content_text: text.trim() || undefined, media });
    setText("");
    setFiles([]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <textarea
        placeholder="Message the agent…"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSubmit(e);
          }
        }}
        disabled={disabled}
      />
      <input
        ref={fileInputRef}
        type="file"
        multiple
        onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
        style={{ maxWidth: 160 }}
        disabled={disabled}
      />
      <button className="primary" type="submit" disabled={disabled}>
        Send
      </button>
    </form>
  );
}
