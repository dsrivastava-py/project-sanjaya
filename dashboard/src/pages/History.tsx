// History (§10.2): month calendar heatmap (sequential gold ramp = active
// hours) + 7/30/90-day stacked category bars. Click a day → its Today view.
import { useState } from "react";

import { StackedCategoryBars } from "../components/charts";
import { ChartCard } from "../components/ChartCard";
import { Heatmap } from "../components/Heatmap";
import { Empty, IconButton } from "../components/ui";
import type { Category } from "../lib/api";
import { useRange } from "../lib/api";
import {
  addDays,
  fmtHM,
  fmtHours,
  monthDates,
  monthLabel,
  monthOf,
  addMonths,
} from "../lib/format";
import { keyColorName, type ThemeName } from "../lib/palette";

const RANGES = [7, 30, 90] as const;

export function History({
  today,
  categories,
  theme,
  onPick,
}: {
  today: string | null;
  categories: Category[];
  theme: ThemeName;
  onPick: (date: string) => void;
}) {
  const [month, setMonth] = useState<string | null>(null);
  const [rangeDays, setRangeDays] = useState<(typeof RANGES)[number]>(30);
  const activeMonth = month ?? (today ? monthOf(today) : null);

  const mDates = activeMonth ? monthDates(activeMonth) : [];
  const mFrom = mDates[0] ?? null;
  const mTo = mDates.length
    ? today && mDates[mDates.length - 1] > today
      ? today
      : mDates[mDates.length - 1]
    : null;
  const monthQ = useRange(mFrom, mTo && mFrom && mTo >= mFrom ? mTo : mFrom);

  const rFrom = today ? addDays(today, -(rangeDays - 1)) : null;
  const rangeQ = useRange(rFrom, today);

  if (!today) return <Empty>Loading…</Empty>;

  return (
    <div className="mx-auto max-w-[1200px]">
      <h1 className="mb-5 font-display text-[24px] font-semibold text-ink1">History</h1>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <ChartCard
          title={activeMonth ? monthLabel(activeMonth) : "…"}
          className="lg:col-span-2"
          actions={
            <>
              <IconButton label="Previous month"
                onClick={() => activeMonth && setMonth(addMonths(activeMonth, -1))}>‹</IconButton>
              <IconButton label="Next month"
                onClick={() => activeMonth && setMonth(addMonths(activeMonth, 1))}
                disabled={!activeMonth || activeMonth >= monthOf(today)}>›</IconButton>
            </>
          }
          table={{
            columns: ["Date", "Active", "Focus"],
            rows: (monthQ.data ?? [])
              .filter((d) => d.active_seconds > 0)
              .map((d) => [d.date, fmtHM(d.active_seconds),
                           d.focus_score != null ? Math.round(d.focus_score) : "—"]),
          }}
        >
          {activeMonth && (
            <Heatmap
              month={activeMonth}
              days={monthQ.data ?? []}
              today={today}
              theme={theme}
              onPick={onPick}
            />
          )}
        </ChartCard>

        <ChartCard
          title={`Last ${rangeDays} days by category`}
          className="lg:col-span-3"
          actions={
            <div className="flex gap-1">
              {RANGES.map((r) => (
                <IconButton key={r} label={`${r} days`} active={rangeDays === r}
                            onClick={() => setRangeDays(r)}>
                  {r}d
                </IconButton>
              ))}
            </div>
          }
          table={{
            columns: ["Date", "Category", "Hours"],
            rows: (rangeQ.data ?? []).flatMap((d) =>
              Object.entries(d.category_totals)
                .filter(([, v]) => v > 0)
                .map(([k, v]) => [d.date, keyColorName(k, categories, theme).name, fmtHours(v)]),
            ),
          }}
        >
          {rangeQ.data && rangeQ.data.some((d) => d.active_seconds > 0) ? (
            <StackedCategoryBars days={rangeQ.data} categories={categories} theme={theme} />
          ) : (
            <Empty>No tracked activity in this range yet.</Empty>
          )}
        </ChartCard>
      </div>
    </div>
  );
}
