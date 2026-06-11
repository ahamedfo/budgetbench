"use client";
import Link from "next/link";

function Action({ children, onClick, href, primary }) {
  const cls = `flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors ${
    primary
      ? "bg-carbon-blue text-white hover:bg-carbon-blueHover"
      : "border border-white/20 text-white/90 hover:bg-white/10"
  }`;
  if (href)
    return (
      <Link href={href} className={cls}>
        {children}
      </Link>
    );
  return (
    <button onClick={onClick} className={cls}>
      {children}
    </button>
  );
}

export default function TopBar() {
  return (
    <header className="sticky top-0 z-30">
      <div className="h-12 bg-[#161616] text-white flex items-center px-4">
        <Link href="/" className="font-bold tracking-tight text-lg mr-3">
          IBM
        </Link>
        <span className="text-white/30 mr-3">|</span>
        <span className="text-sm text-white/90 truncate">
          Budget<span className="text-carbon-blue font-semibold">Bench</span>
          <span className="text-white/50"> — Executive Dashboard</span>
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Action onClick={() => window.location.reload()}>↻ Refresh</Action>
          <Action onClick={() => window.print()} primary>
            ⎙ Print
          </Action>
        </div>
      </div>
    </header>
  );
}
