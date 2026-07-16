// Review (§10.5, Phase 7): queue of uncategorized + low-confidence spans,
// grouped by identity ("12 spans · notion.so · 1h 40m"). One-click assign per
// group, bulk select + assign, optional learned rule per assignment.
import { useMemo, useState } from "react";

import type { Category, ReviewGroup } from "../lib/api";
import { useAssignReview, useReviewQueue } from "../lib/api";
import { fmtHM } from "../lib/format";
import { STATUS, type ThemeName } from "../lib/palette";
import { CategoryPicker, Field } from "../components/pickers";
import { Card, Empty, IconButton } from "../components/ui";

const DAY_CHOICES = [7, 30, 90] as const;

export function Review({
  categories,
  theme,
}: {
  categories: Category[];
  theme: ThemeName;
}) {
  const [days, setDays] = useState<number>(30);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [cat, setCat] = useState<number | null>(null);
  const [learn, setLearn] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const queue = useReviewQueue(days);
  const assign = useAssignReview();
  const groups = queue.data?.groups ?? [];

  const selectedIds = useMemo(
    () =>
      groups
        .filter((g) => selected.has(g.key))
        .flatMap((g) => g.span_ids),
    [groups, selected],
  );

  const toggle = (key: string) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const doAssign = (spanIds: number[]) => {
    if (cat == null) {
      setErr("Pick a category first.");
      return;
    }
    setErr(null);
    assign.mutate(
      { span_ids: spanIds, category_id: cat, learn_rule: learn },
      {
        onSuccess: () => setSelected(new Set()),
        onError: (e) => setErr(String(e)),
      },
    );
  };

  return (
    <div className="mx-auto max-w-[1000px]">
      <header className="mb-5 flex items-center justify-between">
        <h1 className="font-display text-[24px] font-semibold text-ink1">
          Review
          <span className="ml-3 text-[15px] font-normal text-ink2">
            {queue.data ? `${queue.data.total_spans} spans need your eyes` : "…"}
          </span>
        </h1>
        <div className="flex items-center gap-2">
          {DAY_CHOICES.map((n) => (
            <IconButton
              key={n}
              label={`Last ${n} days`}
              active={days === n}
              onClick={() => setDays(n)}
            >
              {n}d
            </IconButton>
          ))}
        </div>
      </header>

      {queue.isLoading && <Empty>Scanning the queue…</Empty>}
      {queue.isError && (
        <Card><Empty>Could not reach Sanjaya at /api — is the tray app running?</Empty></Card>
      )}

      {queue.data && groups.length === 0 && (
        <Card>
          <div className="py-10 text-center">
            <div className="mb-2 text-[24px] text-accent">✓</div>
            <p className="text-[15px] text-ink1">Sanjaya sees all.</p>
            <p className="text-[13px] text-ink3">Nothing needs your eyes today.</p>
          </div>
        </Card>
      )}

      {groups.length > 0 && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_300px]">
          <div className="space-y-2">
            <div className="mb-1 flex items-center gap-3 px-1 text-[12px] text-ink3">
              <input
                type="checkbox"
                aria-label="Select all groups"
                checked={selected.size === groups.length && groups.length > 0}
                onChange={(e) =>
                  setSelected(e.target.checked ? new Set(groups.map((g) => g.key)) : new Set())
                }
              />
              Select all · {selected.size} of {groups.length} groups
            </div>
            {groups.map((g) => (
              <GroupRow
                key={g.key}
                g={g}
                checked={selected.has(g.key)}
                onToggle={() => toggle(g.key)}
                onAssign={() => doAssign(g.span_ids)}
                busy={assign.isPending}
                canAssign={cat != null}
              />
            ))}
          </div>

          <Card title="Assign" className="h-fit lg:sticky lg:top-6">
            <div className="space-y-3">
              <Field label="Category">
                <CategoryPicker categories={categories} value={cat} onChange={setCat} theme={theme} />
              </Field>
              <label className="flex items-center gap-2 text-[13px] text-ink2">
                <input
                  type="checkbox"
                  checked={learn}
                  onChange={(e) => setLearn(e.target.checked)}
                />
                Always classify like this
                <span className="text-[12px] text-ink3">(creates a rule)</span>
              </label>
              {err && (
                <p className="text-[12px]" style={{ color: STATUS.serious }}>⚠ {err}</p>
              )}
              <button
                type="button"
                onClick={() => doAssign(selectedIds)}
                disabled={assign.isPending || selectedIds.length === 0 || cat == null}
                className="w-full rounded-[10px] bg-accent px-3 py-2 text-[13px] font-medium text-surface1 transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {assign.isPending
                  ? "Assigning…"
                  : `Assign ${selectedIds.length} span${selectedIds.length === 1 ? "" : "s"}`}
              </button>
              <p className="text-[12px] leading-relaxed text-ink3">
                Pick a category, select groups on the left (or use a row's ↵
                button), and every span in them is classified as yours — with an
                optional rule so Sanjaya learns it forever.
              </p>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

function GroupRow({
  g,
  checked,
  onToggle,
  onAssign,
  busy,
  canAssign,
}: {
  g: ReviewGroup;
  checked: boolean;
  onToggle: () => void;
  onAssign: () => void;
  busy: boolean;
  canAssign: boolean;
}) {
  return (
    <Card className="!p-3">
      <div className="flex items-center gap-3">
        <input type="checkbox" checked={checked} onChange={onToggle}
               aria-label={`Select ${g.key}`} />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="truncate text-[15px] font-medium text-ink1">{g.key}</span>
            <span className="tnum shrink-0 text-[12px] text-ink3">
              {g.count} span{g.count === 1 ? "" : "s"} · {fmtHM(g.total_s)}
            </span>
          </div>
          {g.sample_titles.length > 0 && (
            <div className="truncate text-[12px] text-ink3">
              {g.sample_titles.join(" · ")}
            </div>
          )}
        </div>
        <IconButton
          label={`Assign ${g.key}`}
          title={canAssign ? "Assign this group to the picked category" : "Pick a category on the right first"}
          onClick={onAssign}
          disabled={busy || !canAssign}
        >
          ↵ Assign
        </IconButton>
      </div>
    </Card>
  );
}
