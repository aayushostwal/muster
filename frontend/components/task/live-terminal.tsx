"use client";

import type { FitAddon } from "@xterm/addon-fit";
import type { Terminal } from "@xterm/xterm";
import { Maximize2, Radio, WifiOff } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { useTerminalSession } from "@/hooks/use-terminal-session";
import { cn } from "@/lib/utils";

export function LiveTerminal({ taskId }: { taskId: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const pendingOutputRef = useRef<Uint8Array[]>([]);
  const pendingGapRef = useRef(false);
  const [ready, setReady] = useState(false);

  const onOutput = useCallback((data: Uint8Array) => {
    if (terminalRef.current) terminalRef.current.write(data);
    else pendingOutputRef.current.push(data);
  }, []);
  const onGap = useCallback(() => {
    if (!terminalRef.current) pendingGapRef.current = true;
    else {
      terminalRef.current.reset();
      terminalRef.current.writeln("\r\n\x1b[33m[muster: reconnecting from retained scrollback]\x1b[0m");
    }
  }, []);
  const session = useTerminalSession(taskId, { onOutput, onGap });
  const { resize, sendBytes, sendText } = session;

  useEffect(() => {
    let disposed = false;
    let resizeObserver: ResizeObserver | null = null;
    let terminal: Terminal | null = null;
    let fitAddon: FitAddon | null = null;
    const disposables: Array<{ dispose: () => void }> = [];

    const mount = async () => {
      const [{ Terminal: XTerm }, { FitAddon: XTermFitAddon }] = await Promise.all([
        import("@xterm/xterm"),
        import("@xterm/addon-fit"),
      ]);
      if (disposed || !containerRef.current) return;
      terminal = new XTerm({
        cursorBlink: true,
        cursorStyle: "bar",
        fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", monospace',
        fontSize: 13,
        lineHeight: 1.25,
        scrollback: 10_000,
        allowProposedApi: false,
        theme: {
          background: "#05070b",
          foreground: "#d7dee9",
          cursor: "#42e8c4",
          selectionBackground: "#2b635f99",
          black: "#0b0d12",
          brightBlack: "#5e6878",
          green: "#42e8c4",
          brightGreen: "#71f4d8",
          blue: "#8a8cff",
          brightBlue: "#a6a7ff",
        },
      });
      fitAddon = new XTermFitAddon();
      terminal.loadAddon(fitAddon);
      terminal.open(containerRef.current);
      terminalRef.current = terminal;
      fitRef.current = fitAddon;
      if (pendingGapRef.current) {
        terminal.reset();
        terminal.writeln("\r\n\x1b[33m[muster: reconnecting from retained scrollback]\x1b[0m");
        pendingGapRef.current = false;
      }
      for (const data of pendingOutputRef.current) terminal.write(data);
      pendingOutputRef.current = [];
      fitAddon.fit();
      resize(terminal.cols, terminal.rows);
      terminal.focus();
      disposables.push(terminal.onData((data) => sendText(data)));
      disposables.push(terminal.onBinary((data) => {
        const bytes = Uint8Array.from(data, (character) => character.charCodeAt(0));
        sendBytes(bytes);
      }));
      resizeObserver = new ResizeObserver(() => {
        if (!fitAddon || !terminal) return;
        fitAddon.fit();
        resize(terminal.cols, terminal.rows);
      });
      resizeObserver.observe(containerRef.current);
      setReady(true);
    };
    void mount();
    return () => {
      disposed = true;
      resizeObserver?.disconnect();
      disposables.forEach((item) => item.dispose());
      terminal?.dispose();
      terminalRef.current = null;
      fitRef.current = null;
    };
  }, [resize, sendBytes, sendText]);

  return (
    <div className="relative h-full min-h-0 bg-[#05070b]">
      <div
        ref={containerRef}
        className={cn("h-full min-h-0 px-2 py-2 transition-opacity", ready ? "opacity-100" : "opacity-0")}
        aria-label="Interactive agent terminal"
      />
      {!ready && <div className="absolute inset-0 grid place-items-center font-mono text-xs text-slate-600">Starting terminal renderer…</div>}
      <div className="pointer-events-none absolute right-3 top-3 flex items-center gap-2">
        <span className={cn(
          "flex items-center gap-1.5 rounded-md border bg-black/75 px-2 py-1 font-mono text-[0.56rem] uppercase tracking-wider backdrop-blur",
          session.connection === "live" ? "border-signal-400/15 text-signal-400" : "border-amber-400/15 text-amber-300",
        )}>
          {session.connection === "live" ? <Radio className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
          {session.connection}
        </span>
      </div>
      {session.control === "read_only" && !session.exit && (
        <div className="absolute inset-x-0 bottom-3 flex justify-center">
          <Button className="pointer-events-auto shadow-panel" size="sm" onClick={session.takeControl}>
            <Maximize2 className="h-3.5 w-3.5" /> Take control
          </Button>
        </div>
      )}
      {session.exit && !session.error && (
        <div className="absolute inset-x-0 bottom-3 flex justify-center">
          <span className="rounded-md border border-white/10 bg-black/80 px-3 py-1.5 font-mono text-[0.62rem] text-slate-400 backdrop-blur">
            {session.exit.archived ? "Archived terminal output" : `Terminal exited${session.exit.code === null ? "" : ` (${session.exit.code})`}`}
          </span>
        </div>
      )}
      {session.error && (
        <div className="absolute inset-x-3 bottom-3 rounded-lg border border-red-400/20 bg-red-950/90 px-3 py-2 text-xs text-red-200">
          {session.error}
        </div>
      )}
    </div>
  );
}
