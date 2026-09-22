import { CircleAlert, Inbox } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";

export function Skeleton({ className = "h-24" }: { className?: string }) {
  return <div className={`animate-pulse rounded-panel border border-white/[0.05] bg-white/[0.035] ${className}`} />;
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex min-h-64 flex-col items-center justify-center rounded-panel border border-dashed border-white/10 bg-white/[0.018] px-6 text-center">
      <div className="mb-4 rounded-2xl border border-white/10 bg-white/[0.04] p-3 text-slate-500">
        <Inbox className="h-5 w-5" />
      </div>
      <h3 className="font-medium text-white">{title}</h3>
      <p className="mt-2 max-w-sm text-sm leading-6 text-slate-500">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="flex min-h-64 flex-col items-center justify-center rounded-panel border border-red-400/15 bg-red-400/[0.035] px-6 text-center">
      <CircleAlert className="mb-4 h-6 w-6 text-red-400" />
      <h3 className="font-medium text-white">Unable to load this view</h3>
      <p className="mt-2 max-w-md text-sm text-slate-500">{message}</p>
      {retry && <Button className="mt-5" onClick={retry}>Try again</Button>}
    </div>
  );
}
