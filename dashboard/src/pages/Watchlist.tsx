import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { WatchlistCompany } from "../lib/types";
import { useFetch } from "../hooks/useFetch";
import { ComplianceFooter } from "../components/ComplianceFooter";
import { Panel, Tag } from "../components/ui";

const TIER_CLS: Record<number, string> = {
  1: "text-ok border-ok/40 bg-ok/10",
  2: "text-accent border-accent/30 bg-accent/10",
  3: "text-low border-low/30 bg-low/10",
};

export function Watchlist() {
  const { data } = useFetch<WatchlistCompany[]>(() => api.watchlist(), []);
  const navigate = useNavigate();
  const [sort, setSort] = useState<keyof WatchlistCompany>("tier");

  const rows = useMemo(() => {
    const list = [...(data || [])];
    list.sort((a, b) => {
      const av = a[sort] as never;
      const bv = b[sort] as never;
      return av > bv ? 1 : av < bv ? -1 : 0;
    });
    return list;
  }, [data, sort]);

  const Th = ({ k, children }: { k: keyof WatchlistCompany; children: React.ReactNode }) => (
    <th
      onClick={() => setSort(k)}
      className="cursor-pointer select-none px-3 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-ink-3 hover:text-ink-2"
    >
      {children}
      {sort === k && <span className="ml-1 text-accent">▾</span>}
    </th>
  );

  return (
    <div className="animate-fade-up space-y-4">
      <Panel title={`Watchlist · ${rows.length}`}>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead className="sticky top-0 bg-panel">
              <tr className="border-b border-line">
                <Th k="name">Company</Th>
                <Th k="ticker">Ticker</Th>
                <Th k="exchange">Exchange</Th>
                <Th k="tier">Tier</Th>
                <Th k="public_private">Type</Th>
                <Th k="liquidity_risk">Liquidity</Th>
                <th className="px-3 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-ink-3">
                  Peptides
                </th>
              </tr>
            </thead>
            <tbody className="row-divide">
              {rows.map((c) => (
                <tr
                  key={c.id}
                  onClick={() => navigate(`/events?company=${c.id}`)}
                  className="cursor-pointer transition hover:bg-panel-2"
                >
                  <td className="px-3 py-2.5 text-ink">{c.name}</td>
                  <td className="px-3 py-2.5 font-mono text-xs text-accent">{c.ticker || "—"}</td>
                  <td className="px-3 py-2.5 font-mono text-xs text-ink-2">{c.exchange || "—"}</td>
                  <td className="px-3 py-2.5">
                    <span className={`inline-flex rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold ${TIER_CLS[c.tier] || TIER_CLS[3]}`}>
                      T{c.tier}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 font-mono text-[11px] text-ink-3">
                    {c.public_private.replace(/_/g, " ")}
                  </td>
                  <td className="px-3 py-2.5">
                    {c.liquidity_risk ? (
                      <span className="font-mono text-[11px] text-high">{c.liquidity_risk}</span>
                    ) : (
                      <span className="text-ink-3">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      {c.peptides.slice(0, 3).map((p) => (
                        <Tag key={p}>{p}</Tag>
                      ))}
                      {c.peptides.length > 3 && (
                        <span className="font-mono text-[10px] text-ink-3">+{c.peptides.length - 3}</span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <ComplianceFooter />
    </div>
  );
}
