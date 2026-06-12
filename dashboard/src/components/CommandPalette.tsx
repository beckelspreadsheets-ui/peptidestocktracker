import { Command } from "cmdk";
import { Building2, List, Pill, Radar, Stethoscope, LayoutGrid, type LucideIcon } from "lucide-react";
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import type { WatchlistCompany } from "../lib/types";
import { cleanCompanyName } from "../lib/format";

export function CommandPalette({
  open,
  setOpen,
  watchlist,
  peptides,
}: {
  open: boolean;
  setOpen: (v: boolean) => void;
  watchlist: WatchlistCompany[];
  peptides: string[];
}) {
  const navigate = useNavigate();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(!open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  const go = (path: string) => {
    setOpen(false);
    navigate(path);
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center bg-black/55 px-4 pt-[14vh] backdrop-blur-sm" onClick={() => setOpen(false)}>
      <Command
        label="Command palette"
        className="w-full max-w-xl overflow-hidden rounded-xl border border-line-strong bg-panel shadow-drawer"
        onClick={(e) => e.stopPropagation()}
        loop
      >
        <div className="border-b border-line px-3">
          <Command.Input
            autoFocus
            placeholder="Jump to a company, ticker, peptide, or screen…"
            className="w-full bg-transparent px-1 py-3.5 text-sm text-ink outline-none placeholder:text-ink-3"
          />
        </div>
        <Command.List className="max-h-[52vh] overflow-y-auto p-2">
          <Command.Empty className="px-3 py-6 text-center font-mono text-xs text-ink-3">
            No matches.
          </Command.Empty>

          <Command.Group heading="Screens" className="px-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:font-mono [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-ink-3">
            <Item icon={LayoutGrid} onSelect={() => go("/")}>Cockpit</Item>
            <Item icon={List} onSelect={() => go("/events")}>Events feed</Item>
            <Item icon={Radar} onSelect={() => go("/watchlist")}>Watchlist</Item>
            <Item icon={Stethoscope} onSelect={() => go("/health")}>Source health</Item>
          </Command.Group>

          {watchlist.length > 0 && (
            <Command.Group heading="Watchlist companies" className="px-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:font-mono [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-ink-3">
              {watchlist.map((c) => (
                <Item
                  key={c.id}
                  icon={Building2}
                  value={`${c.name} ${c.ticker || ""} ${c.id}`}
                  onSelect={() => go(`/events?q=${encodeURIComponent(c.name)}`)}
                >
                  <span className="flex-1">{cleanCompanyName(c.name)}</span>
                  {c.ticker && (
                    <span className="font-mono text-[11px] text-accent">{c.ticker}</span>
                  )}
                </Item>
              ))}
            </Command.Group>
          )}

          {peptides.length > 0 && (
            <Command.Group heading="Peptides" className="px-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:font-mono [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-ink-3">
              {peptides.map((p) => (
                <Item key={p} icon={Pill} onSelect={() => go(`/events?peptide=${p}`)}>
                  {p}
                </Item>
              ))}
            </Command.Group>
          )}
        </Command.List>
      </Command>
    </div>
  );
}

function Item({
  icon: Icon,
  children,
  onSelect,
  value,
}: {
  icon: LucideIcon;
  children: React.ReactNode;
  onSelect: () => void;
  value?: string;
}) {
  return (
    <Command.Item
      value={value}
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-ink-2 aria-selected:bg-accent/10 aria-selected:text-ink"
    >
      <Icon size={14} className="text-ink-3" />
      {children}
    </Command.Item>
  );
}
