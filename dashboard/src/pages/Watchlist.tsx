import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { compactMoney, pct, relativeTime } from "../lib/format";
import type { MarketDataItem, MarketWatchlistPage, WatchlistCompany } from "../lib/types";
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
  const { data: market } = useFetch<MarketWatchlistPage>(() => api.marketWatchlist(), []);
  const navigate = useNavigate();
  const [sort, setSort] = useState<keyof WatchlistCompany>("tier");
  const marketByCompany = useMemo(() => {
    return new Map((market?.items || []).map((item) => [item.company_id, item]));
  }, [market]);

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
                  Market
                </th>
                <th className="px-3 py-2 text-left font-mono text-[10px] uppercase tracking-wider text-ink-3">
                  Peptides
                </th>
              </tr>
            </thead>
            <tbody className="row-divide">
              {rows.map((c) => (
                <tr
                  key={c.id}
                  onClick={() => navigate(`/events?q=${encodeURIComponent(c.name)}`)}
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
                  <td className="min-w-[220px] px-3 py-2.5">
                    <MarketCell item={marketByCompany.get(c.id)} />
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
      {market?.source_note && (
        <div className="font-mono text-[10px] leading-relaxed text-ink-3">{market.source_note}</div>
      )}
      <ComplianceFooter disclaimers={market?.disclaimers} />
    </div>
  );
}

function MarketCell({ item }: { item?: MarketDataItem }) {
  if (!item || item.status === "unavailable") {
    return <span className="font-mono text-[11px] text-ink-3">unavailable</span>;
  }
  const currency = item.currency || "USD";
  return (
    <div className="space-y-1 font-mono">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
        <span className="text-ink">MC {compactMoney(item.market_cap, currency)}</span>
        <span className="text-ink-3">Px {compactMoney(item.price, currency)}</span>
      </div>
      <div className="flex flex-wrap gap-1 text-[10px]">
        <Move value={item.change_1d_pct} label="1d" />
        <Move value={item.change_7d_pct} label="7d" />
        <Move value={item.change_30d_pct} label="30d" />
      </div>
      <div className="text-[9px] text-ink-3">{relativeTime(item.as_of)}</div>
    </div>
  );
}

function Move({ label, value }: { label: string; value: number | null }) {
  const tone = value === null ? "text-ink-3" : value >= 0 ? "text-ok" : "text-high";
  return (
    <span className={`rounded border border-line px-1 py-0.5 ${tone}`}>
      {label} {pct(value)}
    </span>
  );
}
