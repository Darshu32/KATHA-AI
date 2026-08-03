"use client";

/* KATHA landing — first pass.
 *
 * Brand register carried straight from the app: white paper, near-black ink,
 * Avenir (font-sans) with JetBrains Mono (font-mono) for the technical layer,
 * a single pencil-red accent. The hero is a live R3F massing model (see
 * hero-scene). Content is intentionally lean — the *type* of landing page is
 * a later decision; this establishes the visual foundation. */

import Link from "next/link";
import dynamic from "next/dynamic";
import { motion, useReducedMotion } from "framer-motion";

// three.js is client-only; load the scene after mount with a quiet paper
// placeholder so the shell never blocks on it.
const HeroScene = dynamic(() => import("@/components/landing/hero-scene"), {
  ssr: false,
  loading: () => <div className="h-full w-full animate-pulse rounded-xl bg-paper-soft" />,
});

const FEATURES: { k: string; h: string; p: string }[] = [
  { k: "01 · BRIEF", h: "Describe it in plain language", p: "An agent captures type, space, requirements and code context as you talk." },
  { k: "02 · DESIGN", h: "Checked as it's drawn", p: "Cost, building codes, MEP and ergonomics validate inline — not after the fact." },
  { k: "03 · DELIVER", h: "Real drawings, automatically", p: "5 working drawings and 8 analysis diagrams, generated from the design graph." },
  { k: "04 · HAND OFF", h: "Built to leave KATHA", p: "Export to IFC, DXF, STEP, FBX and 13 more — Revit, AutoCAD and ArchiCAD ready." },
];

export default function Landing() {
  const reduce = useReducedMotion();
  const rise = (delay: number) => ({
    initial: { opacity: 0, y: reduce ? 0 : 16 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.6, delay, ease: [0.32, 0.72, 0, 1] as const },
  });

  return (
    <div className="min-h-screen bg-paper text-ink font-sans">
      {/* ── Nav ─────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-30 border-b border-hairline bg-paper/85 backdrop-blur-sm">
        <nav className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <Link href="/" className="flex items-baseline gap-1.5">
            <span className="text-[1.15rem] font-semibold tracking-tight text-ink-deep">KATHA</span>
            <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-pencil">AI</span>
          </Link>
          <div className="hidden items-center gap-8 font-mono text-[11px] uppercase tracking-[0.14em] text-ink-soft sm:flex">
            <a href="#how" className="transition-colors hover:text-ink">How it works</a>
            <a href="#exports" className="transition-colors hover:text-ink">Exports</a>
            <Link href="/design" className="transition-colors hover:text-ink">Studio</Link>
          </div>
          <Link
            href="/chat"
            className="rounded-md bg-ink-deep px-4 py-2 text-[13px] font-medium text-paper transition-colors hover:bg-ink"
          >
            Open KATHA
          </Link>
        </nav>
      </header>

      {/* ── Hero ────────────────────────────────────────────────────────── */}
      <section className="relative mx-auto grid max-w-6xl grid-cols-1 items-center gap-6 px-6 pb-10 pt-12 lg:grid-cols-[1.05fr_1fr] lg:gap-4 lg:pt-20">
        <div>
          <motion.p {...rise(0)} className="font-mono text-[11px] uppercase tracking-[0.22em] text-pencil">
            The universal OS for architects
          </motion.p>
          <motion.h1
            {...rise(0.08)}
            className="mt-5 text-balance text-[2.6rem] font-semibold leading-[1.03] tracking-[-0.02em] text-ink-deep sm:text-[3.4rem] lg:text-[3.8rem]"
          >
            From a sentence to a{" "}
            <span className="font-display italic font-normal text-pencil">buildable</span> design.
          </motion.h1>
          <motion.p {...rise(0.16)} className="mt-6 max-w-[46ch] text-[1.05rem] leading-relaxed text-ink-soft">
            Brief a project in plain language. KATHA returns a costed, code-checked design — with
            working drawings, analysis diagrams, and BIM-ready exports to the tools you already use.
          </motion.p>
          <motion.div {...rise(0.24)} className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              href="/chat"
              className="group inline-flex items-center gap-2 rounded-md bg-pencil px-5 py-3 text-[14px] font-medium text-paper transition-colors hover:bg-pencil-soft"
            >
              Open KATHA
              <span className="transition-transform group-hover:translate-x-0.5">&rarr;</span>
            </Link>
            <Link
              href="/design"
              className="inline-flex items-center rounded-md border border-graphite px-5 py-3 text-[14px] font-medium text-ink transition-colors hover:border-ink"
            >
              Explore the studio
            </Link>
          </motion.div>
          <motion.p {...rise(0.32)} className="mt-6 font-mono text-[10.5px] uppercase tracking-[0.14em] text-ink-mute">
            IFC · DXF · STEP · FBX · Revit-ready · 17 formats
          </motion.p>
        </div>

        {/* Live massing model */}
        <motion.div
          {...rise(0.1)}
          className="h-[380px] w-full sm:h-[460px] lg:h-[600px]"
        >
          <HeroScene />
        </motion.div>
      </section>

      {/* ── How it works ────────────────────────────────────────────────── */}
      <section id="how" className="border-t border-hairline">
        <div className="mx-auto max-w-6xl px-6 py-16">
          <div className="mb-10 flex items-end justify-between gap-6">
            <h2 className="text-balance text-[1.6rem] font-semibold tracking-[-0.015em] text-ink-deep sm:text-[2rem]">
              One line in. A design set out.
            </h2>
            <span id="exports" className="hidden font-mono text-[11px] uppercase tracking-[0.14em] text-ink-mute sm:block">
              Brief &rarr; Design &rarr; Deliver &rarr; Hand off
            </span>
          </div>
          <div className="grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-hairline bg-hairline sm:grid-cols-2 lg:grid-cols-4">
            {FEATURES.map((f) => (
              <div key={f.k} className="bg-paper p-6 transition-colors hover:bg-paper-soft">
                <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-pencil">{f.k}</p>
                <h3 className="mt-3 text-[1.05rem] font-semibold leading-snug text-ink-deep">{f.h}</h3>
                <p className="mt-2 text-[13.5px] leading-relaxed text-ink-soft">{f.p}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Closing CTA ─────────────────────────────────────────────────── */}
      <section className="border-t border-hairline bg-paper-soft">
        <div className="mx-auto flex max-w-6xl flex-col items-start gap-6 px-6 py-16 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-balance text-[1.6rem] font-semibold tracking-[-0.015em] text-ink-deep sm:text-[2rem]">
              Design the first one in a sentence.
            </h2>
            <p className="mt-2 max-w-[48ch] text-[1rem] leading-relaxed text-ink-soft">
              Open the conversation and describe what you're building. KATHA takes it from there.
            </p>
          </div>
          <Link
            href="/chat"
            className="inline-flex shrink-0 items-center gap-2 rounded-md bg-ink-deep px-6 py-3.5 text-[14px] font-medium text-paper transition-colors hover:bg-ink"
          >
            Start designing
            <span aria-hidden>&rarr;</span>
          </Link>
        </div>
      </section>

      {/* ── Footer ──────────────────────────────────────────────────────── */}
      <footer className="border-t border-hairline">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-6 py-8 sm:flex-row">
          <div className="flex items-baseline gap-1.5">
            <span className="font-semibold tracking-tight text-ink-deep">KATHA</span>
            <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-pencil">AI</span>
          </div>
          <p className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-ink-mute">
            The universal OS for architects
          </p>
        </div>
      </footer>
    </div>
  );
}
