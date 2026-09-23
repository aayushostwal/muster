"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Bot, Clock3, Code2, FolderCode, KeyRound, Link2, Network, Settings2, Sparkles } from "lucide-react";
import { useState } from "react";

import { ProjectHeader } from "@/components/project/project-header";
import { ArtifactPanel, CapabilityPanel, CronPanel, DirectoryPanel, ProfilePanel, SecretPanel, ToolPanel } from "@/components/project/resource-panels";
import { cn } from "@/lib/utils";

const tabs = [
  { id: "profile", label: "Profile", icon: Settings2 },
  { id: "directories", label: "Directories", icon: FolderCode },
  { id: "agents", label: "Agents", icon: Bot },
  { id: "skills", label: "Skills", icon: Sparkles },
  { id: "mcp", label: "MCP connectors", icon: Network },
  { id: "tools", label: "Tool permissions", icon: Code2 },
  { id: "artifacts", label: "Artifacts", icon: Link2 },
  { id: "schedules", label: "Schedules", icon: Clock3 },
  { id: "secrets", label: "Secrets", icon: KeyRound },
] as const;

type Tab = (typeof tabs)[number]["id"];

export function ProjectWorkspace({ projectId }: { projectId: string }) {
  const [active, setActive] = useState<Tab>("profile");

  return (
    <div className="mx-auto max-w-screen-2xl px-5 py-6 md:px-8 md:py-8">
      <ProjectHeader projectId={projectId} />
      <div className="mt-5 grid gap-5 xl:grid-cols-[15rem_minmax(0,1fr)]">
        <nav className="surface flex gap-1 overflow-x-auto rounded-panel p-2 xl:flex-col xl:self-start" aria-label="Project capabilities">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button key={tab.id} onClick={() => setActive(tab.id)} className={cn("relative flex shrink-0 items-center gap-3 rounded-xl px-3 py-2.5 text-left text-xs font-medium transition xl:w-full", active === tab.id ? "text-white" : "text-slate-500 hover:bg-white/[0.03] hover:text-slate-300")} aria-current={active === tab.id ? "page" : undefined}>
                {active === tab.id && <motion.span layoutId="capability-active" className="absolute inset-0 rounded-xl border border-white/[0.08] bg-white/[0.065]" />}
                <Icon className={cn("relative h-4 w-4", active === tab.id && "text-signal-400")} />
                <span className="relative">{tab.label}</span>
              </button>
            );
          })}
        </nav>
        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={active} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -5 }} transition={{ duration: 0.2 }}>
            {active === "profile" && <ProfilePanel projectId={projectId} />}
            {active === "directories" && <DirectoryPanel projectId={projectId} />}
            {active === "agents" && <CapabilityPanel projectId={projectId} type="agent" />}
            {active === "skills" && <CapabilityPanel projectId={projectId} type="skill" />}
            {active === "mcp" && <CapabilityPanel projectId={projectId} type="mcp" />}
            {active === "tools" && <ToolPanel projectId={projectId} />}
            {active === "artifacts" && <ArtifactPanel projectId={projectId} />}
            {active === "schedules" && <CronPanel projectId={projectId} />}
            {active === "secrets" && <SecretPanel projectId={projectId} />}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
