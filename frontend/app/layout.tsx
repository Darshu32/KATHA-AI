import type { Metadata } from "next";
import { Newsreader, JetBrains_Mono } from "next/font/google";
import localFont from "next/font/local";
import "./globals.css";
import ToastViewport from "@/components/primitives/toast-viewport";

/* Type system.
 * Avenir LT Pro → company brand font. Used everywhere as the primary
 *                 sans for UI chrome (chat, labels, controls, headings,
 *                 body) so the platform matches the website + documents.
 *                 Self-hosted via next/font/local (no external request —
 *                 good for EU privacy / GDPR). Only the Roman (400) weight
 *                 ships today; heavier/lighter weights are synthesised by
 *                 the browser until their own face files are added.
 * Newsreader    → opt-in editorial serif via `.font-display`. Retained
 *                 for the /design surface's remaining editorial moments
 *                 until that surface's redesign lands; not used on chat.
 * JetBrains Mono → technical surfaces (terminal, cost stream, generation
 *                 log, citation refs, dimensional data, code refs).
 *                 Purpose-built for engineering tools — precise letter-
 *                 forms, strong tabular numbers. Kept monospace because
 *                 Avenir cannot hold tabular column alignment.
 *
 * Newsreader + JetBrains Mono load via next/font/google on the build side
 * rather than the client. CSS variables flow into Tailwind's font tokens.
 */
const avenir = localFont({
  src: "./fonts/AvenirLTPro-Roman.ttf",
  weight: "400",
  style: "normal",
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
  title: "KATHA AI — design AI for architects",
  description:
    "An AI workspace for architecture, interior, furniture and product design. Brief in, complete deliverable out.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${avenir.variable} ${newsreader.variable} ${jetbrainsMono.variable}`}
    >
      <body className="antialiased">
        {children}
        <ToastViewport />
      </body>
    </html>
  );
}
