import { Search, Wifi, WifiOff } from "lucide-react";
import { useLocation } from "react-router-dom";

const CRUMB: Record<string, string> = {
  "": "Cockpit",
  events: "Events",
  watchlist: "Watchlist",
  health: "Source health",
};

export function TopBar({
  live,
  generatedAt,
  onOpenSearch,
}: {
  live: boolean;
  generatedAt?: string;
  onOpenSearch: () => void;
}) {
  const { pathname } = useLocation();
  const seg = pathname.split("/").filter(Boolean)[0] || "";
  const crumb = CRUMB[seg] || "Cockpit";

  return (
    <header className="sticky top-0 z-30 flex items-center gap-4 border-b border-line bg-base/85 px-5 py-3 backdrop-blur">
      <div className="flex items-center gap-2 font-mono text-xs text-ink-3">
        <span className="text-ink-2">{crumb}</span>
      </div>

      <button
        onClick={onOpenSearch}
        className="focusable group ml-2 flex flex-1 items-center gap-2 rounded-md border border-line bg-panel px-3 py-1.5 text-left text-xs text-ink-3 transition hover:border-line-strong md:max-w-md"
      >
        <Search size={13} />
        <span className="flex-1">Search companies, tickers, peptides…</span>
        <kbd className="rounded border border-line bg-panel-2 px-1.5 py-0.5 font-mono text-[10px] text-ink-2">
          ⌘K
        </kbd>
      </button>

      <div className="ml-auto flex items-center gap-3 font-mono text-[10px]">
        {generatedAt && (
          <span className="hidden text-ink-3 sm:inline">synced {timeAgo(generatedAt)}</span>
        )}
        <span
          className={`inline-flex items-center gap-1.5 rounded border px-2 py-1 ${
            live ? "border-ok/30 bg-ok/10 text-ok" : "border-med/30 bg-med/10 text-med"
          }`}
          title={live ? "Connected to live API" : "API offline — showing sample data"}
        >
          {live ? <Wifi size={11} /> : <WifiOff size={11} />}
          {live ? "LIVE" : "SAMPLE"}
        </span>
      </div>
    </header>
  );
}

function timeAgo(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  return `${Math.round(mins / 60)}h ago`;
}
