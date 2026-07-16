// Placeholder pages for nav completeness (§10): Goals (Phase 8), Review
// (Phase 7), Settings (Phase 9).
export function Placeholder({ icon, title, note }: { icon: string; title: string; note: string }) {
  return (
    <div className="mx-auto max-w-[1200px]">
      <h1 className="mb-5 font-display text-[24px] font-semibold text-ink1">{title}</h1>
      <div className="card flex flex-col items-center gap-3 rounded-2xl border border-hairline bg-surface1 py-16">
        <span className="text-[32px] text-accent">{icon}</span>
        <p className="max-w-md text-center text-[15px] text-ink2">{note}</p>
      </div>
    </div>
  );
}
