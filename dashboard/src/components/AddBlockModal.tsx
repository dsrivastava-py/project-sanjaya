// "+ Add block" modal (§10.1, Phase 7): manual span (kind='manual') for offline
// work — class, gym, meetings. Wall-clock times; hours before day_start_hour
// belong to the logical day's small hours (§13.8). Manual spans MAY overlap
// idle/locked time and re-tag it.
import { useEffect, useState } from "react";

import type { Category } from "../lib/api";
import { useCreateSpan } from "../lib/api";
import { fmtClock, fmtDateLong, wallToTs } from "../lib/format";
import { STATUS, type ThemeName } from "../lib/palette";
import { CategoryPicker, Field, inputCls, ProjectPicker } from "./pickers";
import { IconButton } from "./ui";

export function AddBlockModal({
  date,
  dayStartHour,
  categories,
  theme,
  prefill,
  onClose,
}: {
  date: string;
  dayStartHour: number;
  categories: Category[];
  theme: ThemeName;
  prefill?: { startTs: number; endTs: number } | null;
  onClose: () => void;
}) {
  const create = useCreateSpan(date);
  const [start, setStart] = useState(prefill ? fmtClock(prefill.startTs) : "09:00");
  const [end, setEnd] = useState(prefill ? fmtClock(prefill.endTs) : "10:00");
  const [cat, setCat] = useState<number | null>(null);
  const [proj, setProj] = useState<number | null>(null);
  const [label, setLabel] = useState("");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const save = () => {
    const a = wallToTs(date, start, dayStartHour);
    const b = wallToTs(date, end, dayStartHour);
    if (a == null || b == null) return setErr("Times must be HH:MM.");
    if (b <= a) return setErr("End must be after start (within this logical day).");
    if (cat == null) return setErr("Pick a category — that's the point of the block.");
    create.mutate(
      { start_ts: a, end_ts: b, category_id: cat, project_id: proj, label: label || null },
      { onSuccess: onClose, onError: (e) => setErr(String(e)) },
    );
  };

  return (
    <div
      className="fixed inset-0 z-30 grid place-items-center bg-black/40 p-4"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className="w-full max-w-[420px] rounded-2xl border border-hairline bg-surface1 p-5 shadow-xl"
        role="dialog"
        aria-label="Add manual block"
      >
        <header className="mb-4 flex items-center justify-between">
          <h2 className="font-display text-[15px] font-semibold text-ink1">Add block</h2>
          <IconButton label="Close" onClick={onClose}>✕</IconButton>
        </header>
        <p className="mb-3 text-[13px] text-ink3">
          {fmtDateLong(date)} — offline work (class, gym, meetings). Overlapping
          idle time is re-tagged, not double-counted.
        </p>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="From">
              <input className={inputCls} value={start} onChange={(e) => setStart(e.target.value)} />
            </Field>
            <Field label="To">
              <input className={inputCls} value={end} onChange={(e) => setEnd(e.target.value)} />
            </Field>
          </div>
          <Field label="Category">
            <CategoryPicker categories={categories} value={cat} onChange={(id) => { setCat(id); setProj(null); }} theme={theme} />
          </Field>
          <Field label="Project">
            <ProjectPicker categoryId={cat} value={proj} onChange={setProj} />
          </Field>
          <Field label="Label">
            <input
              className={inputCls}
              placeholder="e.g. DBMS lecture, gym, client call"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
          </Field>
          {err && (
            <p className="text-[12px]" style={{ color: STATUS.serious }}>⚠ {err}</p>
          )}
          <button
            type="button"
            onClick={save}
            disabled={create.isPending}
            className="w-full rounded-[10px] bg-accent px-3 py-2 text-[13px] font-medium text-surface1 transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {create.isPending ? "Adding…" : "Add block"}
          </button>
        </div>
      </div>
    </div>
  );
}
