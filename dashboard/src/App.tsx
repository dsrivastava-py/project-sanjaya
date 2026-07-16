// App shell (§10): nav rail Today·History·Insights·Goals·Review·Settings,
// keyboard t/h/i/g/r/, plus ←/→ to move the active day. Dark default.
import { useEffect, useMemo, useState } from "react";

import { useCategories, useSettings, useStatus } from "./lib/api";
import { addDays } from "./lib/format";
import type { ThemeName } from "./lib/palette";
import { useTheme } from "./lib/theme";
import { Goals } from "./pages/Goals";
import { History } from "./pages/History";
import { Insights } from "./pages/Insights";
import { Onboarding } from "./pages/Onboarding";
import { Review } from "./pages/Review";
import { Settings } from "./pages/Settings";
import { Today } from "./pages/Today";

export type PageId = "today" | "history" | "insights" | "goals" | "review" | "settings";

const NAV: { id: PageId; label: string; key: string; icon: string; phase?: string }[] = [
  { id: "today", label: "Today", key: "t", icon: "☀" },
  { id: "history", label: "History", key: "h", icon: "▦" },
  { id: "insights", label: "Insights", key: "i", icon: "✦" },
  { id: "goals", label: "Goals", key: "g", icon: "◎" },
  { id: "review", label: "Review", key: "r", icon: "☰" },
  { id: "settings", label: "Settings", key: ",", icon: "⚙" },
];

export default function App() {
  const [theme, toggleTheme] = useTheme();
  const [page, setPage] = useState<PageId>("today");
  const [date, setDate] = useState<string | null>(null);
  const status = useStatus();
  const cats = useCategories();
  const settings = useSettings();
  const [onboarded, setOnboarded] = useState(false);
  const today = status.data?.today ?? null;
  const dayStartHour = status.data?.day_start_hour ?? 4;
  const showOnboarding = !onboarded && settings.data != null && !settings.data.settings.onboarding_done;

  // First status load pins the active day to "today" (day_start_hour aware).
  useEffect(() => {
    if (today && !date) setDate(today);
  }, [today, date]);

  const shiftDay = useMemo(
    () => (n: number) => {
      setDate((d) => {
        if (!d) return d;
        const next = addDays(d, n);
        return today && next > today ? d : next;
      });
    },
    [today],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const nav = NAV.find((n) => n.key === e.key);
      if (nav) setPage(nav.id);
      else if (e.key === "ArrowLeft") shiftDay(-1);
      else if (e.key === "ArrowRight") shiftDay(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [shiftDay]);

  const openDay = (d: string) => {
    setDate(d);
    setPage("today");
  };

  return (
    <div className="flex min-h-full">
      {showOnboarding && <Onboarding theme={theme} onDone={() => setOnboarded(true)} />}
      <NavRail
        page={page}
        setPage={setPage}
        theme={theme}
        toggleTheme={toggleTheme}
        collectorAlive={status.data?.collector.alive ?? false}
        paused={status.data?.collector.paused ?? false}
        version={status.data?.version}
      />
      <main className="min-w-0 flex-1 px-6 py-6 lg:px-10">
        {page === "today" && (
          <Today
            date={date}
            today={today}
            dayStartHour={dayStartHour}
            shiftDay={shiftDay}
            categories={cats.data ?? []}
            theme={theme}
          />
        )}
        {page === "history" && (
          <History today={today} categories={cats.data ?? []} theme={theme} onPick={openDay} />
        )}
        {page === "insights" && (
          <Insights today={today} categories={cats.data ?? []} theme={theme} />
        )}
        {page === "goals" && <Goals categories={cats.data ?? []} theme={theme} />}
        {page === "review" && <Review categories={cats.data ?? []} theme={theme} />}
        {page === "settings" && (
          <Settings categories={cats.data ?? []} theme={theme} today={today} />
        )}
      </main>
    </div>
  );
}

function NavRail({
  page,
  setPage,
  theme,
  toggleTheme,
  collectorAlive,
  paused,
  version,
}: {
  page: PageId;
  setPage: (p: PageId) => void;
  theme: ThemeName;
  toggleTheme: () => void;
  collectorAlive: boolean;
  paused: boolean;
  version?: string;
}) {
  const health = paused
    ? { color: "#E2A63D", label: "Paused" }
    : collectorAlive
      ? { color: "#22A06B", label: "Watching" }
      : { color: "#E07A3F", label: "Collector offline" };
  return (
    <aside className="sticky top-0 flex h-screen w-[200px] shrink-0 flex-col border-r border-hairline bg-surface1/60 px-3 py-5">
      {/* wordmark + eye (§4.1) */}
      <div className="mb-6 flex items-center gap-2.5 px-2">
        <EyeLogo />
        <span className="font-display text-[18px] font-medium tracking-[0.06em] text-ink1">
          Sanjaya
        </span>
      </div>
      <nav className="flex flex-col gap-1">
        {NAV.map((n) => (
          <button
            key={n.id}
            type="button"
            onClick={() => setPage(n.id)}
            title={`${n.label} (${n.key})`}
            className={`flex items-center gap-3 rounded-[10px] px-3 py-2 text-left text-[15px] transition-colors duration-150 ${
              page === n.id
                ? "bg-surface2 font-medium text-ink1"
                : "text-ink2 hover:bg-surface2/60 hover:text-ink1"
            }`}
          >
            <span className="w-4 text-center text-[13px] text-accent">{n.icon}</span>
            <span className="flex-1">{n.label}</span>
            <kbd className="text-[11px] text-ink3">{n.key}</kbd>
          </button>
        ))}
      </nav>
      <div className="mt-auto space-y-3 px-2">
        <div className="flex items-center gap-2 text-[12px] text-ink3">
          <span className="h-2 w-2 rounded-full" style={{ background: health.color }} />
          {health.label}
        </div>
        <button
          type="button"
          onClick={toggleTheme}
          className="w-full rounded-[10px] border border-hairline px-3 py-1.5 text-[13px] text-ink2 transition-colors duration-150 hover:bg-surface2"
        >
          {theme === "dark" ? "☀ Day narration" : "🌙 Night watch"}
        </button>
        {version && <div className="text-[11px] text-ink3">v{version}</div>}
      </div>
    </aside>
  );
}

function EyeLogo() {
  // Minimal geometric eye: circle iris in pointed-oval, radiating arc above (§4.1).
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden>
      <g stroke="var(--accent)" strokeWidth="1.8" fill="none" strokeLinecap="round">
        <path d="M2 15 Q13 6 24 15 Q13 24 2 15 Z" />
        <circle cx="13" cy="15" r="3.4" fill="var(--accent)" stroke="none" />
        <path d="M6.5 6.5 Q13 2.5 19.5 6.5" />
      </g>
    </svg>
  );
}
