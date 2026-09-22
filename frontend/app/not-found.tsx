import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center px-6 text-center">
      <p className="eyebrow">Signal lost</p>
      <h1 className="mt-4 text-5xl font-semibold tracking-[-0.05em] text-white">This route drifted offline.</h1>
      <p className="mt-4 max-w-md text-sm leading-6 text-slate-500">The resource may have moved or no longer exists.</p>
      <Link href="/" className="mt-7 rounded-xl bg-signal-400 px-4 py-3 text-sm font-semibold text-ink-950 transition hover:bg-signal-300">Return to command center</Link>
    </div>
  );
}
