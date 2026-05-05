import type { Config } from "tailwindcss";

/* KATHA AI — Editorial design system tokens (Claude-inspired).
 * Sans body (Inter) for UI density and readability.
 * Serif display (Newsreader) for hero / page-title moments only.
 * Mono (IBM Plex Mono) for technical surfaces — cost terminal, code, labels.
 *
 * Palette is warm-cream paper with near-black warm ink, terracotta as the
 * single primary accent, brass for data, indigo as a quiet secondary.
 * No gridpaper on UI surfaces — that lives only on the design canvas.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: [
          "var(--font-display)",
          "ui-serif",
          "Georgia",
          "Times New Roman",
          "serif",
        ],
        mono: [
          "var(--font-mono)",
          "ui-monospace",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      colors: {
        // Paper — backgrounds. White theme: main is #FFFFFF; layered
        // surfaces use neutral grays for hierarchy.
        paper: {
          DEFAULT: "#FFFFFF",
          soft: "#FAFAF9",
          deep: "#F2F2F0",
          edge: "#E8E8E5",
        },
        // Ink — text. Warm near-black so the page reads editorial
        // rather than clinical despite the white background.
        ink: {
          DEFAULT: "#2A2620",
          deep: "#1A1814",
          soft: "#5A554F",
          mute: "#8B867F",
        },
        // Hairlines / fine rules — neutral gray.
        hairline: "#E5E5E2",
        graphite: {
          DEFAULT: "#D0D0CC",
          soft: "#ECECE9",
        },
        // Accents — kept from existing palette but used sparingly.
        terracotta: {
          DEFAULT: "#A8451B",
          soft: "#D77A50",
          bg: "#F2DFCE",
        },
        brass: {
          DEFAULT: "#9F7E4F",
          soft: "#C2A375",
          bg: "#EFE5CE",
        },
        indigo: {
          DEFAULT: "#3D4F7A",
          soft: "#6B7CA0",
        },
        // Semantic
        olive: "#3F4E2D",
        mustard: "#B57F2A",
        brick: "#8B2D2D",
      },
      letterSpacing: {
        tagged: "0.14em",
        wider2: "0.10em",
      },
      maxWidth: {
        chat: "44rem", // ~704px — Claude-style centered conversation
        notes: "28rem",
        hero: "62rem",
      },
      boxShadow: {
        card: "0 1px 0 rgba(26, 24, 20, 0.04), 0 1px 2px rgba(26, 24, 20, 0.05)",
        inset: "inset 0 0 0 1px #DAD3C2",
      },
      transitionTimingFunction: {
        snap: "cubic-bezier(0.4, 0, 0.18, 1)",
        editorial: "cubic-bezier(0.32, 0.72, 0, 1)",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-in": "fadeIn 280ms cubic-bezier(0.32, 0.72, 0, 1) both",
      },
    },
  },
  plugins: [],
};

export default config;
