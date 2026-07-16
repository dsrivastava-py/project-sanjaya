// Settings (§10.6, Phase 9): categories & projects manager, rules table,
// privacy (exclude lists / redaction / retention / debug toggle), AI config +
// test connection, data export, about/health. Entity color via slot; STATUS
// always icon + label (§4.3).
import { useState } from "react";
import type { ReactNode } from "react";

import type { Category, Settings as SettingsData } from "../lib/api";
import {
  exportUrl,
  useCategories,
  useCreateCategory,
  useDeleteRule,
  useProjects,
  useSetAutostart,
  useSettings,
  useStatus,
  useTestAi,
  useUpdateCategory,
  useUpdateProject,
  useUpdateSettings,
  useRules,
} from "../lib/api";
import { fmtHM } from "../lib/format";
import { catColor, type ThemeName } from "../lib/palette";
import { Field, inputCls } from "../components/pickers";
import { Card, Dot, Empty, IconButton } from "../components/ui";

export function Settings({ categories, theme, today }: { categories: Category[]; theme: ThemeName; today: string | null }) {
  return (
    <div className="mx-auto flex max-w-[1100px] flex-col gap-5">
      <h1 className="font-display text-[24px] font-semibold text-ink1">
        Settings
        <span className="ml-3 text-[15px] font-normal text-ink2">taxonomy, rules, privacy, AI, data</span>
      </h1>
      <CategoriesCard theme={theme} />
      <ProjectsCard categories={categories} theme={theme} />
      <RulesCard categories={categories} theme={theme} />
      <PrivacyCard />
      <AiCard />
      <DataCard today={today} />
      <AboutCard />
    </div>
  );
}

// --- categories & projects (§10.6) -------------------------------------------
function CategoriesCard({ theme }: { theme: ThemeName }) {
  const cats = useCategories();
  const update = useUpdateCategory();
  const create = useCreateCategory();
  const [newName, setNewName] = useState("");
  return (
    <Card title="Categories">
      <div className="flex flex-col gap-1.5">
        {(cats.data ?? []).map((c) => (
          <div key={c.id} className="flex items-center gap-3 rounded-[10px] px-2 py-1.5 hover:bg-surface2/50">
            <Dot color={catColor(c, theme)} />
            <input
              className="min-w-0 flex-1 bg-transparent text-[14px] text-ink1 outline-none"
              defaultValue={c.name}
              onBlur={(e) => {
                const v = e.target.value.trim();
                if (v && v !== c.name) update.mutate({ id: c.id, name: v });
              }}
            />
            <select
              className="rounded-[8px] border border-hairline bg-surface2/60 px-1.5 py-1 text-[12px] text-ink2"
              value={c.color_slot ?? ""}
              onChange={(e) =>
                update.mutate({ id: c.id, color_slot: e.target.value ? Number(e.target.value) : null })
              }
            >
              <option value="">neutral</option>
              {[1, 2, 3, 4, 5, 6, 7, 8].map((s) => (
                <option key={s} value={s}>slot {s}</option>
              ))}
            </select>
            <label className="flex items-center gap-1.5 text-[12px] text-ink2">
              <input
                type="checkbox"
                checked={!!c.is_productive}
                onChange={(e) => update.mutate({ id: c.id, is_productive: e.target.checked ? 1 : 0 })}
              />
              productive
            </label>
            <IconButton
              label={c.archived ? "Unarchive" : "Archive"}
              onClick={() => update.mutate({ id: c.id, archived: c.archived ? 0 : 1 })}
            >
              {c.archived ? "unarchive" : "archive"}
            </IconButton>
          </div>
        ))}
      </div>
      <div className="mt-3 flex gap-2">
        <input
          className={inputCls}
          placeholder="New category name"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && newName.trim()) {
              create.mutate({ name: newName.trim() });
              setNewName("");
            }
          }}
        />
        <IconButton
          label="Add category"
          disabled={!newName.trim() || create.isPending}
          onClick={() => {
            create.mutate({ name: newName.trim() });
            setNewName("");
          }}
        >
          ＋ Add
        </IconButton>
      </div>
    </Card>
  );
}

function ProjectsCard({ categories, theme }: { categories: Category[]; theme: ThemeName }) {
  const projects = useProjects();
  const update = useUpdateProject();
  const catOf = (id: number) => categories.find((c) => c.id === id);
  const rows = (projects.data ?? []).filter((p) => !p.archived);
  return (
    <Card title="Projects">
      {rows.length === 0 && <Empty>No projects yet — create one from a span popover or a goal.</Empty>}
      <div className="flex flex-col gap-1.5">
        {rows.map((p) => (
          <div key={p.id} className="flex items-center gap-3 rounded-[10px] px-2 py-1.5 hover:bg-surface2/50">
            <Dot color={catColor(catOf(p.category_id), theme)} />
            <input
              className="min-w-0 flex-1 bg-transparent text-[14px] text-ink1 outline-none"
              defaultValue={p.name}
              onBlur={(e) => {
                const v = e.target.value.trim();
                if (v && v !== p.name) update.mutate({ id: p.id, name: v });
              }}
            />
            <span className="text-[12px] text-ink3">{catOf(p.category_id)?.name ?? "?"}</span>
            <IconButton label="Archive project" onClick={() => update.mutate({ id: p.id, archived: 1 })}>
              archive
            </IconButton>
          </div>
        ))}
      </div>
    </Card>
  );
}

// --- rules table (§10.6): pattern, target, source, hits, delete ----------------
function RulesCard({ categories, theme }: { categories: Category[]; theme: ThemeName }) {
  const rules = useRules();
  const del = useDeleteRule();
  const [filter, setFilter] = useState("");
  const rows = (rules.data ?? []).filter(
    (r) => !filter || r.pattern.includes(filter) || (r.category ?? "").toLowerCase().includes(filter.toLowerCase()),
  );
  const catOf = (id: number | null) => categories.find((c) => c.id === id);
  return (
    <Card
      title={`Rules (${rules.data?.length ?? 0})`}
      actions={
        <input
          className="rounded-[8px] border border-hairline bg-surface2/60 px-2 py-1 text-[12px] text-ink1 outline-none"
          placeholder="filter…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      }
    >
      <div className="max-h-[380px] overflow-y-auto">
        <table className="w-full text-[13px]">
          <thead className="sticky top-0 bg-surface1 text-left text-[11px] uppercase tracking-[0.08em] text-ink3">
            <tr>
              <th className="py-1.5 pr-3">Matcher</th>
              <th className="py-1.5 pr-3">Pattern</th>
              <th className="py-1.5 pr-3">Category</th>
              <th className="py-1.5 pr-3">Source</th>
              <th className="py-1.5 pr-3 text-right">Hits</th>
              <th className="py-1.5" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-hairline/60">
                <td className="py-1.5 pr-3 text-ink2">{r.matcher}</td>
                <td className="max-w-[260px] truncate py-1.5 pr-3 font-mono text-[12px] text-ink1" title={r.pattern}>
                  {r.pattern}
                </td>
                <td className="py-1.5 pr-3">
                  <span className="inline-flex items-center gap-1.5">
                    <Dot color={catColor(catOf(r.category_id), theme)} />
                    <span className="text-ink2">{r.category ?? "kind only"}</span>
                  </span>
                </td>
                <td className="py-1.5 pr-3 text-ink3">{r.source}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums text-ink2">{r.hit_count}</td>
                <td className="py-1.5 text-right">
                  <IconButton label="Delete rule" onClick={() => del.mutate(r.id)}>✕</IconButton>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <Empty>No rules match.</Empty>}
      </div>
    </Card>
  );
}

// --- privacy (§10.6): exclude lists, redaction, retention, debug ---------------
function ListEditor({
  label,
  values,
  placeholder,
  onSave,
}: {
  label: string;
  values: string[];
  placeholder: string;
  onSave: (next: string[]) => void;
}) {
  const [draft, setDraft] = useState("");
  return (
    <Field label={label}>
      <div className="flex flex-wrap items-center gap-1.5">
        {values.map((v) => (
          <span key={v} className="inline-flex items-center gap-1 rounded-full border border-hairline px-2 py-0.5 text-[12px] text-ink2">
            {v}
            <button type="button" className="text-ink3 hover:text-ink1" onClick={() => onSave(values.filter((x) => x !== v))}>
              ✕
            </button>
          </span>
        ))}
        <input
          className="min-w-[180px] flex-1 rounded-[8px] border border-hairline bg-surface2/60 px-2 py-1 text-[12px] text-ink1 outline-none"
          placeholder={placeholder}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && draft.trim()) {
              onSave([...values, draft.trim()]);
              setDraft("");
            }
          }}
        />
      </div>
    </Field>
  );
}

function PrivacyCard() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const s = settings.data?.settings;
  if (!s) return <Card title="Privacy"><Empty>Loading…</Empty></Card>;
  const save = (patch: Partial<SettingsData>) => update.mutate(patch);
  return (
    <Card title="Privacy">
      <div className="flex flex-col gap-4">
        <ListEditor
          label="Excluded apps (exe, * wildcard ok)"
          values={s.exclude_exes}
          placeholder="1password.exe"
          onSave={(v) => save({ exclude_exes: v })}
        />
        <ListEditor
          label="Excluded domains (subdomains covered)"
          values={s.exclude_domains}
          placeholder="mybank.com"
          onSave={(v) => save({ exclude_domains: v })}
        />
        <ListEditor
          label="Redaction regexes (applied to every AI payload)"
          values={s.redaction_patterns}
          placeholder="\\d{12}"
          onSave={(v) => save({ redaction_patterns: v })}
        />
        <div className="flex flex-wrap items-center gap-6">
          <Field label="Retention (months, 0 = forever)">
            <input
              type="number"
              min={0}
              className={inputCls + " w-[110px]"}
              defaultValue={s.retention_months}
              onBlur={(e) => save({ retention_months: Math.max(0, Number(e.target.value) || 0) })}
            />
          </Field>
          <label className="flex items-center gap-2 text-[13px] text-ink2">
            <input
              type="checkbox"
              checked={s.debug_ai_payloads}
              onChange={(e) => save({ debug_ai_payloads: e.target.checked })}
            />
            Dump AI payloads for audit (debug)
          </label>
          <label className="flex items-center gap-2 text-[13px] text-ink2">
            <input
              type="checkbox"
              checked={s.texture_fills}
              onChange={(e) => save({ texture_fills: e.target.checked })}
            />
            Texture fills (accessibility, 45°/135° lines)
          </label>
        </div>
        <p className="text-[12px] text-ink3">
          Excluded surfaces are still timed, but titles/URLs are replaced with “[excluded]”
          before they touch the database, and they never reach the AI.
        </p>
      </div>
    </Card>
  );
}

// --- AI (§10.6): models, summary time, cap, test connection ---------------------
function AiCard() {
  const settings = useSettings();
  const update = useUpdateSettings();
  const test = useTestAi();
  const s = settings.data?.settings;
  if (!s) return <Card title="AI"><Empty>Loading…</Empty></Card>;
  return (
    <Card title="AI">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Field label="Classifier model">
          <input
            className={inputCls}
            defaultValue={s.classify_model}
            onBlur={(e) => update.mutate({ classify_model: e.target.value.trim() })}
          />
        </Field>
        <Field label="Narrative model">
          <input
            className={inputCls}
            defaultValue={s.narrative_model}
            onBlur={(e) => update.mutate({ narrative_model: e.target.value.trim() })}
          />
        </Field>
        <Field label="Nightly summary time (HH:MM)">
          <input
            className={inputCls + " w-[120px]"}
            defaultValue={s.summary_time}
            onBlur={(e) => update.mutate({ summary_time: e.target.value.trim() })}
          />
        </Field>
        <Field label="Daily token cap">
          <input
            type="number"
            min={0}
            className={inputCls + " w-[160px]"}
            defaultValue={s.ai_daily_token_cap}
            onBlur={(e) => update.mutate({ ai_daily_token_cap: Math.max(0, Number(e.target.value) || 0) })}
          />
        </Field>
      </div>
      <div className="mt-4 flex items-center gap-3">
        <IconButton label="Test AI connection" disabled={test.isPending} onClick={() => test.mutate()}>
          {test.isPending ? "Testing…" : "Test connection"}
        </IconButton>
        {test.data && (
          <span className={`text-[13px] ${test.data.ok ? "text-ink2" : "text-ink1"}`}>
            {test.data.ok ? "✓ Connected — Groq responded." : `✕ ${test.data.detail ?? "Connection failed."}`}
          </span>
        )}
      </div>
    </Card>
  );
}

// --- data (§10.6): export JSON/CSV/Markdown per range, folder, DB size ----------
function DataCard({ today }: { today: string | null }) {
  const status = useStatus();
  const [from, setFrom] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 6);
    return d.toISOString().slice(0, 10);
  });
  const [to, setTo] = useState(() => today ?? new Date().toISOString().slice(0, 10));
  return (
    <Card title="Data">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="From">
          <input type="date" className={inputCls + " w-[160px]"} value={from} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label="To">
          <input type="date" className={inputCls + " w-[160px]"} value={to} onChange={(e) => setTo(e.target.value)} />
        </Field>
        {(["json", "csv", "md"] as const).map((f) => (
          <a
            key={f}
            href={exportUrl(f, from, to)}
            download
            className="rounded-[10px] border border-hairline px-3 py-1.5 text-[12px] text-ink2 transition-colors hover:bg-surface2"
          >
            Export {f.toUpperCase()}
          </a>
        ))}
      </div>
      <p className="mt-3 text-[12px] text-ink3">
        Data folder: <span className="font-mono">{status.data?.data_dir ?? "…"}</span> · DB size:{" "}
        {status.data ? `${(status.data.db_bytes / 1024 / 1024).toFixed(1)} MB` : "…"}
      </p>
    </Card>
  );
}

// --- about (§10.6): version + collector health ----------------------------------
function AboutCard() {
  const status = useStatus();
  const autostart = useSetAutostart();
  const d = status.data;
  const Row = ({ k, v }: { k: string; v: ReactNode }) => (
    <div className="flex items-baseline justify-between border-t border-hairline/60 py-1.5 text-[13px] first:border-t-0">
      <span className="text-ink3">{k}</span>
      <span className="text-ink1">{v}</span>
    </div>
  );
  return (
    <Card title="About">
      {!d ? (
        <Empty>Loading…</Empty>
      ) : (
        <>
          <Row k="Version" v={d.version} />
          <Row
            k="Collector"
            v={
              d.collector.paused
                ? "⏸ Paused"
                : d.collector.alive
                  ? `✓ Watching (last sample ${d.collector.last_tick_age_s ?? 0}s ago)`
                  : "✕ Offline"
            }
          />
          <Row
            k="Extension"
            v={
              d.extension.last_seen_age_s == null
                ? "— never seen"
                : `✓ last event ${fmtHM(d.extension.last_seen_age_s)} ago`
            }
          />
          <Row k="AI queue" v={`${d.ai_queue.pending} pending · ${d.ai_queue.failed} failed`} />
          <Row
            k="Footprint (budget <0.5% CPU · <150MB)"
            v={
              <span
                className="text-ink1"
                style={d.process.cpu_ok && d.process.rss_ok ? undefined : { color: "#E07A3F" }}
              >
                {d.process.cpu_pct == null ? "—" : `${d.process.cpu_pct}%`} CPU ·{" "}
                {d.process.rss_mb == null ? "—" : `${d.process.rss_mb} MB`}
                {d.process.cpu_ok && d.process.rss_ok ? " ✓" : " ✕ over budget"}
              </span>
            }
          />
          <Row k="Spans recorded" v={d.spans_total.toLocaleString()} />
          <div className="mt-3 flex items-center gap-2">
            <label className="flex items-center gap-2 text-[13px] text-ink2">
              <input
                type="checkbox"
                checked={d.autostart?.enabled ?? false}
                onChange={(e) => autostart.mutate(e.target.checked)}
              />
              Start with Windows
            </label>
          </div>
        </>
      )}
    </Card>
  );
}
