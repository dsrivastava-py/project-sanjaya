// Goals (§10.4, Phase 8): goal cards grouped by period — progress meter vs
// target, streak + best streak, per-period history strip. Direction-aware
// STATUS coloring, always icon + label, never color alone (§4.3). CRUD modal:
// name, period, at_least/at_most, minutes, category/project, active days.
import { useEffect, useState } from "react";

import type { Category, GoalBody, GoalCard } from "../lib/api";
import { useCreateGoal, useDeleteGoal, useGoals, useUpdateGoal } from "../lib/api";
import { fmtHM } from "../lib/format";
import { keyColorName, NEUTRAL, STATUS, type ThemeName } from "../lib/palette";
import { CategoryPicker, Field, inputCls, ProjectPicker } from "../components/pickers";
import { Card, Dot, Empty, IconButton } from "../components/ui";

const PERIOD_ORDER: GoalCard["period"][] = ["daily", "weekly", "monthly", "yearly"];
const PERIOD_LABEL: Record<GoalCard["period"], string> = {
  daily: "Daily",
  weekly: "Weekly (Mon–Sun)",
  monthly: "Monthly",
  yearly: "Yearly",
};
const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function statusOf(status: GoalCard["status"], theme: ThemeName) {
  switch (status) {
    case "met":
      return { c: STATUS.good, icon: "✓", label: "Met" };
    case "missed":
      return { c: STATUS.serious, icon: "✕", label: "Missed" };
    case "skipped":
      return { c: NEUTRAL[theme], icon: "—", label: "Rest day" };
    default:
      return { c: STATUS.warning, icon: "…", label: "In progress" };
  }
}

export function Goals({
  categories,
  theme,
}: {
  categories: Category[];
  theme: ThemeName;
}) {
  const goals = useGoals();
  const del = useDeleteGoal();
  const [modal, setModal] = useState<{ goal: GoalCard | null } | null>(null);
  const cards = goals.data ?? [];

  return (
    <div className="mx-auto max-w-[1100px]">
      <header className="mb-5 flex items-center justify-between">
        <h1 className="font-display text-[24px] font-semibold text-ink1">
          Goals
          <span className="ml-3 text-[15px] font-normal text-ink2">
            targets, streaks, habits
          </span>
        </h1>
        <button
          type="button"
          onClick={() => setModal({ goal: null })}
          className="rounded-[10px] bg-accent px-3 py-1.5 text-[13px] font-medium text-surface1 transition-opacity hover:opacity-90"
        >
          ＋ New goal
        </button>
      </header>

      {goals.isLoading && <Empty>Loading goals…</Empty>}
      {goals.isError && (
        <Card><Empty>Could not reach Sanjaya at /api — is the tray app running?</Empty></Card>
      )}
      {goals.data && cards.length === 0 && (
        <Card>
          <Empty>
            No goals yet. Try “≥3h Placements daily” or “≤1.5h Entertainment daily” —
            Sanjaya keeps the score and the streak.
          </Empty>
        </Card>
      )}

      {PERIOD_ORDER.map((period) => {
        const group = cards.filter((g) => g.period === period);
        if (group.length === 0) return null;
        return (
          <section key={period} className="mb-6">
            <h2 className="mb-3 font-display text-[13px] font-medium uppercase tracking-[0.08em] text-ink3">
              {PERIOD_LABEL[period]}
            </h2>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {group.map((g) => (
                <GoalCardView
                  key={g.id}
                  g={g}
                  categories={categories}
                  theme={theme}
                  onEdit={() => setModal({ goal: g })}
                  onArchive={() => {
                    if (window.confirm(`Archive "${g.name}"? Its history is kept.`))
                      del.mutate(g.id);
                  }}
                />
              ))}
            </div>
          </section>
        );
      })}

      {modal && (
        <GoalModal
          goal={modal.goal}
          categories={categories}
          theme={theme}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
}

function GoalCardView({
  g,
  categories,
  theme,
  onEdit,
  onArchive,
}: {
  g: GoalCard;
  categories: Category[];
  theme: ThemeName;
  onEdit: () => void;
  onArchive: () => void;
}) {
  const st = statusOf(g.status, theme);
  const pct = Math.min(100, (g.minutes / Math.max(1, g.target_minutes)) * 100);
  const catColorName =
    g.category_id != null ? keyColorName(String(g.category_id), categories, theme) : null;
  return (
    <Card>
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[15px] font-medium text-ink1">
            {catColorName && <Dot color={catColorName.color} />}
            <span className="truncate">{g.name}</span>
          </div>
          <div className="mt-0.5 text-[12px] text-ink3">
            {g.direction === "at_least" ? "≥" : "≤"} {fmtHM(g.target_minutes * 60)}{" "}
            {g.period}
            {g.active_days &&
              ` · ${g.active_days.map((d) => DOW[d]).join(" ")}`}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <IconButton label={`Edit ${g.name}`} onClick={onEdit}>✎</IconButton>
          <IconButton label={`Archive ${g.name}`} onClick={onArchive}>🗑</IconButton>
        </div>
      </div>

      <div className="mb-1 flex items-center justify-between text-[12px]">
        <span className="tnum text-ink2">
          {fmtHM(g.minutes * 60)} of {fmtHM(g.target_minutes * 60)}{" "}
          {g.direction === "at_most" ? "cap" : "target"}
        </span>
        <span className="flex items-center gap-1" style={{ color: st.c }}>
          {st.icon} {st.label}
        </span>
      </div>
      <div className="h-2.5 w-full rounded-full bg-surface2/60">
        <div
          className="h-2.5 rounded-full"
          style={{ width: `${Math.max(2, pct)}%`, background: st.c }}
        />
      </div>

      <div className="tnum mt-3 flex items-center gap-4 text-[13px] text-ink2">
        <span title="Current streak">🔥 {g.streak.current}</span>
        <span className="text-ink3" title="Best streak since creation">
          best {g.streak.best}
        </span>
      </div>

      {g.history.length > 1 && <HistoryStrip g={g} theme={theme} />}
    </Card>
  );
}

function HistoryStrip({ g, theme }: { g: GoalCard; theme: ThemeName }) {
  return (
    <div className="mt-3">
      <div className="flex flex-wrap gap-[3px]">
        {g.history.map((h) => {
          const st = statusOf(h.status, theme);
          return (
            <span
              key={h.period_start}
              title={`${h.period_start}: ${st.label} (${fmtHM(h.minutes * 60)})`}
              className="h-[10px] w-[10px] rounded-[3px]"
              style={{
                background: h.status === "pending" ? "transparent" : st.c,
                border: h.status === "pending" ? `1.5px solid ${st.c}` : undefined,
                opacity: h.status === "skipped" ? 0.45 : 1,
              }}
            />
          );
        })}
      </div>
      <div className="mt-1.5 flex gap-3 text-[11px] text-ink3">
        <span style={{ color: STATUS.good }}>✓ met</span>
        <span style={{ color: STATUS.serious }}>✕ missed</span>
        <span>— rest</span>
        <span style={{ color: STATUS.warning }}>… pending</span>
      </div>
    </div>
  );
}

function GoalModal({
  goal,
  categories,
  theme,
  onClose,
}: {
  goal: GoalCard | null; // null = create
  categories: Category[];
  theme: ThemeName;
  onClose: () => void;
}) {
  const create = useCreateGoal();
  const update = useUpdateGoal();
  const [name, setName] = useState(goal?.name ?? "");
  const [period, setPeriod] = useState<GoalCard["period"]>(goal?.period ?? "daily");
  const [direction, setDirection] = useState<GoalCard["direction"]>(
    goal?.direction ?? "at_least",
  );
  const [target, setTarget] = useState(String(goal?.target_minutes ?? 60));
  const [byProject, setByProject] = useState(goal?.project_id != null);
  const [cat, setCat] = useState<number | null>(goal?.category_id ?? null);
  const [proj, setProj] = useState<number | null>(goal?.project_id ?? null);
  const [days, setDays] = useState<number[]>(goal?.active_days ?? [0, 1, 2, 3, 4, 5, 6]);
  const [err, setErr] = useState<string | null>(null);
  const busy = create.isPending || update.isPending;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const toggleDay = (d: number) =>
    setDays((cur) => (cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d].sort()));

  const save = () => {
    const t = Number(target);
    if (!name.trim()) return setErr("Give the goal a name.");
    if (!Number.isFinite(t) || t < 0) return setErr("Target must be minutes (a number).");
    if (byProject && proj == null) return setErr("Pick a project (or track a category).");
    if (!byProject && cat == null) return setErr("Pick a category (or track a project).");
    if (period === "daily" && days.length === 0)
      return setErr("A daily goal needs at least one active day.");
    const body: GoalBody = {
      name: name.trim(),
      period,
      direction,
      target_minutes: Math.round(t),
      category_id: byProject ? null : cat,
      project_id: byProject ? proj : null,
      active_days: period === "daily" && days.length < 7 ? days : null,
    };
    const opts = { onSuccess: onClose, onError: (e: Error) => setErr(String(e)) };
    if (goal) update.mutate({ id: goal.id, ...body }, opts);
    else create.mutate(body, opts);
  };

  return (
    <div
      className="fixed inset-0 z-30 grid place-items-center bg-black/40 p-4"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className="max-h-[90vh] w-full max-w-[440px] overflow-auto rounded-2xl border border-hairline bg-surface1 p-5 shadow-xl"
        role="dialog"
        aria-label={goal ? "Edit goal" : "New goal"}
      >
        <header className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-[15px] font-semibold text-ink1">
            {goal ? "Edit goal" : "New goal"}
          </h2>
          <IconButton label="Close" onClick={onClose}>✕</IconButton>
        </header>
        <div className="space-y-3">
          <Field label="Name">
            <input
              autoFocus
              className={inputCls}
              placeholder="e.g. ≥3h Placements"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Period">
              <select
                className={inputCls}
                value={period}
                onChange={(e) => setPeriod(e.target.value as GoalCard["period"])}
              >
                {PERIOD_ORDER.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </Field>
            <Field label="Direction">
              <select
                className={inputCls}
                value={direction}
                onChange={(e) => setDirection(e.target.value as GoalCard["direction"])}
              >
                <option value="at_least">at least (≥)</option>
                <option value="at_most">at most (≤ cap)</option>
              </select>
            </Field>
          </div>
          <Field label="Target (minutes)">
            <div className="flex items-center gap-2">
              <input
                className={`${inputCls} !w-[110px]`}
                inputMode="numeric"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              />
              <span className="tnum text-[12px] text-ink3">
                = {fmtHM(Math.max(0, Number(target) || 0) * 60)}
              </span>
            </div>
          </Field>

          <Field label="Track">
            <div className="mb-2 flex gap-2">
              <IconButton label="Track a category" active={!byProject}
                          onClick={() => setByProject(false)}>
                Category
              </IconButton>
              <IconButton label="Track a project" active={byProject}
                          onClick={() => setByProject(true)}>
                Project
              </IconButton>
            </div>
            <CategoryPicker categories={categories} value={cat}
                            onChange={(id) => { setCat(id); setProj(null); }} theme={theme} />
            {byProject && (
              <div className="mt-2">
                <ProjectPicker categoryId={cat} value={proj} onChange={setProj} />
              </div>
            )}
          </Field>

          {period === "daily" && (
            <Field label="Active days">
              <div className="flex gap-1.5">
                {DOW.map((label, i) => (
                  <button
                    key={label}
                    type="button"
                    onClick={() => toggleDay(i)}
                    className={`rounded-[8px] border px-2 py-1 text-[12px] transition-colors duration-150 ${
                      days.includes(i)
                        ? "border-accent bg-surface2 text-ink1"
                        : "border-hairline text-ink3 hover:bg-surface2/60"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <p className="mt-1 text-[12px] text-ink3">
                Off days are rest days — they never break a streak.
              </p>
            </Field>
          )}

          {err && (
            <p className="text-[12px]" style={{ color: STATUS.serious }}>⚠ {err}</p>
          )}
          <button
            type="button"
            onClick={save}
            disabled={busy}
            className="w-full rounded-[10px] bg-accent px-3 py-2 text-[13px] font-medium text-surface1 transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {busy ? "Saving…" : goal ? "Save changes" : "Create goal"}
          </button>
        </div>
      </div>
    </div>
  );
}
