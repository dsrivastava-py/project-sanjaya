// Insights (§10.3): weekly AI insight card (✦), focus + active-hours trend
// lines (two charts — never dual-axis), per-category small multiples (8 series
// → never spaghetti), and the deterministic "time leaks" table.
import { useState } from "react";

import { CategorySmallMultiples, TrendLine } from "../components/charts";
import { ChartCard } from "../components/ChartCard";
import { Markdown } from "../components/Markdown";
import { AiChip, Card, Empty, IconButton } from "../components/ui";
import type { Category } from "../lib/api";
import { useGenerateWeekly, useLeaks, useRange, useWeekly } from "../lib/api";
import { addDays, fmtDateShort, fmtHM, weekStartOf } from "../lib/format";
import { STATUS, type ThemeName } from "../lib/palette";

export function Insights({
  today,
  categories,
  theme,
}: {
  today: string | null;
  categories: Category[];
  theme: ThemeName;
}) {
  const [week, setWeek] = useState<string | null>(null);
  const activeWeek = week ?? (today ? weekStartOf(today) : null);
  const weekly = useWeekly(activeWeek);
  const genWeekly = useGenerateWeekly(activeWeek);
  const leaks = useLeaks(activeWeek);

  const from = today ? addDays(today, -29) : null;
  const range = useRange(from, today);
  const days = range.data ?? [];
  const trendData = days.map((d) => ({
    date: fmtDateShort(d.date),
    focus: d.focus_score != null ? Math.round(d.focus_score) : null,
    hours: +(d.active_seconds / 3600).toFixed(2),
  }));

  if (!today) return <Empty>Loading…</Empty>;

  return (
    <div className="mx-auto max-w-[1200px]">
      <h1 className="mb-5 font-display text-[24px] font-semibold text-ink1">Insights</h1>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Weekly insight card */}
        <Card
          title={`Week of ${activeWeek ? fmtDateShort(activeWeek) : "…"}`}
          className="lg:col-span-2"
          actions={
            <>
              {weekly.data?.exists && <AiChip />}
              <IconButton label="Previous week"
                onClick={() => activeWeek && setWeek(addDays(activeWeek, -7))}>‹</IconButton>
              <IconButton label="Next week"
                onClick={() => activeWeek && setWeek(addDays(activeWeek, 7))}
                disabled={!activeWeek || activeWeek >= weekStartOf(today)}>›</IconButton>
              <IconButton
                label="Generate weekly insight"
                onClick={() => genWeekly.mutate()}
                disabled={genWeekly.isPending}
              >
                {genWeekly.isPending ? "Thinking…" : "↻ Generate"}
              </IconButton>
            </>
          }
        >
          {genWeekly.isError && (
            <p className="mb-2 text-[13px]" style={{ color: STATUS.serious }}>
              ⚠ AI unavailable — try again once connectivity returns.
            </p>
          )}
          {weekly.data?.exists && weekly.data.insight_md ? (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <div className="md:col-span-2">
                <Markdown text={weekly.data.insight_md} />
              </div>
              <div className="space-y-3 text-[13px]">
                <InsightList label="Wins" items={weekly.data.wins} icon="✓" color={STATUS.good} />
                <InsightList label="Leaks" items={weekly.data.leaks} icon="↘" color={STATUS.serious} />
                <InsightList label="Next week" items={weekly.data.next_week_focus} icon="→"
                             color="var(--accent)" />
              </div>
            </div>
          ) : (
            <Empty>No weekly insight yet — generate one after a few tracked days.</Empty>
          )}
        </Card>

        {/* Two measures → two charts (one axis each; §4.3) */}
        <ChartCard
          title="Focus score — last 30 days"
          table={{
            columns: ["Date", "Focus"],
            rows: trendData.filter((d) => d.focus != null).map((d) => [d.date, d.focus!]),
          }}
        >
          <TrendLine days={trendData} dataKey="focus" color="var(--accent)"
                     domain={[0, 100]} fmt={(v) => `${Math.round(v)}/100`} />
        </ChartCard>
        <ChartCard
          title="Active hours — last 30 days"
          table={{
            columns: ["Date", "Active"],
            rows: trendData.map((d) => [d.date, `${d.hours}h`]),
          }}
        >
          <TrendLine days={trendData} dataKey="hours" color="var(--accent-2)" unit="h"
                     fmt={(v) => fmtHM(v * 3600)} />
        </ChartCard>

        {/* 8 possible category series → small multiples, never spaghetti */}
        <ChartCard
          title="Per-category hours — last 30 days"
          className="lg:col-span-2"
          table={{
            columns: ["Date", "Category", "Hours"],
            rows: days.flatMap((d) =>
              Object.entries(d.category_totals)
                .filter(([, v]) => v > 0)
                .map(([k, v]) => {
                  const cat = categories.find((c) => String(c.id) === k);
                  return [d.date, cat?.name ?? "Uncategorized", (v / 3600).toFixed(1)];
                }),
            ),
          }}
        >
          {days.some((d) => d.active_seconds > 0) ? (
            <CategorySmallMultiples days={days} categories={categories} theme={theme} />
          ) : (
            <Empty>No tracked activity yet.</Empty>
          )}
        </ChartCard>

        {/* Time leaks — deterministic WoW Δ */}
        <Card title="Time leaks — week over week" className="lg:col-span-2">
          {leaks.data && leaks.data.leaks.length > 0 ? (
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-hairline text-left text-ink3">
                  <th className="py-1.5 pr-4 font-medium">Domain</th>
                  <th className="py-1.5 pr-4 font-medium">This week</th>
                  <th className="py-1.5 pr-4 font-medium">Last week</th>
                  <th className="py-1.5 font-medium">Δ</th>
                </tr>
              </thead>
              <tbody>
                {leaks.data.leaks.map((l) => (
                  <tr key={l.domain} className="border-b border-hairline last:border-0">
                    <td className="py-1.5 pr-4 text-ink1">{l.domain}</td>
                    <td className="tnum py-1.5 pr-4 text-ink2">{fmtHM(l.this_s)}</td>
                    <td className="tnum py-1.5 pr-4 text-ink2">{fmtHM(l.prev_s)}</td>
                    <td className="tnum py-1.5"
                        style={{ color: l.delta_s > 0 ? STATUS.serious : STATUS.good }}>
                      {l.delta_s > 0 ? "▲" : l.delta_s < 0 ? "▼" : "•"}{" "}
                      {fmtHM(Math.abs(l.delta_s))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>No leak-worthy domains this week. Clean sailing.</Empty>
          )}
        </Card>
      </div>
    </div>
  );
}

function InsightList({
  label,
  items,
  icon,
  color,
}: {
  label: string;
  items?: string[];
  icon: string;
  color: string;
}) {
  if (!items?.length) return null;
  return (
    <div>
      <span className="text-[12px] uppercase tracking-[0.08em] text-ink3">{label}</span>
      <ul className="mt-1 space-y-1">
        {items.map((it, i) => (
          <li key={i} className="flex items-start gap-1.5 text-ink2">
            <span style={{ color }}>{icon}</span> {it}
          </li>
        ))}
      </ul>
    </div>
  );
}
