import { notFound } from "next/navigation";

import { RegistryManager } from "@/components/registry/registry-manager";

const kinds = ["agents", "skills", "tools", "mcp", "directories"] as const;

export default async function RegistryPage({ params }: { params: Promise<{ kind: string }> }) {
  const { kind } = await params;
  if (!kinds.includes(kind as (typeof kinds)[number])) notFound();
  return <RegistryManager kind={kind as (typeof kinds)[number]} />;
}
