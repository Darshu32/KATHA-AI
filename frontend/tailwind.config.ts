import type { Config } from "tailwindcss";

/* KATHA AI — Design tokens.
 *
 * Chat surface (white-AI-agent register): pure-white surfaces, neutral
 * cool grays for hierarchy, near-black ink, Inter throughout. Single
 * pencil-red accent (the red architects mark drawings with) for live
 * links, cited values, and destructive states. Mono scoped to numeric
 * data and callout numerals.
 *
 * Design surface (`/design`) retains the editorial register — Newsreader
 * via `.font-display`, terracotta/brass/indigo accents, paper-card and
 * brass-rule primitives. Those tokens stay defined so design keeps
 * rendering until its own redesign pass.
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
        // Paper — backgrounds. Pure-white canvas with neutral cool grays
        // for inset surfaces. The 4-level scale supports surface
        // elevation without warm tints.
        paper: {
          DEFAULT: "#FFFFFF",
          soft: "#FAFAFA",
          deep: "#F2F2F2",
          edge: "#E8E8E8",
        },
        // Ink — text. Four neutral levels: primary, secondary, tertiary,
        // muted. Cool near-black, not warm; pairs with white surfaces.
        ink: {
          DEFAULT: "#1A1A1A",
          deep: "#0A0A0A",
          soft: "#6B6B6B",
          mute: "#A0A0A0",
        },
        // Hairlines / rules — cool neutral gray. Three weights for the
        // border progression; chat leans on the softest two.
        hairline: "#EAEAEA",
        graphite: {
          DEFAULT: "#D4D4D4",
          soft: "#F0F0F0",
        },
        // Pencil — the single accent on chat. The red architects use
        // for markup and as-built notes. Reserved for live links, cited
        // dimensional data, and destructive actions.
        pencil: {
          DEFAULT: "#C8362D",
          soft: "#D86054",
          bg: "#FAEAE7",
        },
        // Editorial accents — kept defined for the /design surface
        // until it receives its own redesign. Not used on chat.
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
