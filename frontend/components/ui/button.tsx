"use client";

import { motion, type HTMLMotionProps } from "framer-motion";
import type { ReactNode } from "react";
import { LoaderCircle } from "lucide-react";

import { cn } from "@/lib/utils";

interface ButtonProps extends Omit<HTMLMotionProps<"button">, "children"> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "icon";
  loading?: boolean;
  children?: ReactNode;
}

export function Button({
  className,
  variant = "secondary",
  size = "md",
  loading,
  disabled,
  children,
  ...props
}: ButtonProps) {
  return (
    <motion.button
      whileHover={disabled ? undefined : { y: -1 }}
      whileTap={disabled ? undefined : { scale: 0.98 }}
      transition={{ type: "spring", stiffness: 500, damping: 30 }}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45",
        {
          "bg-signal-400 text-ink-950 shadow-[0_8px_30px_rgba(66,232,196,0.18)] hover:bg-signal-300":
            variant === "primary",
          "border border-white/10 bg-white/[0.045] text-slate-200 hover:border-white/20 hover:bg-white/[0.075] hover:text-white":
            variant === "secondary",
          "text-slate-400 hover:bg-white/[0.055] hover:text-white": variant === "ghost",
          "border border-red-400/20 bg-red-400/10 text-red-300 hover:bg-red-400/15":
            variant === "danger",
          "h-9 px-3 text-xs": size === "sm",
          "h-11 px-4 text-sm": size === "md",
          "h-9 w-9 p-0": size === "icon",
        },
        className,
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />}
      {children}
    </motion.button>
  );
}
