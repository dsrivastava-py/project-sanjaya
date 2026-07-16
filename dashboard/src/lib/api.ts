// Typed fetchers over the local JSON API (PRD §10.7). Same-origin; localhost only.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export interface Category {
  id: number;
  name: string;
  color_slot: number | null; // 1..8 → §4.3; null → "Other" neutral
  is_productive: number;
  sort: number;
  archived: number;
}

export interface Span {
  id: number;
  start_ts: number;
  end_ts: number;
  kind: string;
  exe: string | null;
  app_name: string | null;
  window_title: string | null;
  url: string | null;
  domain: string | null;
  detail: string | null; // JSON string
  category_id: number | null;
  project_id: number | null;
  classified_by: "rule" | "ai" | "user" | null;
  ai_confidence: number | null;
  edited: number;
}

export interface GoalToday {
  id: number;
  name: string;
  direction: "at_least" | "at_most";
  target_minutes: number;
  minutes: number;
  category_id: number | null;
  project_id: number | null;
  met: boolean;
  active_today: boolean;
  streak: number;
  best_streak: number;
}

export interface Project {
  id: number;
  category_id: number;
  name: string;
  archived: number;
}

export interface LearnedRule {
  rule_id: number;
  matcher: string;
  pattern: string;
  retro_applied: number;
}

export interface ReviewGroup {
  key: string;
  domain: string | null;
  exe: string | null;
  app_name: string | null;
  count: number;
  total_s: number;
  span_ids: number[];
  sample_titles: string[];
  last_ts: number;
}

export interface GoalHistoryEntry {
  period_start: string;
  minutes: number;
  status: "met" | "missed" | "skipped" | "pending";
}

export interface GoalCard {
  id: number;
  name: string;
  period: "daily" | "weekly" | "monthly" | "yearly";
  direction: "at_least" | "at_most";
  target_minutes: number;
  category_id: number | null;
  project_id: number | null;
  active_days: number[] | null; // Mon=0..Sun=6
  created_ts: number;
  archived: boolean;
  period_start: string;
  minutes: number;
  status: "met" | "missed" | "skipped" | "pending";
  met: boolean;
  streak: { current: number; best: number };
  history: GoalHistoryEntry[];
}

export interface StopwatchReading {
  ts: number;
  source: string;
  label: string | null;
  last_value_s: number;
  event: "paused" | "closed" | "reset";
}

export interface Summary {
  date: string;
  exists: boolean;
  narrative_md?: string | null;
  highlights?: string[];
  suggestions?: string[];
  focus_score?: number | null;
  category_totals?: Record<string, number>;
  ai_model?: string | null;
  generated_ts?: number | null;
  edited?: boolean;
  user_note_md?: string | null;
}

export interface DayData {
  date: string;
  active_seconds: number;
  idle_seconds: number;
  focus_score: number;
  focus_components: { score: number; P: number; D: number; S: number };
  category_totals: Record<string, number>; // key: category id as string | "uncategorized"
  spans: Span[];
  goals: GoalToday[];
  stopwatch: StopwatchReading[];
  summary: Summary;
}

export interface RangeDay {
  date: string;
  active_seconds: number;
  idle_seconds: number;
  focus_score: number | null;
  category_totals: Record<string, number>;
}

export interface Status {
  version: string;
  now_ts: number;
  today: string;
  timezone: string;
  day_start_hour: number;
  collector: { alive: boolean; last_tick_age_s: number | null; paused: boolean };
  extension: { last_seen_ts: number | null; last_seen_age_s: number | null };
  ai_queue: { pending: number; failed: number };
  process: {
    cpu_pct: number | null;
    rss_mb: number | null;
    num_threads: number | null;
    budget_cpu_pct: number;
    budget_rss_mb: number;
    cpu_ok: boolean;
    rss_ok: boolean;
  };
  autostart: { enabled: boolean };
  data_dir: string;
  exports_dir: string;
  spans_total: number;
  db_bytes: number;
}

export interface WeeklyInsight {
  exists: boolean;
  week_start?: string;
  generated_ts?: number;
  insight_md?: string;
  wins?: string[];
  leaks?: string[];
  next_week_focus?: string[];
}

export interface Leak {
  domain: string;
  this_s: number;
  prev_s: number;
  delta_s: number;
}

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${body ? `: ${body}` : ""}`);
  }
  return res.json() as Promise<T>;
}

export function useStatus() {
  return useQuery<Status>({
    queryKey: ["status"],
    queryFn: () => j("/api/status"),
    refetchInterval: 30_000,
  });
}

export function useCategories() {
  return useQuery<Category[]>({
    queryKey: ["categories"],
    queryFn: async () => (await j<{ categories: Category[] }>("/api/categories")).categories,
    staleTime: 5 * 60_000,
  });
}

export function useDay(date: string | null) {
  return useQuery<DayData>({
    queryKey: ["day", date],
    queryFn: () => j(`/api/day/${date}`),
    enabled: !!date,
  });
}

export function useRange(from: string | null, to: string | null) {
  return useQuery<RangeDay[]>({
    queryKey: ["range", from, to],
    queryFn: async () =>
      (await j<{ days: RangeDay[] }>(`/api/range?from=${from}&to=${to}`)).days,
    enabled: !!from && !!to,
  });
}

export function useWeekly(week: string | null) {
  return useQuery<WeeklyInsight>({
    queryKey: ["weekly", week],
    queryFn: () => j(`/api/insights/weekly${week ? `?week=${week}` : ""}`),
    enabled: !!week,
  });
}

export function useLeaks(week: string | null) {
  return useQuery<{ week_start: string; leaks: Leak[] }>({
    queryKey: ["leaks", week],
    queryFn: () => j(`/api/insights/leaks${week ? `?week=${week}` : ""}`),
    enabled: !!week,
  });
}

export function useRegenerateSummary(date: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => j(`/api/summary/${date}/generate`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["day", date] });
    },
  });
}

export function useGenerateWeekly(week: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      j("/api/insights/weekly/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ week }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["weekly", week] });
    },
  });
}

// --- Phase 7: span editing ----------------------------------------------------
const JSON_HEADERS = { "Content-Type": "application/json" };
const DAY_S = 86400;

function clipToDay(start: number, end: number, dayStart: number): number {
  return Math.max(0, Math.min(end, dayStart + DAY_S) - Math.max(start, dayStart));
}

/** Shift a span's clipped duration between category_totals keys (client-side
 * mirror of the server recompute, for the optimistic flash). */
function shiftTotals(
  totals: Record<string, number>,
  span: Span,
  dayStart: number,
  fromCat: number | null | undefined, // undefined = don't subtract
  toCat: number | null | undefined, //   undefined = don't add (pure removal)
): Record<string, number> {
  if (span.kind === "idle" || span.kind === "locked") return totals;
  const dur = clipToDay(span.start_ts, span.end_ts, dayStart);
  const out = { ...totals };
  const keyOf = (c: number | null) => (c == null ? "uncategorized" : String(c));
  if (fromCat !== undefined) {
    const k = keyOf(fromCat);
    out[k] = Math.max(0, (out[k] ?? 0) - dur);
    if (out[k] === 0) delete out[k];
  }
  if (toCat !== undefined) out[keyOf(toCat)] = (out[keyOf(toCat)] ?? 0) + dur;
  return out;
}

export interface SpanPatch {
  id: number;
  category_id?: number | null;
  project_id?: number | null;
  label?: string | null;
  learn_rule?: boolean;
}

/** PATCH /api/spans/{id} with an optimistic ["day", date] cache update: the mix
 * chart + totals move instantly, then the server recompute settles the truth. */
export function useUpdateSpan(date: string | null, dayStart: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: SpanPatch) =>
      j<{ span: Span; rule: LearnedRule | null }>(`/api/spans/${id}`, {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
      }),
    onMutate: async (patch) => {
      await qc.cancelQueries({ queryKey: ["day", date] });
      const prev = qc.getQueryData<DayData>(["day", date]);
      if (prev) {
        const span = prev.spans.find((s) => s.id === patch.id);
        if (span) {
          const newCat =
            patch.category_id !== undefined ? patch.category_id : span.category_id;
          qc.setQueryData<DayData>(["day", date], {
            ...prev,
            category_totals:
              patch.category_id !== undefined && newCat !== span.category_id
                ? shiftTotals(prev.category_totals, span, dayStart, span.category_id, newCat)
                : prev.category_totals,
            spans: prev.spans.map((s) =>
              s.id === patch.id
                ? {
                    ...s,
                    category_id: newCat,
                    project_id:
                      patch.project_id !== undefined ? patch.project_id : s.project_id,
                    classified_by: "user",
                    edited: 1,
                  }
                : s,
            ),
          });
        }
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(["day", date], ctx.prev);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["day", date] });
      qc.invalidateQueries({ queryKey: ["review"] });
      qc.invalidateQueries({ queryKey: ["goals"] });
      qc.invalidateQueries({ queryKey: ["range"] });
    },
  });
}

export interface NewSpan {
  start_ts: number;
  end_ts: number;
  category_id?: number | null;
  project_id?: number | null;
  label?: string | null;
}

export function useCreateSpan(date: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: NewSpan) =>
      j<{ span: Span }>("/api/spans", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
      }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["day", date] });
      qc.invalidateQueries({ queryKey: ["goals"] });
      qc.invalidateQueries({ queryKey: ["range"] });
    },
  });
}

export function useDeleteSpan(date: string | null, dayStart: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => j(`/api/spans/${id}`, { method: "DELETE" }),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: ["day", date] });
      const prev = qc.getQueryData<DayData>(["day", date]);
      if (prev) {
        const span = prev.spans.find((s) => s.id === id);
        qc.setQueryData<DayData>(["day", date], {
          ...prev,
          category_totals: span
            ? shiftTotals(prev.category_totals, span, dayStart, span.category_id, undefined)
            : prev.category_totals,
          spans: prev.spans.filter((s) => s.id !== id),
        });
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(["day", date], ctx.prev);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["day", date] });
      qc.invalidateQueries({ queryKey: ["goals"] });
      qc.invalidateQueries({ queryKey: ["range"] });
    },
  });
}

export function useSplitSpan(date: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, at_ts }: { id: number; at_ts: number }) =>
      j<{ spans: Span[] }>(`/api/spans/${id}/split`, {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ at_ts }),
      }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["day", date] });
    },
  });
}

// journal inline edit (§10.1): narrative, user note, highlights
export function useUpdateSummary(date: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      narrative_md?: string;
      user_note_md?: string;
      highlights?: string[];
    }) =>
      j<Summary>(`/api/summary/${date}`, {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
      }),
    onSuccess: (summary) => {
      const prev = qc.getQueryData<DayData>(["day", date]);
      if (prev) qc.setQueryData<DayData>(["day", date], { ...prev, summary });
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["day", date] }),
  });
}

// --- Phase 7: review queue ------------------------------------------------------
export function useReviewQueue(days: number) {
  return useQuery<{ days: number; total_spans: number; groups: ReviewGroup[] }>({
    queryKey: ["review", days],
    queryFn: () => j(`/api/review?days=${days}`),
  });
}

export function useAssignReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      span_ids: number[];
      category_id: number;
      project_id?: number | null;
      learn_rule?: boolean;
    }) =>
      j<{ updated: number; rules: LearnedRule[] }>("/api/review/assign", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
      }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["review"] });
      qc.invalidateQueries({ queryKey: ["day"] });
      qc.invalidateQueries({ queryKey: ["goals"] });
      qc.invalidateQueries({ queryKey: ["range"] });
    },
  });
}

export interface AutoSortAssignment {
  key: string;
  category: string;
  category_id: number;
  confidence: number;
  count: number;
  rule_created: boolean;
}

export interface AutoSortResult {
  sorted_groups: number;
  sorted_spans: number;
  groups_total: number;
  remaining_groups: number;
  assignments: AutoSortAssignment[];
  total_tokens: number;
  undo_available: boolean;
}

export function useAutoSortReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { days: number }) =>
      j<AutoSortResult>("/api/review/auto-sort", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
      }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["review"] });
      qc.invalidateQueries({ queryKey: ["day"] });
      qc.invalidateQueries({ queryKey: ["goals"] });
      qc.invalidateQueries({ queryKey: ["range"] });
      qc.invalidateQueries({ queryKey: ["rules"] });
    },
  });
}

export function useUndoAutoSort() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      j<{ reverted_spans: number; deleted_rules: number }>("/api/review/undo", {
        method: "POST",
        headers: JSON_HEADERS,
      }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["review"] });
      qc.invalidateQueries({ queryKey: ["day"] });
      qc.invalidateQueries({ queryKey: ["goals"] });
      qc.invalidateQueries({ queryKey: ["range"] });
      qc.invalidateQueries({ queryKey: ["rules"] });
    },
  });
}

// --- projects ---------------------------------------------------------------------
export function useProjects() {
  return useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: async () => (await j<{ projects: Project[] }>("/api/projects")).projects,
    staleTime: 60_000,
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; category_id: number }) =>
      j<{ project: Project }>("/api/projects", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
      }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

// --- Phase 8: goals ------------------------------------------------------------------
export function useGoals(includeArchived = false) {
  return useQuery<GoalCard[]>({
    queryKey: ["goals", includeArchived],
    queryFn: async () =>
      (
        await j<{ goals: GoalCard[] }>(
          `/api/goals${includeArchived ? "?include_archived=true" : ""}`,
        )
      ).goals,
  });
}

export interface GoalBody {
  name: string;
  period: GoalCard["period"];
  direction: GoalCard["direction"];
  target_minutes: number;
  category_id?: number | null;
  project_id?: number | null;
  active_days?: number[] | null;
}

export function useCreateGoal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: GoalBody) =>
      j<{ goal: GoalCard }>("/api/goals", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
      }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["goals"] });
      qc.invalidateQueries({ queryKey: ["day"] });
    },
  });
}

export function useUpdateGoal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: Partial<GoalBody> & { id: number }) =>
      j<{ goal: GoalCard }>(`/api/goals/${id}`, {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
      }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["goals"] });
      qc.invalidateQueries({ queryKey: ["day"] });
    },
  });
}

export function useDeleteGoal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => j(`/api/goals/${id}`, { method: "DELETE" }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["goals"] });
      qc.invalidateQueries({ queryKey: ["day"] });
    },
  });
}

// --- Phase 9: settings / rules / managers / export -----------------------------------
export interface Settings {
  classify_model: string;
  narrative_model: string;
  summary_time: string;
  ai_daily_token_cap: number;
  debug_ai_payloads: boolean;
  exclude_exes: string[];
  exclude_domains: string[];
  redaction_patterns: string[];
  pause_schedule: string[];
  retention_months: number;
  texture_fills: boolean;
  onboarding_done: boolean;
}

export interface SettingsPayload {
  settings: Settings;
  data_dir: string;
  exports_dir: string;
}

export interface Rule {
  id: number;
  priority: number;
  matcher: "exe" | "domain" | "url_prefix" | "title_regex";
  pattern: string;
  kind_hint: string | null;
  category_id: number | null;
  project_id: number | null;
  source: "seed" | "learned" | "user";
  created_ts: number;
  hit_count: number;
  category: string | null;
  project: string | null;
}

export function useSettings() {
  return useQuery<SettingsPayload>({
    queryKey: ["settings"],
    queryFn: () => j("/api/settings"),
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<Settings>) =>
      j<{ settings: Settings }>("/api/settings", {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
      }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
}

export function useRules() {
  return useQuery<Rule[]>({
    queryKey: ["rules"],
    queryFn: async () => (await j<{ rules: Rule[] }>("/api/rules")).rules,
  });
}

export function useDeleteRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => j(`/api/rules/${id}`, { method: "DELETE" }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  });
}

export function useUpdateCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: Partial<Category> & { id: number }) =>
      j<{ category: Category }>(`/api/categories/${id}`, {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
      }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["categories"] });
      qc.invalidateQueries({ queryKey: ["day"] });
    },
  });
}

export function useCreateCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; color_slot?: number | null; is_productive?: boolean }) =>
      j<{ category: Category }>("/api/categories", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
      }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["categories"] }),
  });
}

export function useUpdateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: Partial<Project> & { id: number }) =>
      j<{ project: Project }>(`/api/projects/${id}`, {
        method: "PATCH",
        headers: JSON_HEADERS,
        body: JSON.stringify(body),
      }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useArchiveProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => j(`/api/projects/${id}`, { method: "DELETE" }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useTestAi() {
  return useMutation({
    mutationFn: () =>
      j<{ ok: boolean; detail?: string; total_tokens?: number }>("/api/settings/test-ai", {
        method: "POST",
      }),
  });
}

export function useSetAutostart() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) =>
      j<{ enabled: boolean }>("/api/autostart", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ enabled }),
      }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["status"] }),
  });
}

export function usePauseTracking() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (minutes: number | null) =>
      j("/api/pause", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ minutes }) }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["status"] }),
  });
}

export function useResumeTracking() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => j("/api/resume", { method: "POST" }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["status"] }),
  });
}

export function exportUrl(format: "json" | "csv" | "md", from: string, to: string): string {
  return `/api/export?format=${format}&from=${from}&to=${to}`;
}
