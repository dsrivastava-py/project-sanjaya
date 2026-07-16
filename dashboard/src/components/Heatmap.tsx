// Month calendar heatmap (§10.2): sequential gold ramp = active hours — one
// hue, light→dark; dark-mode steps clear 2:1 vs surface (verified in
// palette.ts). Zero-activity days render surface + hairline (honest gap, §13.1).
import { useMemo, useState } from "react";

import type { RangeDay } from "../lib/api";
import { fmtDateShort, fmtHM, monthDates } from "../lib/format";
import { HEAT_RAMP, type ThemeName } from "../lib/palette";

// Ordinal thresholds (active hours → ramp step)
const STEPS = [2, 4, 6, 8]; // >0–2, 2–4, 4–6, ≥6

function stepOf(activeS: number): number {
  const h = activeS / 3600;
  if (h <= 0) return -1;
  for (let i = 0; i < STEPS.length - 1; i++) if (h < STEPS[i]) return i;
  return STEPS.length - 1;
}

export function Heatmap({
  month,
  days,
  today,
  theme,
  onPick,
}: {
  month: string; // YYYY-MM
  days: RangeDay[];
  today: string;
  theme: ThemeName;
  onPick: (date: string) => void;
}) {
  const [tip, setTip] = useState<{ x: number; y: number; d: RangeDay } | null>(null);
  const byDate = useMemo(() => new Map(days.map((d) => [d.date, d])), [days]);
  const dates = monthDates(month);
  // Monday-first grid offset
  const firstDow = (new Date(`${dates[0]}T12:00:00`).getDay() + 6) % 7;
  const ramp = HEAT_RAMP[theme];

  return (
    <div className="relative" onMouseLeave={() => setTip(null)}>
      <div className="mb-1 grid grid-cols-7 gap-1 text-center text-[12px] text-ink3">
        {["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((d) => (
          <span key={d}>{d}</span>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {Array.from({ length: firstDow }).map((_, i) => (
          <span key={`pad${i}`} />
        ))}
        {dates.map((date) => {
          const d = byDate.get(date);
          const future = date > today;
          const step = d ? stepOf(d.active_seconds) : -1;
          const bg = step >= 0 ? ramp[step] : "var(--surface-2)";
          const inkOnFill = step >= (theme === "light" ? 2 : 1) ? "#0A0D19" : "var(--text-2)";
          return (
            <button
              key={date}
              type="button"
              disabled={future}
              onClick={() => onPick(date)}
              aria-label={`${date}: ${d ? fmtHM(d.active_seconds) : "no data"} active`}
              className={`tnum flex h-10 items-center justify-center rounded-[6px] border text-[12px] transition-transform duration-150 ${
                future
                  ? "cursor-default border-transparent text-ink3/40"
                  : "border-hairline hover:scale-[1.06]"
              } ${date === today ? "ring-1 ring-[var(--focus-ring)]" : ""}`}
              style={future ? {} : { background: bg, color: step >= 0 ? inkOnFill : "var(--text-3)" }}
              onMouseMove={(e) => {
                if (future || !d) return;
                const host = (e.currentTarget.offsetParent as HTMLElement)?.getBoundingClientRect();
                if (host) setTip({ x: e.clientX - host.left, y: e.clientY - host.top, d });
              }}
            >
              {Number(date.slice(8))}
            </button>
          );
        })}
      </div>
      {/* ramp legend: sequential, one hue */}
      <div className="mt-3 flex items-center gap-1.5 text-[12px] text-ink3">
        <span>less</span>
        <span className="h-3 w-5 rounded-[3px] border border-hairline bg-surface2" />
        {ramp.map((c) => (
          <span key={c} className="h-3 w-5 rounded-[3px]" style={{ background: c }} />
        ))}
        <span>more</span>
      </div>
      {tip && (
        <div
          className="pointer-events-none absolute z-10 rounded-[10px] border border-hairline bg-surface2 px-3 py-2 text-[13px] shadow-lg"
          style={{ left: tip.x + 10, top: tip.y + 12 }}
        >
          <div className="font-medium text-ink1">{fmtDateShort(tip.d.date)}</div>
          <div className="tnum text-ink2">{fmtHM(tip.d.active_seconds)} active</div>
          {tip.d.focus_score != null && (
            <div className="tnum text-ink3">focus {Math.round(tip.d.focus_score)}</div>
          )}
        </div>
      )}
    </div>
  );
}
