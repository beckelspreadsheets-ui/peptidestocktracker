import { NavLink } from "react-router-dom";
import { Activity, LayoutGrid, List, Radar, Stethoscope } from "lucide-react";

const NAV = [
  { to: "/", label: "Cockpit", icon: LayoutGrid, end: true },
  { to: "/events", label: "Events", icon: List },
  { to: "/watchlist", label: "Watchlist", icon: Radar },
  { to: "/health", label: "Source health", icon: Stethoscope },
];

export function Sidebar() {
  return (
    <aside className="hidden w-[208px] shrink-0 flex-col border-r border-line bg-panel/60 md:flex">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <div className="relative grid h-7 w-7 place-items-center rounded-md border border-accent/40 bg-accent/10">
          <Activity size={15} className="text-accent" />
          <span className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
        </div>
        <div className="leading-none">
          <div className="font-mono text-[13px] font-semibold tracking-tight text-ink">
            peptide<span className="text-accent">·</span>watch
          </div>
          <div className="mt-0.5 font-mono text-[9px] uppercase tracking-[0.2em] text-ink-3">
            cockpit
          </div>
        </div>
      </div>

      <nav className="flex flex-col gap-0.5 px-3">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `focusable group flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] transition ${
                isActive
                  ? "bg-accent/10 text-accent"
                  : "text-ink-2 hover:bg-panel-2 hover:text-ink"
              }`
            }
          >
            {({ isActive }) => (
              <>
                <Icon size={15} className={isActive ? "text-accent" : "text-ink-3 group-hover:text-ink-2"} />
                {label}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto px-5 py-4">
        <p className="font-mono text-[10px] leading-relaxed text-ink-3">
          Public-source research instrument. Not financial advice.
        </p>
      </div>
    </aside>
  );
}
