import type { ReactNode } from "react";
import { daysUntil } from "../lib/format";

const SEV: Record<string, { label: string; cls: string; dot: string }> = {
  critical: { label: "CRIT", cls: "text-crit border-crit/40 bg-crit/10", dot: "bg-crit" },
  high: { label: "HIGH", cls: "text-high border-high/40 bg-high/10", dot: "bg-high" },
  medium: { label: "MED", cls: "text-med border-med/30 bg-med/10", dot: "bg-med" },
  low: { label: "LOW", cls: "text-low border-low/30 bg-low/10", dot: "bg-low" },
};

export function SeverityBadge({ severity }: { severity?: string | null }) {
  const s = SEV[(severity || "low").toLowerCase()] || SEV.low;
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold tracking-wider ${s.cls}`}
    >
      {s.label}
    </span>
  );
}

export function SeverityDot({ severity }: { severity?: string | null }) {
  const s = SEV[(severity || "low").toLowerCase()] || SEV.low;
  return <span className={`inline-block h-2 w-2 rounded-full ${s.dot}`} />;
}

export function Tag({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "accent" }) {
  const cls =
    tone === "accent"
      ? "text-accent border-accent/30 bg-accent/10"
      : "text-ink-2 border-line bg-panel-2";
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[10px] tracking-wide ${cls}`}>
      {children}
    </span>
  );
}

/** The signature score readout: a tabular number + a stacked component meter. */
export function ScoreMeter({
  score,
  components,
}: {
  score?: number;
  components?: Record<string, number>;
}) {
  if (score == null) return null;
  const parts = components || {};
  const order: [string, string][] = [
    ["severity", "bg-crit/70"],
    ["event_type", "bg-accent/80"],
    ["proximity", "bg-high/70"],
    ["recency", "bg-med/70"],
  ];
  return (
    <div className="flex flex-col items-end gap-1">
      <span className="font-mono text-lg font-semibold tabular-nums text-ink">
        {score.toFixed(1)}
      </span>
      <div className="flex h-1 w-16 overflow-hidden rounded-full bg-panel-3" title="severity · type · proximity · recency">
        {order.map(([k, cls]) => (
          <div key={k} className={cls} style={{ width: `${parts[k] || 0}%` }} />
        ))}
      </div>
    </div>
  );
}

/** Countdown to a deadline — warmer as it nears. The "is there still time?" cue. */
export function CountdownChip({ date }: { date?: string | null }) {
  const days = daysUntil(date);
  if (days == null) return null;
  let cls = "text-low border-low/30";
  if (days <= 0) cls = "text-ink-3 border-line";
  else if (days <= 7) cls = "text-crit border-crit/40 bg-crit/10";
  else if (days <= 21) cls = "text-high border-high/40 bg-high/10";
  else cls = "text-accent border-accent/30 bg-accent/5";
  const label = days <= 0 ? "closed" : `${days}d left`;
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold ${cls}`}>
      {label}
    </span>
  );
}

export function StatusDot({ status }: { status: string }) {
  const map: Record<string, string> = {
    done: "bg-ok",
    completed: "bg-ok",
    running: "bg-accent animate-pulse",
    error: "bg-crit",
    failed: "bg-crit",
    skipped: "bg-low",
    pending: "bg-low",
  };
  return <span className={`inline-block h-2 w-2 rounded-full ${map[status] || "bg-low"}`} title={status} />;
}

export function Panel({
  title,
  action,
  children,
  className = "",
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {title && (
        <header className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <h2 className="font-mono text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-2">
            {title}
          </h2>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-4 py-6 text-center font-mono text-xs text-ink-3">{children}</div>;
}
