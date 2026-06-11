"use client";
import { useEffect, useRef, useState } from "react";

// Animate a number toward `target` so KPI tiles visibly shift when the
// selected agent changes or a live result lands.
export function useCountUp(target, durationMs = 650) {
  const [val, setVal] = useState(target ?? 0);
  const fromRef = useRef(target ?? 0);
  const rafRef = useRef(null);
  const startRef = useRef(0);

  useEffect(() => {
    if (target == null) return;
    const from = fromRef.current;
    const to = target;
    if (from === to) return;
    cancelAnimationFrame(rafRef.current);
    startRef.current = 0;

    const tick = (ts) => {
      if (!startRef.current) startRef.current = ts;
      const p = Math.min((ts - startRef.current) / durationMs, 1);
      const eased = 1 - Math.pow(1 - p, 3); // easeOutCubic
      const cur = from + (to - from) * eased;
      setVal(cur);
      if (p < 1) rafRef.current = requestAnimationFrame(tick);
      else fromRef.current = to;
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [target, durationMs]);

  return val;
}
