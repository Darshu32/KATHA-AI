import type { Metadata } from "next";
import { Inter, Newsreader, JetBrains_Mono } from "next/font/google";
import "./globals.css";

/* Type system.
 * Inter         → UI chrome (chat, labels, controls, headings).
 * Newsreader    → opt-in editorial serif via `.font-display`. Retained
 *                 for the /design surface's remaining editorial moments
 *                 until that surface's redesign lands; not used on chat.
 * JetBrains Mono → technical surfaces (terminal, cost stream, generation
 *                 log, citation refs, dimensional data, code refs).
 *                 Purpose-built for engineering tools — precise letter-
 *                 forms, strong tabular numbers, less branded than Plex.
 *
 * All three are loaded via next/font/google for performance and to keep
 * Google Fonts requests on the build side rather than the client (better
 * for EU privacy / GDPR). CSS variables flow into Tailwind's font tokens.
 */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const newsreader = Newsreader({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
  style: ["normal", "italic"],
  variable: "--font-display",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "KATHA — design AI for architects",
  description:
    "An AI workspace for architecture, interior, furniture and product design. Brief in, complete deliverable out.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${newsreader.variable} ${jetbrainsMono.variable}`}
    >
      <body className="antialiased">{children}</body>
    </html>
  );
}
