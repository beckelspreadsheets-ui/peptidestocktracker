# peptide-watch cockpit (dashboard)

A fast, dense research dashboard for the peptide-watch tracker. Dark "instrument" UI:
cool-cyan interface chrome, warm severity colors used only as signal, Hanken Grotesk + IBM
Plex Mono. It reads the **read-only** peptide-watch API (`peptide-watch serve`).

## Run

```bash
# 1) start the API (from the repo root)
uv sync --extra web
uv run peptide-watch serve            # http://localhost:8000, localhost-bound

# 2) start the dashboard (from this dir)
npm install
npm run dev                            # http://localhost:3000
```

Point at a non-default API with `VITE_API_BASE` (see `.env.example`). If the API is
unreachable the UI renders sample data and shows a "SAMPLE" badge instead of "LIVE".

On a VPS, reach both over an SSH tunnel:
`ssh -L 3000:localhost:3000 -L 8000:localhost:8000 vps`, then open `localhost:3000`.

Production build: `npm run build` → static `dist/` (serve behind any static host / reverse
proxy on the same machine as the API).

## Navigation

- **⌘K / Ctrl-K** — command palette: jump to any company, ticker, peptide, or screen.
- **Detail drawers** — click any event/row; review evidence without leaving the list.
- **Keyboard triage** (events feed) — `j`/`k` move, `Enter` opens, `Esc` closes.
- **New since last visit** — events newer than your last "mark all seen" get a cyan marker.

## Screens

Cockpit (ranked briefing + discovery queue + regulatory doors w/ countdowns + shortages +
source health) · Events (filters + drawer) · Watchlist · Source health.

Every view carries the compliance footer. The UI renders only public-source facts and
contains no buy/sell or recommendation language by construction.
