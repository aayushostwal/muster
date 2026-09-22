"use client";

import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, CircleAlert, Info, X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

type ToastTone = "success" | "error" | "info";
interface ToastItem {
  id: number;
  message: string;
  tone: ToastTone;
}

const ToastContext = createContext<((message: string, tone?: ToastTone) => void) | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const dismiss = useCallback((id: number) => {
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);
  const notify = useCallback(
    (message: string, tone: ToastTone = "info") => {
      const id = Date.now() + Math.random();
      setItems((current) => [...current.slice(-3), { id, message, tone }]);
      window.setTimeout(() => dismiss(id), 4200);
    },
    [dismiss],
  );
  const value = useMemo(() => notify, [notify]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-[70] flex w-[min(24rem,calc(100vw-2.5rem))] flex-col gap-2" aria-live="polite">
        <AnimatePresence initial={false}>
          {items.map((item) => {
            const Icon = item.tone === "success" ? CheckCircle2 : item.tone === "error" ? CircleAlert : Info;
            return (
              <motion.div
                key={item.id}
                initial={{ opacity: 0, x: 35, scale: 0.96 }}
                animate={{ opacity: 1, x: 0, scale: 1 }}
                exit={{ opacity: 0, x: 20, scale: 0.97 }}
                layout
                className="surface pointer-events-auto flex items-center gap-3 rounded-xl px-4 py-3.5"
              >
                <Icon className={item.tone === "error" ? "h-4 w-4 text-red-400" : item.tone === "success" ? "h-4 w-4 text-signal-400" : "h-4 w-4 text-pulse-400"} />
                <span className="flex-1 text-sm text-slate-200">{item.message}</span>
                <button onClick={() => dismiss(item.id)} className="text-slate-600 transition hover:text-white" aria-label="Dismiss notification">
                  <X className="h-4 w-4" />
                </button>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context;
}
