"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { api } from "@/lib/api";

/** Matches a trailing `/query` token, mirroring the `@project` mention pattern. */
export const SLASH_PATTERN = /(?:^|\s)\/([^\s]*)$/;

export type SlashCommandKind = "action" | "agent" | "skill";

export interface SlashCommandItem {
  id: string;
  kind: SlashCommandKind;
  name: string;
  description: string | null;
}

/**
 * Resolves the enabled agents and skills that can be invoked from chat via `/name`,
 * filtered against the in-progress query typed after the slash.
 */
export function useSlashCommands(query: string | null) {
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.agents, enabled: query !== null });
  const skills = useQuery({ queryKey: ["skills"], queryFn: api.skills, enabled: query !== null });

  const items = useMemo<SlashCommandItem[]>(() => {
    const actionItems: SlashCommandItem[] = [
      {
        id: "action-pr",
        kind: "action",
        name: "pr",
        description: "Inspect task changes and prepare a pull request confirmation",
      },
    ];
    const agentItems = (agents.data?.items ?? [])
      .filter((agent) => agent.enabled)
      .map((agent) => ({ id: agent.id, kind: "agent" as const, name: agent.name, description: agent.description }));
    const skillItems = (skills.data?.items ?? [])
      .filter((skill) => skill.enabled)
      .map((skill) => ({ id: skill.id, kind: "skill" as const, name: skill.name, description: skill.description }));
    return [...actionItems, ...agentItems, ...skillItems].sort((a, b) => a.name.localeCompare(b.name));
  }, [agents.data?.items, skills.data?.items]);

  const suggestions = useMemo(() => {
    if (query === null) return [];
    const normalized = query.trim().toLocaleLowerCase();
    return items.filter((item) => !normalized || item.name.toLocaleLowerCase().includes(normalized)).slice(0, 8);
  }, [items, query]);

  return {
    suggestions,
    isPending: agents.isPending || skills.isPending,
    isError: agents.isError || skills.isError,
  };
}
