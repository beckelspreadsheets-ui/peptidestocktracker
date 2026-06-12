import { mockBriefing, mockEvents, mockWatchlist, mockSourceHealth } from "./mock";
import type { Briefing, EventItem, EventsPage, SourceHealth, WatchlistCompany } from "./types";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) || "http://localhost:8000";

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
  sourceHealth: () => get<SourceHealth[]>(`/api/source-health`, mockSourceHealth),
};

export { BASE as API_BASE };
