export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const d = new Date(value.includes("T") ? value : value.replace(" ", "T") + "Z");
  return isNaN(d.getTime()) ? null : d;
}

export function relativeTime(value: string | null | undefined): string {
  const d = parseDate(value);
  if (!d) return "—";
  const secs = Math.round((Date.now() - d.getTime()) / 1000);
  if (secs < 60) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.round(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.round(months / 12)}y ago`;
}

/** Days until a deadline date (YYYY-MM-DD or ISO). Negative = passed. */
export function daysUntil(value: string | null | undefined): number | null {
  const d = parseDate(value);
  if (!d) return null;
  return Math.ceil((d.getTime() - Date.now()) / 86400000);
}

export function shortDate(value: string | null | undefined): string {
  const d = parseDate(value);
  if (!d) return "—";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function titleCase(s: string): string {
  return s
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Strip the "(CIK 0001234)" / extra parens noise from EDGAR display names. */
export function cleanCompanyName(name: string): string {
  return name.replace(/\s*\(CIK[^)]*\)/gi, "").replace(/\s{2,}/g, " ").trim();
}

export function compactMoney(value: number | null | undefined, currency = "USD"): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const prefix = currency === "USD" ? "$" : "";
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${prefix}${(value / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `${prefix}${(value / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${prefix}${(value / 1_000).toFixed(2)}K`;
  return `${prefix}${value.toFixed(2)}`;
}

export function pct(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
}
