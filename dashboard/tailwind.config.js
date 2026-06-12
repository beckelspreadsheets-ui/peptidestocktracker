/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["'Hanken Grotesk'", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "monospace"],
      },
      colors: {
        base: "#0a0c0f",
        panel: "#0f1318",
        "panel-2": "#141a21",
        "panel-3": "#1a212a",
        line: "#222a33",
        "line-strong": "#303b46",
        ink: "#e7eef5",
        "ink-2": "#9aa8b4",
        "ink-3": "#5d6b78",
        accent: "#2dd4bf",
        "accent-bright": "#5eead4",
        "accent-dim": "#10302d",
        crit: "#f0506b",
        high: "#f59042",
        med: "#e0b341",
        low: "#6b7785",
        ok: "#46c97a",
        review: "#e0b341",
      },
      boxShadow: {
        drawer: "-24px 0 60px -20px rgba(0,0,0,0.7)",
        panel: "0 1px 0 0 rgba(255,255,255,0.02), 0 12px 30px -18px rgba(0,0,0,0.6)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.4s cubic-bezier(0.2,0.7,0.2,1) both",
      },
    },
  },
  plugins: [],
};
