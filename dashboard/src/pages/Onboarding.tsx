// First-run onboarding (Phase 10, §14): confirm seeded categories, point to the
// GROQ key (.env), point to the browser extension, offer start-on-boot. Shown
// once — dismissing writes settings.onboarding_done = true. Full-screen overlay
// so it can't be missed on a fresh machine.
import type { ReactNode } from "react";

import { useCategories, useSetAutostart, useStatus, useTestAi, useUpdateSettings } from "../lib/api";
import { catColor, type ThemeName } from "../lib/palette";
import { Dot, IconButton } from "../components/ui";

export function Onboarding({ theme, onDone }: { theme: ThemeName; onDone: () => void }) {
  const cats = useCategories();
  const status = useStatus();
  const test = useTestAi();
  const autostart = useSetAutostart();
  const update = useUpdateSettings();

  const finish = () => update.mutate({ onboarding_done: true }, { onSuccess: onDone });
  const hasKey = test.data?.ok ?? null;
  const extSeen = status.data?.extension.last_seen_age_s != null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-page/80 p-6 backdrop-blur-sm">
      <div className="w-full max-w-[640px] rounded-2xl border border-hairline bg-surface1 p-8 shadow-2xl">
        <div className="mb-6 flex items-center gap-3">
          <span className="text-[26px] text-accent">👁</span>
          <div>
            <h1 className="font-display text-[22px] font-semibold text-ink1">Welcome to Sanjaya</h1>
            <p className="text-[13px] text-ink3">Four quick things, then you're watching time honestly.</p>
          </div>
        </div>

        <ol className="flex flex-col gap-5">
          {/* 1 — seeded categories */}
          <Step n={1} title="Your categories are ready">
            <p className="mb-2 text-[13px] text-ink2">
              Seeded from your world — edit any time in Settings.
            </p>
            <div className="flex flex-wrap gap-2">
              {(cats.data ?? []).map((c) => (
                <span key={c.id} className="inline-flex items-center gap-1.5 rounded-full border border-hairline px-2.5 py-0.5 text-[12px] text-ink2">
                  <Dot color={catColor(c, theme)} />
                  {c.name}
                </span>
              ))}
            </div>
          </Step>

          {/* 2 — GROQ key */}
          <Step n={2} title="Add your GROQ API key">
            <p className="text-[13px] text-ink2">
              Put <span className="font-mono text-ink1">GROQ_API_KEY=…</span> in the{" "}
              <span className="font-mono text-ink1">.env</span> file at the project root, then
              restart. Key from <span className="font-mono text-ink1">console.groq.com/keys</span>.
              Timing still works without it — only the AI journal pauses.
            </p>
            <div className="mt-2 flex items-center gap-3">
              <IconButton label="Test AI connection" disabled={test.isPending} onClick={() => test.mutate()}>
                {test.isPending ? "Testing…" : "Test connection"}
              </IconButton>
              {hasKey === true && <span className="text-[13px] text-ink2">✓ Groq responded.</span>}
              {hasKey === false && (
                <span className="text-[13px]" style={{ color: "#E07A3F" }}>
                  ✕ {test.data?.detail ?? "not reachable"}
                </span>
              )}
            </div>
          </Step>

          {/* 3 — extension */}
          <Step n={3} title="Load the browser extension">
            <p className="text-[13px] text-ink2">
              Chrome/Edge → <span className="font-mono text-ink1">chrome://extensions</span> →
              Developer mode → <span className="font-mono text-ink1">Load unpacked</span> → pick the{" "}
              <span className="font-mono text-ink1">extension/</span> folder. It reports the active
              tab's domain so browsing is categorized.
            </p>
            <p className="mt-1 text-[12px] text-ink3">
              {extSeen ? "✓ Extension has reported in." : "· No extension events yet."}
            </p>
          </Step>

          {/* 4 — start on boot */}
          <Step n={4} title="Start Sanjaya with Windows">
            <label className="flex items-center gap-2 text-[13px] text-ink2">
              <input
                type="checkbox"
                checked={status.data?.autostart.enabled ?? false}
                onChange={(e) => autostart.mutate(e.target.checked)}
              />
              Launch on sign-in (recommended — honest time needs to always be watching)
            </label>
          </Step>
        </ol>

        <div className="mt-8 flex justify-end gap-3">
          <button
            type="button"
            onClick={finish}
            disabled={update.isPending}
            className="rounded-[10px] bg-accent px-4 py-2 text-[14px] font-medium text-page transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {update.isPending ? "Saving…" : "Start watching →"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-hairline text-[12px] text-accent">
        {n}
      </span>
      <div className="min-w-0 flex-1">
        <h3 className="mb-1 text-[14px] font-medium text-ink1">{title}</h3>
        {children}
      </div>
    </li>
  );
}
