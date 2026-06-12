import { useState } from "react";
import { Route, Routes } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { CommandPalette } from "./components/CommandPalette";
import { EventDrawerProvider } from "./components/eventDrawer";
import { Dashboard } from "./pages/Dashboard";
import { Events } from "./pages/Events";
import { Watchlist } from "./pages/Watchlist";
import { SourceHealth } from "./pages/SourceHealth";
import { useFetch } from "./hooks/useFetch";
import { api } from "./lib/api";
import type { Briefing, WatchlistCompany } from "./lib/types";

export default function App() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [meta, setMeta] = useState<{ generatedAt?: string; live: boolean }>({ live: false });

  // lightweight global data for the command palette
  const { data: watchlist } = useFetch<WatchlistCompany[]>(() => api.watchlist(), []);
  const peptideIds = Array.from(
    new Set((watchlist || []).flatMap((c) => c.peptides)),
  ).slice(0, 12);

  const onLive = (b: Briefing, live: boolean) =>
    setMeta((m) =>
      m.generatedAt === b.generated_at && m.live === live ? m : { generatedAt: b.generated_at, live },
    );

  return (
    <EventDrawerProvider>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar live={meta.live} generatedAt={meta.generatedAt} onOpenSearch={() => setPaletteOpen(true)} />
          <main className="flex-1 overflow-y-auto px-4 py-5 sm:px-6">
            <div className="mx-auto max-w-[1240px]">
              <Routes>
                <Route path="/" element={<Dashboard onLive={onLive} />} />
                <Route path="/events" element={<Events />} />
                <Route path="/watchlist" element={<Watchlist />} />
                <Route path="/health" element={<SourceHealth />} />
              </Routes>
            </div>
          </main>
        </div>
      </div>
      <CommandPalette
        open={paletteOpen}
        setOpen={setPaletteOpen}
        watchlist={watchlist || []}
        peptides={peptideIds}
      />
    </EventDrawerProvider>
  );
}
