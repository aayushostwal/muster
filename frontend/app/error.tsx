"use client";

import { useEffect } from "react";

import { ErrorState } from "@/components/ui/states";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <div className="mx-auto max-w-3xl p-6 md:p-10">
      <ErrorState message={error.message || "An unexpected interface error occurred."} retry={reset} />
    </div>
  );
}
