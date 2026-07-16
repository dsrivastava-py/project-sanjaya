// Timeline popover editor (§10.1, Phase 7): category color-dot select, project,
// free-text label, ✔ "always classify like this" (learned rule), delete, split
// at time. Idle/locked blocks can't be categorized — they route to "+ Add block"
// so a manual span re-tags the time instead.
import { useEffect, useRef, useState } from "react";

import type { Category, Span } from "../lib/api";
import { useDeleteSpan, useSplitSpan, useUpdateSpan } from "../lib/api";
import { fmtClock, fmtHM, wallToTs } from "../lib/format";
import { STATUS, type ThemeName } from "../lib/palette";
import { CategoryPicker, Field, inputCls, ProjectPicker } from "./pickers";
import { IconButton } from "./ui";

function detailLabel(s: Span): string {
  try {
    const d = s.detail ? (JSON.parse(s.detail) as Record<string, unknown>) : {};
    return d.label ? String(d.label) : "";
  } catch {
    return "";
  }
}

export function SpanEditor({
  span,
  categories,
  date,
  dayStart,
  dayStartHour,
  theme,
  onClose,
  onAddBlock,
}: {
  span: Span;
  categories: Category[];
  date: string;
  dayStart: number;
  dayStartHour: number;
  theme: ThemeName;
  onClose: () => void;
  onAddBlock: (startTs: number, endTs: number) => void;
}) {
  const update = useUpdateSpan(date, dayStart);
  const del = useDeleteSpan(date, dayStart);
  const split = useSplitSpan(date);

  const [cat, setCat] = useState<number | null>(span.category_id);
  const [proj, setProj] = useState<number | null>(span.project_id);
  const [label, setLabel] = useState(detailLabel(span));
  const [learn, setLearn] = useState(false);
  const [splitAt, setSplitAt] = useState(() =>
    fmtClock(Math.floor((span.start_ts + span.end_ts) / 2)),
  );
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
  }, [onClose]);

  const inactive = span.kind === "idle" || span.kind === "locked";
  const canLearn = !!(span.url || span.domain || span.exe);

  const save = () => {
    const patch: Parameters<typeof update.mutate>[0] = { id: span.id };
    if (cat !== span.category_id) patch.category_id = cat;
    if (proj !== span.project_id) patch.project_id = proj;
    if (label !== detailLabel(span)) patch.label = label || null;
    if (learn && cat != null) patch.learn_rule = true;
    if (Object.keys(patch).length === 1) return onClose(); // nothing changed
    update.mutate(patch, {
      onSuccess: onClose,
      onError: (e) => setErr(String(e)),
    });
  };

  const doSplit = () => {
    const at = wallToTs(date, splitAt, dayStartHour);
    if (at == null || at <= span.start_ts || at >= span.end_ts) {
      setErr("Split time must fall inside the span.");
      return;
    }
    split.mutate({ id: span.id, at_ts: at }, { onSuccess: onClose, onError: (e) => setErr(String(e)) });
  };

  const doDelete = () => {
    if (!window.confirm("Delete this span? Its time becomes untracked.")) return;
    del.mutate(span.id, { onSuccess: onClose, onError: (e) => setErr(String(e)) });
  };

  return (
    <div
      ref={ref}
      className="absolute z-20 w-[320px] rounded-2xl border border-hairline bg-surface1 p-4 shadow-xl"
      role="dialog"
      aria-label="Edit span"
    >
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="tnum text-[13px] text-ink2">
            {fmtClock(span.start_ts)}–{fmtClock(span.end_ts)} ·{" "}
            {fmtHM(span.end_ts - span.start_ts)}
          </div>
          <div className="truncate text-[13px] text-ink3">
            {span.kind}
            {span.domain || span.app_name || span.exe
              ? ` · ${span.domain || span.app_name || span.exe}`
              : ""}
          </div>
        </div>
        <IconButton label="Close" onClick={onClose}>✕</IconButton>
      </div>

      {inactive ? (
        <div className="space-y-3">
          <p className="text-[13px] text-ink2">
            {span.kind === "idle" ? "Idle" : "Locked"} time can’t be categorized.
            Add a manual block to re-tag it (class, gym, meetings…).
          </p>
          <button
            type="button"
            onClick={() => {
              onClose();
              onAddBlock(span.start_ts, span.end_ts);
            }}
            className="w-full rounded-[10px] border border-hairline px-3 py-2 text-[13px] text-ink1 hover:bg-surface2"
          >
            ＋ Add block over this time
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <Field label="Category">
            <CategoryPicker
              categories={categories}
              value={cat}
              onChange={(id) => {
                setCat(id);
                setProj(null);
              }}
              theme={theme}
              allowNone
            />
          </Field>
          <Field label="Project">
            <ProjectPicker categoryId={cat} value={proj} onChange={setProj} />
          </Field>
          <Field label="Label">
            <input
              className={inputCls}
              placeholder="Free-text label (optional)"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
          </Field>
          {canLearn && (
            <label className="flex items-center gap-2 text-[13px] text-ink2">
              <input
                type="checkbox"
                checked={learn}
                onChange={(e) => setLearn(e.target.checked)}
                disabled={cat == null}
              />
              Always classify like this
              <span className="text-[12px] text-ink3">(creates a rule)</span>
            </label>
          )}

          <div className="flex items-center gap-2 border-t border-hairline pt-3">
            <input
              className={`${inputCls} !w-[76px]`}
              value={splitAt}
              onChange={(e) => setSplitAt(e.target.value)}
              aria-label="Split time"
            />
            <IconButton label="Split span at time" onClick={doSplit} disabled={split.isPending}>
              ⑂ Split
            </IconButton>
            <span className="flex-1" />
            <IconButton label="Delete span" onClick={doDelete} disabled={del.isPending}>
              🗑 Delete
            </IconButton>
          </div>

          {err && (
            <p className="text-[12px]" style={{ color: STATUS.serious }}>
              ⚠ {err}
            </p>
          )}

          <button
            type="button"
            onClick={save}
            disabled={update.isPending}
            className="w-full rounded-[10px] bg-accent px-3 py-2 text-[13px] font-medium text-surface1 transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {update.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      )}
    </div>
  );
}
