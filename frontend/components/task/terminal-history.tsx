"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

export function TerminalHistory({ taskId }: { taskId: string }) {
  const history = useInfiniteQuery({
    queryKey: ["terminal-history", taskId],
    initialPageParam: "0:0",
    queryFn: ({ pageParam }) => api.terminalHistory(taskId, pageParam),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    retry: false,
  });
  const items = history.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div className="h-full overflow-y-auto overscroll-contain p-4" aria-label="Session history" tabIndex={0}>
      <p className="mb-4 text-xs text-slate-500">Prompts, replies and tool activity from the beginning of this task. Scroll to review earlier work.</p>
      {history.isPending && <p className="text-sm text-slate-400">Loading session history…</p>}
      {!history.isPending && !history.isError && !items.length && !history.hasNextPage && <p className="text-sm text-slate-400">No saved native conversation is available for this task. You can still view the terminal output.</p>}
      <div className="space-y-4">
        {items.map((item, index) => (
          <article key={index} className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
            <div className="mb-2 flex gap-3 text-xs text-slate-400">
              <span className={item.role === "user" ? "text-signal-400" : "text-slate-300"}>{({ user: "You", assistant: "Agent", tool: "Tool call", tool_result: "Tool result" })[item.role]}</span>
              {item.timestamp && <time>{item.timestamp}</time>}
            </div>
            <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-6 text-slate-300">{item.text}</pre>
            {item.truncated && <p className="mt-2 text-xs text-amber-300">This entry exceeds the display limit; showing its first 64K characters.</p>}
          </article>
        ))}
      </div>
      {history.isError && <div className="mt-4 text-sm text-red-300">{history.error.message}<Button className="ml-3" size="sm" onClick={() => history.refetch()}>Retry</Button></div>}
      {history.hasNextPage && <Button className="mt-4" loading={history.isFetchingNextPage} onClick={() => history.fetchNextPage()}>Load more history</Button>}
    </div>
  );
}
