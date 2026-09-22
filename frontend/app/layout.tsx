import type { Metadata, Viewport } from "next";
import Script from "next/script";
import type { ReactNode } from "react";

import "@/app/globals.css";
import { Providers } from "@/app/providers";
import { AppShell } from "@/components/shell/app-shell";

export const metadata: Metadata = {
  title: { default: "Muster — Agent Command Center", template: "%s · Muster" },
  description: "Orchestrate Claude Code and Codex agents from one local-first command center.",
  icons: { icon: "/logo.svg" },
};

export const viewport: Viewport = {
  themeColor: "#06070a",
  colorScheme: "dark",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" data-scroll-behavior="smooth">
      <body className="noise">
        <Script src="/runtime-config.js" strategy="beforeInteractive" />
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
