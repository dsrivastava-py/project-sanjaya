// Shared form atoms for the editing surfaces (Phase 7/8): category chip grid
// (color follows the category ENTITY via its slot, §4.3), project select with
// inline quick-create, and a labeled field wrapper.
import { useState } from "react";
import type { ReactNode } from "react";

import type { Category } from "../lib/api";
import { useCreateProject, useProjects } from "../lib/api";
import { catColor, NEUTRAL, type ThemeName } from "../lib/palette";
import { Dot } from "./ui";

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[12px] uppercase tracking-[0.08em] text-ink3">
        {label}
      </span>
      {children}
    </label>
  );
}

export const inputCls =
  "w-full rounded-[10px] border border-hairline bg-surface2/60 px-2.5 py-1.5 " +
  "text-[14px] text-ink1 outline-none focus:border-accent";

export function CategoryPicker({
  categories,
  value,
  onChange,
  theme,
  allowNone = false,
}: {
  categories: Category[];
  value: number | null;
  onChange: (id: number | null) => void;
  theme: ThemeName;
  allowNone?: boolean;
}) {
  const opts: { id: number | null; name: string; color: string }[] = categories
    .filter((c) => !c.archived)
    .map((c) => ({ id: c.id, name: c.name, color: catColor(c, theme) }));
  if (allowNone) opts.push({ id: null, name: "Uncategorized", color: NEUTRAL[theme] });
  return (
    <div className="grid grid-cols-2 gap-1.5">
      {opts.map((o) => (
        <button
          key={o.id ?? "none"}
          type="button"
          onClick={() => onChange(o.id)}
          className={`flex items-center gap-2 rounded-[10px] border px-2 py-1.5 text-left text-[13px] transition-colors duration-150 ${
            value === o.id
              ? "border-accent bg-surface2 text-ink1"
              : "border-hairline text-ink2 hover:bg-surface2/60"
          }`}
        >
          <Dot color={o.color} />
          <span className="truncate">{o.name}</span>
        </button>
      ))}
    </div>
  );
}

export function ProjectPicker({
  categoryId,
  value,
  onChange,
}: {
  categoryId: number | null;
  value: number | null;
  onChange: (id: number | null) => void;
}) {
  const projects = useProjects();
  const create = useCreateProject();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const options = (projects.data ?? []).filter(
    (p) => !p.archived && (categoryId == null || p.category_id === categoryId),
  );

  const submitNew = () => {
    const n = name.trim();
    if (!n || categoryId == null) return;
    create.mutate(
      { name: n, category_id: categoryId },
      {
        onSuccess: (res) => {
          onChange(res.project.id);
          setAdding(false);
          setName("");
        },
      },
    );
  };

  // no category context → offer every project (quick-create needs a category)
  return (
    <div className="flex items-center gap-2">
      {adding ? (
        <>
          <input
            autoFocus
            className={inputCls}
            placeholder="New project name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submitNew();
              if (e.key === "Escape") setAdding(false);
            }}
          />
          <button
            type="button"
            onClick={submitNew}
            disabled={create.isPending}
            className="rounded-[10px] border border-hairline px-2 py-1.5 text-[12px] text-ink2 hover:bg-surface2"
          >
            Add
          </button>
        </>
      ) : (
        <>
          <select
            className={inputCls}
            value={value ?? ""}
            onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
          >
            <option value="">No project</option>
            {options.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          {categoryId != null && (
            <button
              type="button"
              onClick={() => setAdding(true)}
              title="New project in this category"
              className="shrink-0 rounded-[10px] border border-hairline px-2 py-1.5 text-[12px] text-ink2 hover:bg-surface2"
            >
              + New
            </button>
          )}
        </>
      )}
    </div>
  );
}
