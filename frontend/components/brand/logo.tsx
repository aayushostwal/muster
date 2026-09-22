import { cn } from "@/lib/utils";

interface LogoProps {
  compact?: boolean;
  className?: string;
}

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 48 48"
      role="img"
      aria-label="Muster"
      className={cn("h-9 w-9", className)}
      fill="none"
    >
      <defs>
        <linearGradient id="muster-gradient" x1="7" y1="8" x2="42" y2="41">
          <stop stopColor="#83F7DF" />
          <stop offset="1" stopColor="#6668F5" />
        </linearGradient>
      </defs>
      <path
        d="M8 33.5V17.8c0-2.1 2.5-3.2 4.1-1.8l10.2 9.2a2.5 2.5 0 0 0 3.4 0L35.9 16c1.6-1.4 4.1-.3 4.1 1.8v15.7"
        stroke="url(#muster-gradient)"
        strokeWidth="4.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="8" cy="12" r="3" fill="#83F7DF" />
      <circle cx="24" cy="20" r="3" fill="#A6A7FF" />
      <circle cx="40" cy="12" r="3" fill="#6668F5" />
      <path d="M14 37h20" stroke="white" strokeOpacity=".28" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function Logo({ compact = false, className }: LogoProps) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <LogoMark />
      {!compact && (
        <div className="leading-none">
          <div className="text-lg font-semibold tracking-[-0.04em] text-white">muster</div>
          <div className="mt-1 text-[0.56rem] font-semibold uppercase tracking-[0.2em] text-slate-500">
            agent command
          </div>
        </div>
      )}
    </div>
  );
}
