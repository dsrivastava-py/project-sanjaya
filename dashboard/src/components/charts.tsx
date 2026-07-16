// Recharts wrappers obeying §4.3: one axis per chart (never dual), thin marks,
// 2px lines, 2px surface gaps, ink-token text, legend for ≥2 series, hover
// tooltips. Colors resolved from the category ENTITY's slot — never its rank.
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Category, RangeDay } from "../lib/api";
import { fmtDateShort, fmtHM } from "../lib/format";
import { keyColorName, type ThemeName } from "../lib/palette";
import { Dot } from "./ui";

const AXIS_TICK = { fill: "var(--text-3)", fontSize: 12 } as const;

function ChartTip({
  active,
  payload,
  label,
  fmt,
}: {
  active?: boolean;
  payload?: { name?: string; value?: number | string; color?: string }[];
  label?: string | number;
  fmt: (v: number) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-[10px] border border-hairline bg-surface2 px-3 py-2 text-[13px] shadow-lg">
      <div className="mb-1 font-medium text-ink1">{label}</div>
      {payload
        .filter((p) => Number(p.value) > 0 || payload.length === 1)
        .map((p, i) => (
          <div key={i} className="flex items-center gap-2 text-ink2">
            <Dot color={p.color ?? "var(--text-3)"} />
            <span>{p.name}</span>
            <span className="tnum ml-auto pl-3 text-ink1">{fmt(Number(p.value))}</span>
          </div>
        ))}
    </div>
  );
}

export function LegendRow({
  keys,
  categories,
  theme,
}: {
  keys: string[];
  categories: Category[];
  theme: ThemeName;
}) {
  return (
    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink2">
      {keys.map((k) => {
        const { color, name } = keyColorName(k, categories, theme);
        return (
          <span key={k} className="flex items-center gap-1.5">
            <Dot color={color} /> {name}
          </span>
        );
      })}
    </div>
  );
}

/** Category keys present in a range, ordered by fixed slot order (entity order). */
export function rangeCategoryKeys(days: RangeDay[], categories: Category[]): string[] {
  const present = new Set<string>();
  for (const d of days)
    for (const [k, v] of Object.entries(d.category_totals)) if (v > 0) present.add(k);
  const ordered = categories
    .filter((c) => present.has(String(c.id)))
    .sort((a, b) => (a.color_slot ?? 99) - (b.color_slot ?? 99))
    .map((c) => String(c.id));
  if (present.has("uncategorized")) ordered.push("uncategorized");
  return ordered;
}

/** History: stacked per-day category hours. One y-axis (hours). */
export function StackedCategoryBars({
  days,
  categories,
  theme,
}: {
  days: RangeDay[];
  categories: Category[];
  theme: ThemeName;
}) {
  const keys = rangeCategoryKeys(days, categories);
  const data = days.map((d) => {
    const row: Record<string, number | string> = { date: fmtDateShort(d.date) };
    for (const k of keys) row[k] = +((d.category_totals[k] ?? 0) / 3600).toFixed(2);
    return row;
  });
  const tickEvery = Math.max(1, Math.ceil(days.length / 12));
  return (
    <div>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
          <CartesianGrid stroke="var(--grid)" strokeWidth={1} vertical={false} />
          <XAxis
            dataKey="date"
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={{ stroke: "var(--grid)" }}
            interval={tickEvery - 1}
          />
          <YAxis
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            unit="h"
            width={44}
          />
          <Tooltip
            cursor={{ fill: "var(--surface-2)", opacity: 0.5 }}
            content={<ChartTip fmt={(v) => fmtHM(v * 3600)} />}
          />
          {keys.map((k) => {
            const { color, name } = keyColorName(k, categories, theme);
            return (
              <Bar
                key={k}
                dataKey={k}
                name={name}
                stackId="day"
                fill={color}
                // 2px surface gap between stacked segments (§4.3)
                stroke="var(--surface-1)"
                strokeWidth={1}
                maxBarSize={24}
              />
            );
          })}
        </BarChart>
      </ResponsiveContainer>
      <LegendRow keys={keys} categories={categories} theme={theme} />
    </div>
  );
}

/** Single-measure trend line (focus score / active hours). 2px line, crosshair tooltip. */
export function TrendLine({
  days,
  dataKey,
  color,
  unit,
  domain,
  fmt,
}: {
  days: { date: string; [k: string]: number | string | null }[];
  dataKey: string;
  color: string;
  unit?: string;
  domain?: [number, number];
  fmt: (v: number) => string;
}) {
  const tickEvery = Math.max(1, Math.ceil(days.length / 10));
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={days} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
        <CartesianGrid stroke="var(--grid)" strokeWidth={1} vertical={false} />
        <XAxis
          dataKey="date"
          tick={AXIS_TICK}
          tickLine={false}
          axisLine={{ stroke: "var(--grid)" }}
          interval={tickEvery - 1}
        />
        <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} unit={unit} domain={domain} width={44} />
        <Tooltip
          cursor={{ stroke: "var(--text-3)", strokeDasharray: "3 3" }}
          content={<ChartTip fmt={fmt} />}
        />
        <Line
          type="monotone"
          dataKey={dataKey}
          stroke={color}
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 5, stroke: "var(--surface-1)", strokeWidth: 2 }}
          connectNulls={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** >4 category series → small multiples, never spaghetti (§10.3). */
export function CategorySmallMultiples({
  days,
  categories,
  theme,
}: {
  days: RangeDay[];
  categories: Category[];
  theme: ThemeName;
}) {
  const keys = rangeCategoryKeys(days, categories);
  const maxH = Math.max(
    1,
    ...days.flatMap((d) => keys.map((k) => (d.category_totals[k] ?? 0) / 3600)),
  );
  const yMax = Math.ceil(maxH);
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {keys.map((k) => {
        const { color, name } = keyColorName(k, categories, theme);
        const data = days.map((d) => ({
          date: fmtDateShort(d.date),
          h: +((d.category_totals[k] ?? 0) / 3600).toFixed(2),
        }));
        return (
          <div key={k} className="rounded-[10px] border border-hairline p-2">
            <div className="mb-1 flex items-center gap-1.5 text-[12px] text-ink2">
              <Dot color={color} /> <span className="truncate">{name}</span>
            </div>
            <ResponsiveContainer width="100%" height={90}>
              <LineChart data={data} margin={{ top: 2, right: 2, left: 2, bottom: 0 }}>
                <YAxis hide domain={[0, yMax]} />
                <XAxis dataKey="date" hide />
                <Tooltip
                  cursor={{ stroke: "var(--text-3)", strokeDasharray: "3 3" }}
                  content={<ChartTip fmt={(v) => fmtHM(v * 3600)} />}
                />
                <Line type="monotone" dataKey="h" name={name} stroke={color} strokeWidth={2}
                      dot={false} activeDot={{ r: 4 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        );
      })}
    </div>
  );
}
