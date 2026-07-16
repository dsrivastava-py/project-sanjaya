// Today — the default bento grid (§10.1): hero focus dial + AI day title,
// active-time + top-category tiles, 00–24h timeline (click block → edit
// popover, "+ Add block" manual spans), category mix, journal with inline
// edit + note, editable highlights, goals today with streak flames.
import { useState } from "react";

import type { Category, DayData, GoalToday } from "../lib/api";
import { useDay, useRegenerateSummary, useUpdateSummary } from "../lib/api";
import { dayStartTs, fmtDateLong, fmtHM, fmtHMS } from "../lib/format";
import { keyColorName, NEUTRAL, STATUS, type ThemeName } from "../lib/palette";
import { AddBlockModal } from "../components/AddBlockModal";
import { ChartCard, DataTable } from "../components/ChartCard";
import { FocusDial } from "../components/FocusDial";
import { Markdown } from "../components/Markdown";
import { MixBars } from "../components/MixBars";
import { TimelineStrip } from "../components/TimelineStrip";
import { AiChip, Card, Dot, EditedChip, Empty, IconButton } from "../components/ui";
import { fmtClock } from "../lib/format";

const textareaCls =
  "w-full min-h-[140px] rounded-[10px] border border-hairline bg-surface2/60 " +
  "p-3 text-[14px] leading-relaxed text-ink1 outline-none focus:border-accent";

export function Today({
  date,
  today,
  dayStartHour,
  shiftDay,
  categories,
  theme,
}: {
  date: string | null;
  today: string | null;
  dayStartHour: number;
  shiftDay: (n: number) => void;
  categories: Category[];
  theme: ThemeName;
}) {
  const day = useDay(date);
  const d = day.data;
  const [addBlock, setAddBlock] = useState<
    { prefill: { startTs: number; endTs: number } | null } | null
  >(null);

  return (
    <div className="mx-auto max-w-[1200px]">
      <header className="mb-5 flex items-center justify-between">
        <h1 className="font-display text-[24px] font-semibold text-ink1">
          {date === today ? "Today" : "Day view"}
          <span className="ml-3 text-[15px] font-normal text-ink2">
            {date ? fmtDateLong(date) : "…"}
          </span>
        </h1>
        <div className="flex items-center gap-2">
          <IconButton label="Previous day" onClick={() => shiftDay(-1)}>←</IconButton>
          <IconButton
            label="Next day"
            onClick={() => shiftDay(1)}
            disabled={!date || !today || date >= today}
          >
            →
          </IconButton>
        </div>
      </header>

      {day.isLoading && <Empty>Loading the day…</Empty>}
      {day.isError && (
        <Card><Empty>Could not reach Sanjaya at /api — is the tray app running?</Empty></Card>
      )}

      {d && date && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {/* HERO row */}
          <Card className="md:col-span-1">
            <div className="flex items-center gap-5">
              <FocusDial score={d.active_seconds > 0 ? d.focus_score : null} />
              <div className="min-w-0">
                <DayTitle d={d} />
              </div>
            </div>
          </Card>
          <StatTile label="Active time" value={fmtHM(d.active_seconds)}
                    sub={`${fmtHM(d.idle_seconds)} idle`} />
          <TopCategoryTile d={d} categories={categories} theme={theme} />

          {/* TIMELINE full width */}
          <ChartCard
            title="Day timeline"
            className="md:col-span-3"
            actions={
              <IconButton
                label="Add manual block"
                title="Add a manual block for offline work (class, gym, meetings)"
                onClick={() => setAddBlock({ prefill: null })}
              >
                ＋ Add block
              </IconButton>
            }
            table={{
              columns: ["From", "To", "Kind", "Category", "App / domain", "Duration"],
              rows: d.spans.map((s) => [
                fmtClock(s.start_ts),
                fmtClock(s.end_ts),
                s.kind,
                s.kind === "idle" || s.kind === "locked"
                  ? "—"
                  : keyColorName(String(s.category_id ?? "uncategorized"), categories, theme).name,
                s.domain || s.app_name || s.exe || "—",
                fmtHM(s.end_ts - s.start_ts),
              ]),
            }}
          >
            <TimelineStrip
              spans={d.spans}
              categories={categories}
              dayStart={dayStartTs(date, dayStartHour)}
              theme={theme}
              date={date}
              dayStartHour={dayStartHour}
              onAddBlock={(startTs, endTs) => setAddBlock({ prefill: { startTs, endTs } })}
            />
          </ChartCard>

          {/* MIX + JOURNAL */}
          <ChartCard
            title="Category mix"
            className="md:col-span-1"
            table={{
              columns: ["Category", "Time"],
              rows: Object.entries(d.category_totals)
                .sort((a, b) => b[1] - a[1])
                .map(([k, v]) => [keyColorName(k, categories, theme).name, fmtHM(v)]),
            }}
          >
            <MixBars totals={d.category_totals} categories={categories} theme={theme} />
          </ChartCard>
          <Journal d={d} date={date} />

          {/* HIGHLIGHTS + GOALS */}
          <Highlights d={d} date={date} />
          <GoalsToday goals={d.goals} categories={categories} theme={theme} />
        </div>
      )}

      {addBlock && date && (
        <AddBlockModal
          date={date}
          dayStartHour={dayStartHour}
          categories={categories}
          theme={theme}
          prefill={addBlock.prefill}
          onClose={() => setAddBlock(null)}
        />
      )}
    </div>
  );
}

function DayTitle({ d }: { d: DayData }) {
  const s = d.summary;
  const title =
    s.exists && s.narrative_md
      ? firstSentence(s.narrative_md)
      : d.active_seconds > 0
        ? "Journal not written yet — regenerate below."
        : "A quiet day so far. Sanjaya is watching.";
  return (
    <div>
      <p className="line-clamp-4 text-[15px] leading-relaxed text-ink2">{title}</p>
      {s.exists && s.narrative_md && (
        <div className="mt-2"><AiChip /></div>
      )}
    </div>
  );
}

function firstSentence(md: string): string {
  const plain = md.replace(/[#*_`>]/g, "").trim();
  const m = /^(.*?[.!?])(\s|$)/.exec(plain);
  return (m ? m[1] : plain).slice(0, 160);
}

function StatTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card>
      <div className="flex h-full flex-col justify-center">
        <span className="text-[13px] uppercase tracking-[0.08em] text-ink3">{label}</span>
        <span className="tnum mt-2 font-display text-[32px] font-semibold text-ink1">{value}</span>
        {sub && <span className="tnum mt-1 text-[13px] text-ink3">{sub}</span>}
      </div>
    </Card>
  );
}

function TopCategoryTile({
  d,
  categories,
  theme,
}: {
  d: DayData;
  categories: Category[];
  theme: ThemeName;
}) {
  const top = Object.entries(d.category_totals).sort((a, b) => b[1] - a[1])[0];
  if (!top)
    return (
      <Card>
        <div className="flex h-full flex-col justify-center">
          <span className="text-[13px] uppercase tracking-[0.08em] text-ink3">Top category</span>
          <span className="mt-2 text-[15px] text-ink3">No activity yet</span>
        </div>
      </Card>
    );
  const { color, name } = keyColorName(top[0], categories, theme);
  return (
    <Card>
      <div className="flex h-full flex-col justify-center">
        <span className="text-[13px] uppercase tracking-[0.08em] text-ink3">Top category</span>
        <span className="mt-2 flex items-center gap-2 font-display text-[24px] font-semibold text-ink1">
          <Dot color={color} /> <span className="truncate">{name}</span>
        </span>
        <span className="tnum mt-1 text-[13px] text-ink3">{fmtHM(top[1])}</span>
      </div>
    </Card>
  );
}

function Journal({ d, date }: { d: DayData; date: string }) {
  const regen = useRegenerateSummary(date);
  const save = useUpdateSummary(date);
  const [mode, setMode] = useState<null | "narrative" | "note">(null);
  const [draft, setDraft] = useState("");
  const s = d.summary;

  const startEdit = (m: "narrative" | "note") => {
    setDraft((m === "narrative" ? s.narrative_md : s.user_note_md) ?? "");
    setMode(m);
  };
  const commit = () => {
    save.mutate(
      mode === "narrative" ? { narrative_md: draft } : { user_note_md: draft },
      { onSuccess: () => setMode(null) },
    );
  };

  return (
    <Card
      title="Journal"
      className="md:col-span-2"
      actions={
        <>
          {s.exists && s.narrative_md && !s.edited && <AiChip />}
          {s.edited && <EditedChip />}
          <IconButton
            label="Edit journal"
            disabled={!s.exists || !!mode}
            title={s.exists ? "Edit the narrative (markdown)" : "No journal yet to edit"}
            onClick={() => startEdit("narrative")}
          >
            ✎ Edit
          </IconButton>
          <IconButton
            label="Regenerate journal"
            title="Regenerate will overwrite the narrative (your note is kept)"
            onClick={() => {
              if (window.confirm("Regenerate the journal? This overwrites the current narrative (your added note is kept)."))
                regen.mutate();
            }}
            disabled={regen.isPending || !!mode}
          >
            {regen.isPending ? "Writing…" : "↻ Regenerate"}
          </IconButton>
          <IconButton
            label="Add note"
            disabled={!s.exists || !!mode}
            title={s.exists ? "Add your own note below the narrative" : "Notes attach to a written journal"}
            onClick={() => startEdit("note")}
          >
            + Note
          </IconButton>
        </>
      }
    >
      {regen.isError && (
        <p className="mb-2 rounded-[10px] border border-hairline bg-surface2 px-3 py-2 text-[13px]"
           style={{ color: STATUS.serious }}>
          ⚠ AI unavailable — deterministic data stays visible; the journal will come back with connectivity.
        </p>
      )}
      {mode ? (
        <div>
          <span className="mb-1 block text-[12px] uppercase tracking-[0.08em] text-ink3">
            {mode === "narrative" ? "Narrative (markdown)" : "Your note (markdown)"}
          </span>
          <textarea
            autoFocus
            className={textareaCls}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="mt-2 flex items-center justify-end gap-2">
            {save.isError && (
              <span className="mr-auto text-[12px]" style={{ color: STATUS.serious }}>
                ⚠ Save failed — try again.
              </span>
            )}
            <IconButton label="Cancel edit" onClick={() => setMode(null)}>Cancel</IconButton>
            <button
              type="button"
              onClick={commit}
              disabled={save.isPending}
              className="rounded-[10px] bg-accent px-3 py-1 text-[12px] font-medium text-surface1 hover:opacity-90 disabled:opacity-50"
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      ) : s.exists && s.narrative_md ? (
        <>
          <Markdown text={s.narrative_md} />
          {s.user_note_md && (
            <div className="mt-3 border-t border-hairline pt-3">
              <span className="text-[12px] uppercase tracking-[0.08em] text-ink3">Your note</span>
              <Markdown text={s.user_note_md} />
            </div>
          )}
        </>
      ) : (
        <Empty>
          No journal yet for this day.
          {d.active_seconds > 0 ? " Hit Regenerate to have Sanjaya write it." : " Nothing was tracked."}
        </Empty>
      )}
    </Card>
  );
}

function Highlights({ d, date }: { d: DayData; date: string }) {
  const save = useUpdateSummary(date);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const hl = d.summary.highlights ?? [];

  const commit = () => {
    const items = draft.split("\n").map((l) => l.replace(/^[-*✦]\s*/, "").trim()).filter(Boolean);
    save.mutate({ highlights: items }, { onSuccess: () => setEditing(false) });
  };

  return (
    <Card
      title="Highlights"
      className="md:col-span-2"
      actions={
        d.summary.exists && (
          <IconButton
            label="Edit highlights"
            disabled={editing}
            title="Edit highlights — one per line"
            onClick={() => {
              setDraft(hl.join("\n"));
              setEditing(true);
            }}
          >
            ✎ Edit
          </IconButton>
        )
      }
    >
      {editing ? (
        <div>
          <textarea
            autoFocus
            className={textareaCls}
            placeholder="One highlight per line"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="mt-2 flex items-center justify-end gap-2">
            <IconButton label="Cancel edit" onClick={() => setEditing(false)}>Cancel</IconButton>
            <button
              type="button"
              onClick={commit}
              disabled={save.isPending}
              className="rounded-[10px] bg-accent px-3 py-1 text-[12px] font-medium text-surface1 hover:opacity-90 disabled:opacity-50"
            >
              {save.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      ) : hl.length === 0 && d.stopwatch.length === 0 ? (
        <Empty>Highlights appear once the journal is written.</Empty>
      ) : (
        <>
          <ul className="space-y-2">
            {hl.map((h, i) => (
              <li key={i} className="flex items-start gap-2 text-[15px] text-ink1">
                <span className="mt-0.5 text-accent">✦</span> {h}
              </li>
            ))}
          </ul>
          {d.stopwatch.length > 0 && (
            <div className="mt-4 border-t border-hairline pt-3">
              <span className="text-[12px] uppercase tracking-[0.08em] text-ink3">
                Stopwatch readings
              </span>
              <DataTable
                spec={{
                  columns: ["Time", "Label", "Reading", "Event"],
                  rows: d.stopwatch.map((r) => [
                    fmtClock(r.ts),
                    r.label || r.source,
                    fmtHMS(r.last_value_s),
                    r.event,
                  ]),
                }}
              />
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function GoalsToday({
  goals,
  categories,
  theme,
}: {
  goals: GoalToday[];
  categories: Category[];
  theme: ThemeName;
}) {
  return (
    <Card title="Goals today" className="md:col-span-1">
      {goals.length === 0 ? (
        <Empty>No goals yet — create one on the Goals page (g).</Empty>
      ) : (
        <ul className="space-y-4">
          {goals.map((g) => {
            const pct = Math.min(100, (g.minutes / Math.max(1, g.target_minutes)) * 100);
            const over = g.direction === "at_most" && g.minutes > g.target_minutes;
            // status colors: icon + label, never color alone (§4.3)
            const st = !g.active_today
              ? { c: NEUTRAL[theme], icon: "—", label: "Rest day" }
              : g.met
                ? { c: STATUS.good, icon: "✓", label: "Met" }
                : over
                  ? { c: STATUS.serious, icon: "✕", label: "Over" }
                  : { c: STATUS.warning, icon: "…", label: "In progress" };
            const catColorName = g.category_id != null
              ? keyColorName(String(g.category_id), categories, theme)
              : null;
            return (
              <li key={g.id}>
                <div className="mb-1 flex items-center justify-between text-[13px]">
                  <span className="flex items-center gap-2 text-ink1">
                    {catColorName && <Dot color={catColorName.color} />}
                    {g.name}
                    {g.streak > 0 && (
                      <span
                        className="tnum text-[12px] text-ink2"
                        title={`Streak ${g.streak} — best ${g.best_streak}`}
                      >
                        🔥{g.streak}
                      </span>
                    )}
                  </span>
                  <span className="flex items-center gap-1 text-[12px]" style={{ color: st.c }}>
                    {st.icon} {st.label}
                  </span>
                </div>
                <div className="h-2.5 w-full rounded-full bg-surface2/60">
                  <div
                    className="h-2.5 rounded-full"
                    style={{ width: `${Math.max(2, pct)}%`, background: st.c }}
                  />
                </div>
                <div className="tnum mt-1 text-[12px] text-ink3">
                  {fmtHM(g.minutes * 60)} of {fmtHM(g.target_minutes * 60)}{" "}
                  {g.direction === "at_most" ? "cap" : "target"}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
