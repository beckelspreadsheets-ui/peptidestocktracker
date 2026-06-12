import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect } from "react";

export function Drawer({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="fixed inset-0 z-40 bg-black/55 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            className="fixed right-0 top-0 z-50 flex h-full w-full max-w-[540px] flex-col border-l border-line-strong bg-panel shadow-drawer"
            initial={{ x: 48, opacity: 0.6 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 48, opacity: 0 }}
            transition={{ type: "spring", stiffness: 420, damping: 38 }}
          >
            <header className="flex items-center justify-between border-b border-line px-5 py-3.5">
              <div className="min-w-0 font-mono text-[11px] uppercase tracking-[0.18em] text-ink-2">
                {title}
              </div>
              <button
                onClick={onClose}
                className="focusable rounded p-1 text-ink-3 transition hover:bg-panel-2 hover:text-ink"
                aria-label="Close (Esc)"
              >
                <X size={16} />
              </button>
            </header>
            <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
