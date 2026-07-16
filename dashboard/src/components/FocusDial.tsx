// Hero focus-score dial: gold arc on a recessive track, count-up number
// (≤600ms, §4.4), subtle gold glow (§4.1). Deterministic score — not AI (§8.6).
import { useEffect, useRef, useState } from "react";

export function FocusDial({ score }: { score: number | null }) {
  const target = score == null ? 0 : Math.max(0, Math.min(100, score));
  const [shown, setShown] = useState(0);
  const raf = useRef<number>(0);

  useEffect(() => {
    const t0 = performance.now();
    const dur = 600;
    cancelAnimationFrame(raf.current);
    const from = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / dur);
      const eased = 1 - Math.pow(1 - p, 3); // ease-out
      setShown(from + (target - from) * eased);
      if (p < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target]);

  // 270° arc from 135° to 405°
  const R = 62;
  const C = 2 * Math.PI * R;
  const arcLen = C * 0.75;
  const progress = (shown / 100) * arcLen;

  return (
    <div className="relative h-[160px] w-[160px]" role="img"
         aria-label={score == null ? "No focus score yet" : `Focus score ${Math.round(target)} of 100`}>
      <svg viewBox="0 0 160 160" className="h-full w-full -rotate-[225deg]">
        <circle cx="80" cy="80" r={R} fill="none" stroke="var(--grid)" strokeWidth="10"
                strokeLinecap="round" strokeDasharray={`${arcLen} ${C}`} />
        {score != null && (
          <circle cx="80" cy="80" r={R} fill="none" stroke="var(--accent)" strokeWidth="10"
                  strokeLinecap="round" strokeDasharray={`${progress} ${C}`}
                  style={{ filter: "drop-shadow(0 0 10px rgba(232,180,74,0.35))" }} />
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="tnum font-display text-[48px] font-semibold leading-none text-ink1">
          {score == null ? "—" : Math.round(shown)}
        </span>
        <span className="mt-1 text-[12px] uppercase tracking-[0.1em] text-ink3">Focus</span>
      </div>
    </div>
  );
}
