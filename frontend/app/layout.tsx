import type { Metadata } from "next";
import { Inter, Newsreader, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

/* Type system — Claude-inspired editorial.
 * Inter      → UI body / chat / labels (clean sans, dense, neutral)
 * Newsreader → display headlines only (editorial serif, optical-sized)
 * Plex Mono  → technical surfaces (cost terminal, code, mono labels)
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

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["300", "400", "500"],
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
      className={`${inter.variable} ${newsreader.variable} ${plexMono.variable}`}
    >
      <body className="antialiased">{children}</body>
    </html>
  );
}
