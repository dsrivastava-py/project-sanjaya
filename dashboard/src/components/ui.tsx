// Small shared UI atoms: cards, chips, empty states, section titles.
import type { ReactNode } from "react";

export function Card({
  title,
  actions,
  children,
  className = "",
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`card rounded-2xl border border-hairline bg-surface1 p-5 ${className}`}
    >
      {(title || actions) && (
        <header className="mb-4 flex items-center justify-between gap-3">
          {title ? (
            <h2 className="font-display text-[13px] font-medium uppercase tracking-[0.08em] text-ink3">
              {title}
            </h2>
          ) : (
            <span />
          )}
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

/** ✦ chip — marks AI-generated text so AI vs human is always distinguishable (§10.1). */
export function AiChip() {
  return (
    <span
      title="AI-generated"
      className="inline-flex items-center gap-1 rounded-full border border-hairline px-2 py-0.5 text-[12px] text-accent"
    >
      ✦ AI
    </span>
  );
}

export function EditedChip() {
  return (
    <span className="inline-flex items-center rounded-full border border-hairline px-2 py-0.5 text-[12px] text-ink3">
      edited
    </span>
  );
}

export function Dot({ color }: { color: string }) {
  return (
    <span
      aria-hidden
      className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
      style={{ background: color }}
    />
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-[13px] text-ink3">{children}</p>;
}

export function IconButton({
  label,
  onClick,
  active = false,
  disabled = false,
  title,
  children,
}: {
  label: string;
  onClick?: () => void;
  active?: boolean;
  disabled?: boolean;
  title?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={title ?? label}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-[10px] border border-hairline px-2 py-1 text-[12px] transition-colors duration-200 ${
        active ? "bg-surface2 text-ink1" : "text-ink2 hover:bg-surface2"
      } ${disabled ? "cursor-not-allowed opacity-40" : ""}`}
    >
      {children}
    </button>
  );
}
