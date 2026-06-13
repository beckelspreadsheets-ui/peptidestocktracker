import {
  mockBriefing,
  mockEvents,
  mockOperatorDeadlines,
  mockOperatorDetail,
  mockOperatorEntities,
  mockWatchlist,
  mockSourceHealth,
} from "./mock";
import type {
  Briefing,
  EventItem,
  EventsPage,
  OperatorDeadlinesPage,
  OperatorEntitiesPage,
  OperatorEntityDetail,
  OperatorStatus,
  MarketWatchlistPage,
  SourceHealth,
  WatchlistCompany,
} from "./types";

// Default to relative URLs: works same-origin when the API serves the built
// dashboard, and via the Vite dev proxy in development. Override with
// VITE_API_BASE only when the API is on a different origin.
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

async function get<T>(path: string, fallback: T): Promise<{ data: T; live: boolean }> {
  try {
    const res = await fetch(`${BASE}${path}`, { headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error(`${res.status}`);
    return { data: (await res.json()) as T, live: true };
  } catch {
    // Offline / API not running: fall back to mock data so the UI still renders.
    return { data: fallback, live: false };
  }
}

export const api = {
  briefing: (limit = 25) =>
    get<Briefing>(`/api/briefing?limit=${limit}`, mockBriefing),
  events: (params: Record<string, string | number | undefined>) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") qs.set(k, String(v));
    });
    return get<EventsPage>(`/api/events?${qs.toString()}`, mockEvents(params));
  },
  event: (id: number) =>
    get<{ event: EventItem }>(`/api/events/${id}`, {
      event: mockEvents({}).items.find((e) => e.id === id) || mockEvents({}).items[0],
    }),
  watchlist: () => get<WatchlistCompany[]>(`/api/watchlist`, mockWatchlist),
  marketWatchlist: () =>
    get<MarketWatchlistPage>(`/api/market/watchlist`, {
      items: [],
      source_note: "Market data unavailable while offline.",
    }),
  sourceHealth: () => get<SourceHealth[]>(`/api/source-health`, mockSourceHealth),
  operatorEntities: (statuses?: OperatorStatus[]) => {
    const qs = new URLSearchParams();
    statuses?.forEach((status) => qs.append("status", status));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    const fallback = statuses?.length
      ? { ...mockOperatorEntities, items: mockOperatorEntities.items.filter((item) => statuses.includes(item.status)) }
      : mockOperatorEntities;
    return get<OperatorEntitiesPage>(`/api/operator/entities${suffix}`, fallback);
  },
  operatorEntity: (entityKey: string) =>
    get<OperatorEntityDetail>(
      `/api/operator/entities/${encodeURIComponent(entityKey)}`,
      mockOperatorDetail,
    ),
  operatorDeadlines: () =>
    get<OperatorDeadlinesPage>(`/api/operator/deadlines`, mockOperatorDeadlines),
};

export { BASE as API_BASE };
