import { Skeleton } from "@/components/ui/states";

export default function Loading() {
  return (
    <div className="mx-auto max-w-screen-2xl space-y-6 p-5 md:p-8">
      <Skeleton className="h-28" />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-56" />
        ))}
      </div>
    </div>
  );
}
