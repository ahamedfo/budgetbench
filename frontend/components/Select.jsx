"use client";

// Minimal styled select: native behavior, custom chevron, no browser arrow.
export default function Select({ value, onChange, disabled, children, className = "" }) {
  return (
    <div className={`relative ${className}`}>
      <select className="select" value={value} onChange={onChange} disabled={disabled}>
        {children}
      </select>
      <svg
        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-carbon-subtle"
        viewBox="0 0 20 20"
        fill="none"
        stroke="currentColor"
      >
        <path d="M6 8l4 4 4-4" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}
