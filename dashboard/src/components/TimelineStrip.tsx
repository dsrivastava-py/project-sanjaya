// DAY TIMELINE (§10.1): horizontal 00–24h strip; span blocks colored by
// category slot with 2px surface gaps; idle/locked neutral (never a colored
// category); hover tooltip layer; click block → edit popover (Phase 7).
// Manual blocks render last so they sit on top of the idle time they re-tag.
import { useMemo, useState } from "react";

import type { Category, Span } from "../lib/api";
import { fmtClock, fmtHM } from "../lib/format";
import { catColor, IDLE, NEUTRAL, type ThemeName } from "../lib/palette";
import { SpanEditor } from "./SpanEditor";

interface TipState {
  x: number;
  y: number;
  span: Span;
}

function spanTitle(s: Span): string | null {
  try {
    const d = s.detail ? (JSON.parse(s.detail) as Record<string, unknown>) : {};
    const cand =
      (d.label as string) || // user's free-text label wins (Phase 7)
      (d.video_title as string) ||
      (d.topic as string) ||
      (d.query as string) ||
      (d.file as string) ||
      (d.page_title as string);
    if (cand) return String(cand);
  } catch {
    /* raw detail — fall through to window title */
  }
  return s.window_title || null;
}

export function TimelineStrip({
  spans,
  categories,
  dayStart,
  theme,
  date,
  dayStartHour = 4,
  onAddBlock,
}: {
  spans: Span[];
  categories: Category[];
  dayStart: number; // UTC epoch seconds where this local day begins
  theme: ThemeName;
  date?: string | null; // set (with onAddBlock) to enable click-to-edit
  dayStartHour?: number;
  onAddBlock?: (startTs: number, endTs: number) => void;
}) {
  const [tip, setTip] = useState<TipState | null>(null);
  const [editing, setEditing] = useState<{ span: Span; xPct: number } | null>(null);
  const DAY = 86400;
  const editable = !!date && !!onAddBlock;
  const catById = useMemo(
    () => new Map(categories.map((c) => [c.id, c])),
    [categories],
  );

  const blocks = useMemo(
    () =>
      spans
        .map((s) => {
          const a = Math.max(s.start_ts, dayStart);
          const b = Math.min(s.end_ts, dayStart + DAY);
          return { s, left: ((a - dayStart) / DAY) * 100, width: ((b - a) / DAY) * 100 };
        })
        .filter((b) => b.width > 0)
        // manual spans re-tag idle/locked time (§10.1): paint them last = on top
        .sort((a, b) => Number(a.s.kind === "manual") - Number(b.s.kind === "manual")),
    [spans, dayStart],
  );

  const colorOf = (s: Span): string => {
    if (s.kind === "idle" || s.kind === "locked") return IDLE[theme];
    if (s.category_id == null) return NEUTRAL[theme];
    return catColor(catById.get(s.category_id), theme);
  };

  return (
    <div className="relative">
      <div
        className="relative h-16 w-full overflow-hidden rounded-[10px] border border-hairline bg-surface2/40"
        onMouseLeave={() => setTip(null)}
      >
        {blocks.map(({ s, left, width }) => (
          <div
            key={s.id}
            className={`absolute top-[6px] bottom-[6px] rounded-[3px] transition-opacity duration-150 hover:opacity-80 ${
              editable ? "cursor-pointer" : ""
            }`}
            style={{
              left: `${left}%`,
              // 2px surface gap between adjacent blocks (§4.3)
              width: `calc(${width}% - 2px)`,
              minWidth: "2px",
              background: colorOf(s),
              opacity: s.kind === "idle" || s.kind === "locked" ? 0.9 : 1,
            }}
            onMouseMove={(e) => {
              const host = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect();
              setTip({ x: e.clientX - host.left, y: e.clientY - host.top, span: s });
            }}
            onClick={() => {
              if (!editable) return;
              setTip(null);
              setEditing({ span: s, xPct: left + width / 2 });
            }}
          />
        ))}
        {tip && !editing && <TimelineTip tip={tip} catById={catById} theme={theme} />}
      </div>
      <div className="tnum mt-1 flex justify-between text-[12px] text-ink3">
        {/* wall-clock labels: the strip runs day_start_hour → +24h (§13.8) */}
        {[0, 4, 8, 12, 16, 20, 24].map((k) => {
          const wall = (new Date(dayStart * 1000).getHours() + k) % 24;
          return <span key={k}>{String(wall).padStart(2, "0")}</span>;
        })}
      </div>
      {editing && date && onAddBlock && (
        <div
          className="absolute top-[72px]"
          style={{
            left: `max(0px, min(calc(${editing.xPct}% - 160px), calc(100% - 320px)))`,
          }}
        >
          <SpanEditor
            span={editing.span}
            categories={categories}
            date={date}
            dayStart={dayStart}
            dayStartHour={dayStartHour}
            theme={theme}
            onClose={() => setEditing(null)}
            onAddBlock={onAddBlock}
          />
        </div>
      )}
    </div>
  );
}

function TimelineTip({
  tip,
  catById,
  theme,
}: {
  tip: TipState;
  catById: Map<number, Category>;
  theme: ThemeName;
}) {
  const s = tip.span;
  const inactive = s.kind === "idle" || s.kind === "locked";
  const cat = s.category_id != null ? catById.get(s.category_id) : undefined;
  const name = inactive ? (s.kind === "idle" ? "Idle" : "Locked") : cat?.name ?? "Uncategorized";
  const color = inactive ? IDLE[theme] : cat ? catColor(cat, theme) : NEUTRAL[theme];
  const title = inactive ? null : spanTitle(s);
  const label = s.domain || s.app_name || s.exe;
  return (
    <div
      className="pointer-events-none absolute z-10 max-w-[300px] rounded-[10px] border border-hairline bg-surface2 px-3 py-2 text-[13px] shadow-lg"
      style={{
        left: tip.x,
        top: tip.y + 14,
        transform: tip.x > 500 ? "translateX(-100%)" : undefined,
      }}
    >
      <div className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />
        <span className="font-medium text-ink1">{name}</span>
        {s.kind === "manual" && <span className="text-[11px] text-ink3">manual</span>}
        {s.edited === 1 && <span className="text-[11px] text-ink3">edited</span>}
      </div>
      <div className="tnum mt-0.5 text-ink2">
        {fmtClock(s.start_ts)}–{fmtClock(s.end_ts)} · {fmtHM(s.end_ts - s.start_ts)}
      </div>
      {label && !inactive && <div className="mt-0.5 truncate text-ink3">{label}</div>}
      {title && <div className="mt-0.5 line-clamp-2 text-ink2">{title}</div>}
    </div>
  );
}
