import { useEffect, useRef } from "react";
import type { Message } from "../types";

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

export default function ChatThread({ messages }: { messages: Message[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  return (
    <div className="chat-thread">
      {messages.map((message) => (
        <div key={message.id} className={`chat-bubble ${message.sender}`}>
          <div className="sender-label">
            {message.sender} · {formatTime(message.created_at)}
          </div>
          {message.content_text && <div>{message.content_text}</div>}
          {message.media?.map((attachment, i) => (
            <a
              key={i}
              className="media-attachment"
              href={attachment.url ?? "#"}
              target="_blank"
              rel="noreferrer"
            >
              📎 {attachment.name ?? attachment.url ?? "attachment"}
            </a>
          ))}
        </div>
      ))}
      {messages.length === 0 && <div className="muted">No messages yet.</div>}
      <div ref={bottomRef} />
    </div>
  );
}
