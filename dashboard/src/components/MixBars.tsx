// CATEGORY MIX (§10.1): thin horizontal bars, direct-labeled h:mm. Color
// follows the category entity (slot); labels always in ink tokens (§4.3).
// Idle never appears here — it is not a category.
import { useState } from "react";

import type { Category } from "../lib/api";
import { fmtHM } from "../lib/format";
import { keyColorName, type ThemeName } from "../lib/palette";
import { Dot, Empty } from "./ui";

export function MixBars({
  totals,
  categories,
  theme,
}: {
  totals: Record<string, number>; // category-id string | "uncategorized" → seconds
  categories: Category[];
  theme: ThemeName;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const entries = Object.entries(totals)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return <Empty>No tracked activity yet.</Empty>;
  const max = entries[0][1];
  const total = entries.reduce((a, [, v]) => a + v, 0);

  return (
    <ul className="space-y-2.5">
      {entries.map(([key, secs]) => {
        const { color, name } = keyColorName(key, categories, theme);
        const pct = Math.round((secs / total) * 100);
        return (
          <li
            key={key}
            className="group"
            onMouseEnter={() => setHover(key)}
            onMouseLeave={() => setHover(null)}
            title={`${name} — ${fmtHM(secs)} (${pct}% of active time)`}
          >
            <div className="mb-1 flex items-center justify-between text-[13px]">
              <span className="flex min-w-0 items-center gap-2 text-ink2">
                <Dot color={color} />
                <span className="truncate">{name}</span>
              </span>
              <span className="tnum text-ink1">
                {fmtHM(secs)}
                {hover === key && <span className="ml-1 text-ink3">· {pct}%</span>}
              </span>
            </div>
            {/* bar ≤24px, 4px rounded data end (§4.3) */}
            <div className="h-3 w-full rounded-[4px] bg-surface2/60">
              <div
                className="h-3 rounded-[4px] transition-[width] duration-200"
                style={{ width: `${Math.max(1.5, (secs / max) * 100)}%`, background: color }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
