import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./hooks/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0b0f17",
          900: "#111722",
          850: "#171f2c",
          800: "#1d2735",
          700: "#2a3648",
        },
        signal: {
          300: "#83f7df",
          400: "#42e8c4",
          500: "#19c8a5",
          600: "#0ba184",
        },
        pulse: {
          400: "#8a8cff",
          500: "#6668f5",
          600: "#5052d9",
        },
      },
      boxShadow: {
        panel: "0 18px 60px rgba(0, 0, 0, 0.32)",
        glow: "0 0 0 1px rgba(66, 232, 196, 0.18), 0 0 36px rgba(25, 200, 165, 0.08)",
      },
      borderRadius: {
        panel: "1.25rem",
      },
      transitionTimingFunction: {
        spring: "cubic-bezier(0.16, 1, 0.3, 1)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "SFMono-Regular", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
