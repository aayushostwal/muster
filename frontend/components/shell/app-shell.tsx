"use client";

import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Activity, Bot, Command, FolderCode, Menu, Network, PanelLeftClose, Search, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Logo } from "@/components/brand/logo";
import { GlobalTaskComposer } from "@/components/task/global-task-composer";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cn, initials } from "@/lib/utils";

function SidebarContent({ close }: { close?: () => void }) {
  const pathname = usePathname();
  const { data } = useQuery({ queryKey: ["projects"], queryFn: api.projects });

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-[var(--header-height)] items-center border-b border-white/[0.07] px-5">
        <Link href="/" onClick={close} aria-label="Muster command center">
          <Logo />
        </Link>
      </div>
      <nav className="flex-1 overflow-y-auto px-3 py-5" aria-label="Primary navigation">
        <p className="px-3 text-[0.64rem] font-semibold uppercase tracking-[0.16em] text-slate-600">Workspace</p>
        <Link
          href="/"
          onClick={close}
          className={cn(
            "mt-2 flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition",
            pathname === "/" ? "bg-white/[0.075] text-white" : "text-slate-500 hover:bg-white/[0.04] hover:text-slate-200",
          )}
        >
          <Command className="h-4 w-4" />
          Command center
        </Link>
        <div className="mt-8 px-3">
          <p className="text-[0.64rem] font-semibold uppercase tracking-[0.16em] text-slate-600">Global configuration</p>
        </div>
        <div className="mt-2 space-y-1">
          {[
            { href: "/registry/agents", label: "Agents", icon: Bot },
            { href: "/registry/skills", label: "Skills", icon: Sparkles },
            { href: "/registry/mcp", label: "MCP connectors", icon: Network },
            { href: "/registry/directories", label: "Directories", icon: FolderCode },
          ].map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href;
            return <Link key={item.href} href={item.href} onClick={close} className={cn("flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition", active ? "bg-white/[0.075] text-white" : "text-slate-500 hover:bg-white/[0.04] hover:text-slate-200")}><Icon className={cn("h-4 w-4", active && "text-signal-400")} />{item.label}</Link>;
          })}
        </div>
        <div className="mt-8 flex items-center justify-between px-3">
          <p className="text-[0.64rem] font-semibold uppercase tracking-[0.16em] text-slate-600">Active projects</p>
          <span className="font-mono text-[0.65rem] text-slate-700">{data?.items.length ?? 0}</span>
        </div>
        <div className="mt-2 space-y-1">
          {data?.items.slice(0, 8).map((project) => {
            const active = pathname.startsWith(`/projects/${project.id}`);
            return (
              <Link
                key={project.id}
                href={`/projects/${project.id}/board`}
                onClick={close}
                className={cn(
                  "group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition",
                  active ? "bg-signal-400/[0.08] text-signal-300" : "text-slate-500 hover:bg-white/[0.04] hover:text-slate-200",
                )}
              >
                <span className={cn("grid h-7 w-7 place-items-center rounded-lg border text-[0.62rem] font-semibold", active ? "border-signal-400/20 bg-signal-400/10" : "border-white/[0.07] bg-white/[0.03]")}>
                  {initials(project.name)}
                </span>
                <span className="min-w-0 flex-1 truncate">{project.name}</span>
              </Link>
            );
          })}
        </div>
      </nav>
      <div className="m-3 rounded-xl border border-white/[0.07] bg-white/[0.025] p-3">
        <div className="flex items-center gap-2 text-xs font-medium text-slate-300">
          <Activity className="h-3.5 w-3.5 text-signal-400" />
          Local-first control
        </div>
        <p className="mt-2 text-[0.68rem] leading-5 text-slate-600">Your agents and project data stay on this machine.</p>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const health = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 30_000,
    retry: 1,
  });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        window.dispatchEvent(new CustomEvent("muster:focus-search"));
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="min-h-screen">
      <aside className={cn("fixed inset-y-0 left-0 z-30 hidden border-r border-white/[0.07] bg-ink-950/80 backdrop-blur-xl transition-[width] duration-300 ease-spring lg:block", collapsed ? "w-0 overflow-hidden border-0" : "w-[var(--sidebar-width)]")}>
        <div className="w-[var(--sidebar-width)]"><SidebarContent /></div>
      </aside>
      <header className={cn("fixed right-0 top-0 z-20 flex h-[var(--header-height)] items-center justify-between border-b border-white/[0.07] bg-ink-950/70 px-4 backdrop-blur-xl transition-[left] duration-300 ease-spring md:px-6", collapsed ? "left-0" : "left-0 lg:left-[var(--sidebar-width)]")}>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation">
            <Menu className="h-5 w-5" />
          </Button>
          <Button variant="ghost" size="icon" className="hidden lg:inline-flex" onClick={() => setCollapsed((value) => !value)} aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}>
            <PanelLeftClose className={cn("h-4 w-4 transition-transform", collapsed && "rotate-180")} />
          </Button>
          <button onClick={() => window.dispatchEvent(new CustomEvent("muster:focus-search"))} className="ml-1 hidden items-center gap-2 rounded-xl border border-white/[0.07] bg-white/[0.025] px-3 py-2 text-xs text-slate-600 transition hover:border-white/15 hover:text-slate-300 sm:flex">
            <Search className="h-3.5 w-3.5" />
            Search control center
            <kbd className="ml-4 rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5 font-mono text-[0.6rem] text-slate-500">⌘ K</kbd>
          </button>
        </div>
        <div className="flex items-center gap-2 rounded-full border border-white/[0.07] bg-white/[0.025] px-3 py-1.5 text-[0.68rem] font-medium text-slate-400">
          <span className={cn("h-1.5 w-1.5 rounded-full", health.isSuccess ? "bg-signal-400 shadow-[0_0_10px_#42e8c4]" : health.isPending ? "animate-pulse bg-amber-400" : "bg-red-400")} />
          {health.isSuccess ? "Core online" : health.isPending ? "Connecting" : "Core offline"}
        </div>
      </header>
      <main className={cn("min-h-screen pt-[var(--header-height)] transition-[padding] duration-300 ease-spring", collapsed ? "lg:pl-0" : "lg:pl-[var(--sidebar-width)]")}>{children}</main>
      <GlobalTaskComposer />

      <AnimatePresence>
        {mobileOpen && (
          <>
            <motion.button aria-label="Close navigation" className="fixed inset-0 z-40 bg-black/65 backdrop-blur-sm lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setMobileOpen(false)} />
            <motion.aside className="fixed inset-y-0 left-0 z-50 w-[min(86vw,var(--sidebar-width))] border-r border-white/10 bg-ink-950 lg:hidden" initial={{ x: "-100%" }} animate={{ x: 0 }} exit={{ x: "-100%" }} transition={{ type: "spring", stiffness: 360, damping: 38 }}>
              <button className="absolute right-3 top-4 z-10 rounded-lg p-2 text-slate-500 hover:bg-white/5 hover:text-white" onClick={() => setMobileOpen(false)} aria-label="Close navigation"><X className="h-4 w-4" /></button>
              <SidebarContent close={() => setMobileOpen(false)} />
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </div>
  );
}
