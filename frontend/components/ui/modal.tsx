"use client";

import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

import { Button } from "@/components/ui/button";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  wide?: boolean;
}

export function Modal({ open, onClose, title, description, children, wide }: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    const frame = requestAnimationFrame(() => dialogRef.current?.focus());
    document.body.style.overflow = "hidden";
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = "";
      previous?.focus();
    };
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-md"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) onClose();
          }}
        >
          <motion.div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="dialog-title"
            aria-describedby={description ? "dialog-description" : undefined}
            tabIndex={-1}
            initial={{ opacity: 0, y: 22, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 420, damping: 34 }}
            className={`surface w-full overflow-hidden rounded-panel ${wide ? "max-w-2xl" : "max-w-lg"}`}
          >
            <div className="flex items-start justify-between border-b border-white/[0.07] px-6 py-5">
              <div>
                <h2 id="dialog-title" className="text-lg font-semibold tracking-tight text-white">
                  {title}
                </h2>
                {description && (
                  <p id="dialog-description" className="mt-1 text-sm text-slate-500">
                    {description}
                  </p>
                )}
              </div>
              <Button size="icon" variant="ghost" onClick={onClose} aria-label="Close dialog">
                <X className="h-4 w-4" />
              </Button>
            </div>
            <div className="max-h-[min(72vh,46rem)] overflow-y-auto p-6">{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
