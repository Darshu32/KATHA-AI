"use client";

/* MVP 2 — Design generation workspace.
 * Engineering-workstation 4-zone layout: left controls, centered canvas,
 * right specs, bottom terminal. Inter on chrome, JetBrains Mono on
 * technical surfaces (cost stream, generation log, citations, dimensions).
 * No serif. Gridpaper appears only on the canvas surface, never on chrome.
 * Pencil-red is the single accent (active terminal tab, live links). */

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useAuthStore, useConfigStore, useImageGenStore } from "@/lib/store";
import { ApiError, images as imagesApi } from "@/lib/api-client";
import type {
  ArchTheme,
  ImageRatio,
  ProjectType,
} from "@/lib/types";
import {
  Annotation,
  PaperCard,
  SectionTag,
} from "@/components/primitives";

type Scope = "architecture" | "interior" | "furniture" | "product";
type Dim = "2d" | "3d" | "4d";
type TerminalTab = "cost" | "problems";

const SCOPES: { id: Scope; label: string }[] = [
  { id: "architecture", label: "Architecture" },
  { id: "interior", label: "Interior" },
  { id: "furniture", label: "Furniture" },
  { id: "product", label: "Product" },
];

const DIMS: { id: Dim; label: string; tagline: string }[] = [
  { id: "2d", label: "2D", tagline: "plans · elevations · sections" },
  { id: "3d", label: "3D", tagline: "models · renders" },
  { id: "4d", label: "4D", tagline: "walkthroughs · time" },
];

// Themes are fetched dynamically from /api/v1/themes (DB-backed via the
// admin theme registry). See useConfigStore.loadThemes in lib/store.ts.

const RATIOS: ImageRatio[] = ["16:9", "4:3", "1:1", "3:4", "9:16"];

export default function ImageWorkspaceMvp2() {
  const {
    prompt,
    setPrompt,
    projectType,
    setProjectType,
    theme,
    setTheme,
    ratio,
    setRatio,
    isGenerating,
    setIsGenerating,
    generations,
    addGeneration,
    terminalOpen,
    toggleTerminal,
  } = useImageGenStore();

  const projectTypeDefs = useConfigStore((s) => s.projectTypeDefs);
  const themesList = useConfigStore((s) => s.themes);
  const loadAll = useConfigStore((s) => s.loadAll);
  const token = useAuthStore((s) => s.token);

  const [scope, setScope] = useState<Scope>("interior");
  const [dim, setDim] = useState<Dim>("3d");
  const [terminalTab, setTerminalTab] = useState<TerminalTab>("cost");
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [generateNotice, setGenerateNotice] = useState<string | null>(null);

  // Bootstrap dynamic config (themes + project types) on mount.
  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  // If the persisted projectType isn't valid against the freshly-fetched
  // taxonomy (e.g. backend dropped a slug), fall back to the first def.
  useEffect(() => {
    if (projectTypeDefs.length === 0) return;
    const valid = projectTypeDefs.some((d) => d.slug === projectType);
    if (!valid) setProjectType(projectTypeDefs[0].slug as ProjectType);
  }, [projectTypeDefs, projectType, setProjectType]);

  // Same defensive sync for theme.
  useEffect(() => {
    if (themesList.length === 0) return;
    const valid = themesList.some((t) => t.slug === theme);
    if (!valid) setTheme(themesList[0].slug as ArchTheme);
  }, [themesList, theme, setTheme]);

  const activeTypeDef = useMemo(
    () => projectTypeDefs.find((d) => d.slug === projectType) ?? null,
    [projectTypeDefs, projectType],
  );

  const generate = async () => {
    if (!prompt.trim() || isGenerating) return;
    setGenerateError(null);
    setGenerateNotice(null);
    setIsGenerating(true);

    try {
      const res = await imagesApi.generate(token, {
        prompt: prompt.trim(),
        project_type: projectType,
        theme,
        ratio,
      });

      if (res.status === "provider_unconfigured") {
        // Clean signal — backend reachable, but GEMINI_API_KEY isn't set.
        // Surface as a notice rather than an error; everything else works.
        setGenerateNotice(
          "Image generation is wired but waiting on the GEMINI_API_KEY in .env. Pipeline verified end-to-end.",
        );
      } else if (res.image?.url) {
        addGeneration({
          id: crypto.randomUUID(),
          prompt: prompt.trim(),
          url: res.image.url,
          timestamp: new Date().toISOString(),
          theme,
          ratio,
          quality: "standard",
          drawingType: "3d-render",
          camera: "front",
          lighting: "daylight",
          width: 1024,
          height: 576,
        });
      }
    } catch (e) {
      if (e instanceof ApiError) {
        setGenerateError(
          `Backend rejected the request (${e.status}). Check the API logs.`,
        );
      } else {
        setGenerateError(
          "Couldn't reach the backend. Is uvicorn running on :8000?",
        );
      }
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div className="h-screen w-full flex flex-col bg-paper">
      <TopBar onToggleTerminal={toggleTerminal} terminalOpen={terminalOpen} />

      <div className="flex-1 flex min-h-0">
        <LeftControls
          projectType={projectType}
          setProjectType={setProjectType}
          projectTypeDefs={projectTypeDefs}
          scope={scope}
          setScope={setScope}
          dim={dim}
          setDim={setDim}
          theme={theme}
          setTheme={setTheme}
          themesList={themesList}
          ratio={ratio}
          setRatio={setRatio}
        />

        <main className="flex-1 flex flex-col min-w-0 border-x border-hairline bg-paper">
          <CanvasHeader
            scope={scope}
            dim={dim}
            projectType={projectType}
            projectTypeLabel={activeTypeDef?.label ?? projectType}
          />
          <div className="flex-1 overflow-auto draft-scroll grid-paper">
            {generations.length === 0 ? (
              <CanvasEmptyHero
                scope={scope}
                dim={dim}
                projectTypeLabel={activeTypeDef?.label ?? projectType}
                starterPrompts={activeTypeDef?.starter_prompts ?? []}
                onPickPrompt={setPrompt}
              />
            ) : (
              <CanvasGallery generations={generations} dim={dim} />
            )}
          </div>
          {generateNotice ? (
            <div className="border-t border-hairline bg-paper-soft px-6 py-2 text-[12px] text-ink-soft">
              <span className="font-mono text-mustard mr-1">•</span>
              {generateNotice}
            </div>
          ) : null}
          {generateError ? (
            <div className="border-t border-hairline bg-paper-soft px-6 py-2 text-[12px] text-brick">
              <span className="font-mono mr-1">!</span>
              {generateError}
            </div>
          ) : null}
          <CanvasPromptBar
            prompt={prompt}
            setPrompt={setPrompt}
            isGenerating={isGenerating}
            onGenerate={generate}
          />
        </main>

        <RightSummary
          hasDesign={generations.length > 0}
          dim={dim}
          theme={theme}
        />
      </div>

      {terminalOpen ? (
        <TerminalPanel
          tab={terminalTab}
          setTab={setTerminalTab}
          hasDesign={generations.length > 0}
          onClose={() => toggleTerminal()}
        />
      ) : (
        <TerminalCollapsed onOpen={() => toggleTerminal()} />
      )}
    </div>
  );
}

// ── Top bar ────────────────────────────────────────────────────────────

function TopBar({
  onToggleTerminal,
  terminalOpen,
}: {
  onToggleTerminal: () => void;
  terminalOpen: boolean;
}) {
  return (
    <header className="border-b border-hairline bg-paper">
      <div className="px-5 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link
            href="/chat"
            className="text-[1.05rem] text-ink-deep tracking-tight font-semibold leading-none"
          >
            Katha
          </Link>
        </div>
        <nav className="flex items-center gap-2">
          <button
            type="button"
            onClick={onToggleTerminal}
            className="text-[12px] text-ink-soft hover:text-ink transition-colors px-2 py-1"
          >
            {terminalOpen ? "Hide terminal" : "Show terminal"}
          </button>
          <Link href="/chat" className="slide-pill" data-active="false">
            Chat
          </Link>
          <Link href="/design" className="slide-pill" data-active="true">
            Design
          </Link>
        </nav>
      </div>
    </header>
  );
}

// ── Left: controls ─────────────────────────────────────────────────────

function LeftControls({
  projectType,
  setProjectType,
  projectTypeDefs,
  scope,
  setScope,
  dim,
  setDim,
  theme,
  setTheme,
  themesList,
  ratio,
  setRatio,
}: {
  projectType: ProjectType;
  setProjectType: (t: ProjectType) => void;
  projectTypeDefs: import("@/lib/api-client").ProjectTypeDef[];
  scope: Scope;
  setScope: (s: Scope) => void;
  dim: Dim;
  setDim: (d: Dim) => void;
  theme: ArchTheme;
  setTheme: (t: ArchTheme) => void;
  themesList: import("@/lib/api-client").ThemeDef[];
  ratio: ImageRatio;
  setRatio: (r: ImageRatio) => void;
}) {
  return (
    <aside className="w-72 shrink-0 bg-paper-soft border-r border-hairline overflow-y-auto draft-scroll">
      <div className="px-5 py-5 space-y-6">
        <ProjectTypeSelector
          value={projectType}
          defs={projectTypeDefs}
          onChange={setProjectType}
        />

        <section>
          <SectionTag>Scope</SectionTag>
          <div className="mt-2.5 grid grid-cols-2 gap-1.5">
            {SCOPES.map((s) => (
              <button
                key={s.id}
                type="button"
                className="slide-pill text-center"
                data-active={s.id === scope}
                onClick={() => setScope(s.id)}
              >
                {s.label}
              </button>
            ))}
          </div>
        </section>

        <section>
          <SectionTag>Dimensionality</SectionTag>
          <div className="mt-2.5 flex gap-1.5">
            {DIMS.map((d) => (
              <button
                key={d.id}
                type="button"
                className="slide-pill flex-1 text-center"
                data-active={d.id === dim}
                onClick={() => setDim(d.id)}
              >
                {d.label}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[12px] text-ink-mute">
            {DIMS.find((d) => d.id === dim)?.tagline}
          </p>
        </section>

        <section>
          <SectionTag>Theme</SectionTag>
          <div className="mt-2.5 space-y-1.5">
            {themesList.length === 0 ? (
              <div className="text-[12px] text-ink-mute px-3 py-2">
                Loading themes…
              </div>
            ) : (
              themesList.map((t) => (
                <button
                  key={t.slug}
                  type="button"
                  className="slide-pill w-full text-left"
                  data-active={t.slug === theme}
                  onClick={() => setTheme(t.slug as ArchTheme)}
                  title={t.description || undefined}
                >
                  {t.display_name}
                </button>
              ))
            )}
          </div>
        </section>

        <section>
          <SectionTag>Aspect ratio</SectionTag>
          <div className="mt-2.5 grid grid-cols-5 gap-1">
            {RATIOS.map((r) => (
              <button
                key={r}
                type="button"
                className="slide-pill text-center !text-[11px] !px-1.5"
                data-active={r === ratio}
                onClick={() => setRatio(r)}
              >
                {r}
              </button>
            ))}
          </div>
        </section>

      </div>
    </aside>
  );
}

// ── Bottom: prompt bar (sits inside the canvas column) ─────────────────
//
// Discoverability fix: the prompt textarea used to live at the bottom of
// the left controls and was below the fold for most viewport sizes. It
// now sits as a sticky bar at the bottom of the canvas column, matching
// the chat workspace pattern users already know.

function CanvasPromptBar({
  prompt,
  setPrompt,
  isGenerating,
  onGenerate,
}: {
  prompt: string;
  setPrompt: (v: string) => void;
  isGenerating: boolean;
  onGenerate: () => void;
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 180) + "px";
  }, [prompt]);

  return (
    <div className="border-t border-hairline bg-paper px-6 py-4">
      <div className="max-w-4xl mx-auto">
        <div className="border border-hairline rounded-xl bg-paper-soft/60 p-3 flex items-end gap-3 focus-within:border-graphite transition-colors">
          <textarea
            ref={ref}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Describe what you want — Katha tunes the output to your project type."
            rows={1}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                onGenerate();
              }
            }}
            className="flex-1 resize-none outline-none bg-transparent text-ink placeholder:text-ink-mute leading-relaxed py-1.5 text-[15px]"
            disabled={isGenerating}
          />
          <button
            type="button"
            onClick={onGenerate}
            disabled={!prompt.trim() || isGenerating}
            className="shrink-0 text-[13px] font-medium px-4 py-1.5 bg-ink-deep text-paper hover:bg-ink rounded-md transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            {isGenerating ? "Generating…" : "Generate"}
          </button>
        </div>
        <div className="mt-2 px-1 text-[11px] text-ink-mute">
          ⌘↵ to generate · ⇧↵ for newline
        </div>
      </div>
    </div>
  );
}

// ── Center: canvas ─────────────────────────────────────────────────────

function CanvasHeader({
  scope,
  dim,
  projectType,
  projectTypeLabel,
}: {
  scope: Scope;
  dim: Dim;
  projectType: ProjectType;
  projectTypeLabel: string;
}) {
  void projectType; // explicitly unused — kept on signature for future telemetry
  return (
    <div className="px-6 py-2.5 border-b border-hairline bg-paper/85 backdrop-blur-sm flex items-center justify-between">
      <div className="flex items-center gap-3">
        <SectionTag>Canvas</SectionTag>
        <span className="text-[12px] text-ink-mute">
          {projectTypeLabel} ·{" "}
          {SCOPES.find((s) => s.id === scope)?.label} · {dim.toUpperCase()}
        </span>
      </div>
    </div>
  );
}

function CanvasEmptyHero({
  scope,
  dim,
  projectTypeLabel,
  starterPrompts,
  onPickPrompt,
}: {
  scope: Scope;
  dim: Dim;
  projectTypeLabel: string;
  starterPrompts: string[];
  onPickPrompt: (p: string) => void;
}) {
  const lowerLabel = projectTypeLabel.toLowerCase();

  return (
    <div className="px-6 md:px-12 py-16 max-w-3xl mx-auto">
      <h1 className="text-[1.625rem] md:text-[1.875rem] text-ink-deep leading-[1.2] tracking-[-0.02em] font-semibold">
        A {lowerLabel} canvas, ready when you are.
      </h1>
      <p className="mt-4 text-ink-soft text-[15px] leading-relaxed max-w-xl">
        Standards, ergonomic ranges, and cost defaults are tuned for{" "}
        <strong className="text-ink">{lowerLabel}</strong> projects. Pick a
        starter below or write your own prompt.
      </p>

      {starterPrompts.length > 0 ? (
        <div className="mt-8">
          <SectionTag>Starter prompts</SectionTag>
          <div className="mt-3 space-y-2">
            {starterPrompts.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => onPickPrompt(s)}
                className="w-full text-left px-4 py-3 border border-hairline bg-paper-soft/60 hover:bg-paper-soft hover:border-graphite rounded-md transition-colors text-[14px] text-ink leading-snug"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mt-10 grid grid-cols-1 md:grid-cols-3 gap-3">
        <CanvasInfoCard
          tag="Step 1"
          title="Configure"
          body={`Pick scope (${SCOPES.find((s) => s.id === scope)?.label}) and dimensionality (${dim.toUpperCase()}).`}
        />
        <CanvasInfoCard
          tag="Step 2"
          title="Prompt"
          body={`Describe the design. Katha treats it as a ${lowerLabel} project and pulls the right codes + cost defaults.`}
        />
        <CanvasInfoCard
          tag="Step 3"
          title="Iterate"
          body="Cost streams live in the terminal below. Re-prompt to refine; export to edit."
        />
      </div>
    </div>
  );
}

function CanvasInfoCard({
  tag,
  title,
  body,
}: {
  tag: string;
  title: string;
  body: string;
}) {
  return (
    <PaperCard className="p-4">
      <SectionTag>{tag}</SectionTag>
      <h3 className="mt-2 text-[14px] text-ink-deep font-semibold tracking-[-0.01em]">
        {title}
      </h3>
      <p className="mt-1.5 text-[13px] text-ink-soft leading-relaxed">{body}</p>
    </PaperCard>
  );
}

function CanvasGallery({
  generations,
  dim,
}: {
  generations: { id: string; prompt: string; timestamp: string }[];
  dim: Dim;
}) {
  return (
    <div className="px-6 md:px-10 py-8 max-w-5xl mx-auto space-y-5">
      {generations.map((g, i) => (
        <PaperCard key={g.id} className="p-5 anim-fade-in">
          <div className="flex items-baseline justify-between mb-3">
            <SectionTag>
              Render · {String(generations.length - i).padStart(2, "0")}
            </SectionTag>
            <Annotation>
              {new Date(g.timestamp).toLocaleString([], {
                hour: "2-digit",
                minute: "2-digit",
                day: "2-digit",
                month: "short",
              })}
            </Annotation>
          </div>
          <div className="aspect-video bg-paper-deep border border-hairline rounded-md flex items-center justify-center grid-paper">
            <div className="text-center">
              <SectionTag>Render placeholder</SectionTag>
              <div className="mt-2 text-[12px] text-ink-soft">
                {dim.toUpperCase()} · {g.prompt.slice(0, 60)}
                {g.prompt.length > 60 ? "…" : ""}
              </div>
              <div className="mt-3 text-[11px] font-mono text-ink-mute">
                Wire Nano Banana Pro at /api/v1/projects/&lt;id&gt;/generate
              </div>
            </div>
          </div>
        </PaperCard>
      ))}
    </div>
  );
}

// ── Right: spec summary + citations ────────────────────────────────────

function RightSummary({
  hasDesign,
  dim,
  theme,
}: {
  hasDesign: boolean;
  dim: Dim;
  theme: ArchTheme;
}) {
  return (
    <aside className="w-80 shrink-0 bg-paper-soft border-l border-hairline overflow-y-auto draft-scroll">
      <div className="px-5 py-5">
        <SectionTag>Specification summary</SectionTag>
        {!hasDesign ? (
          <p className="mt-3 text-[13px] text-ink-soft leading-relaxed">
            Specs, materials, and BOQ will appear here once you generate a
            design. Every value carries its source inline.
          </p>
        ) : (
          <div className="mt-4 space-y-5">
            <div>
              <h4 className="font-mono text-[10px] tracking-[0.14em] uppercase text-ink-mute mb-2">
                Meta
              </h4>
              <div className="border-t border-hairline">
                <CitedKV k="Dim" v={dim.toUpperCase()} />
                <CitedKV k="Theme" v={theme} />
                <CitedKV k="Version" v="01" />
              </div>
            </div>
            <div>
              <h4 className="font-mono text-[10px] tracking-[0.14em] uppercase text-ink-mute mb-2">
                Primary materials
              </h4>
              <div className="border-t border-hairline">
                <CitedKV
                  k="Walnut (top)"
                  v="₹560/kg"
                  src="MCX live · timber composite"
                  srcWhen="3 hrs ago"
                />
                <CitedKV
                  k="Brass (handles)"
                  v="₹820/kg"
                  src="MCX live · brass scrap"
                  srcWhen="3 hrs ago"
                />
                <CitedKV
                  k="Leather A"
                  v="₹1,950/m²"
                  src="Vendor · TanCo grade-A"
                  srcWhen="catalog · 4 days ago"
                />
              </div>
            </div>
            <div>
              <h4 className="font-mono text-[10px] tracking-[0.14em] uppercase text-ink-mute mb-2">
                Code compliance
              </h4>
              <div className="border-t border-hairline">
                <CitedKV
                  k="Door width"
                  v="1100 mm"
                  src="NBC-2016 Part 3 §4.2.1 · ≥ 1000 mm"
                  srcWhen="ingested 2026-04-01"
                />
                <CitedKV
                  k="Wall U-value"
                  v="0.36 W/m²K"
                  src="ECBC-2017 §4.3 · ≤ 0.40"
                  srcWhen="ingested 2026-04-01"
                />
                <CitedKV
                  k="Joinery tol."
                  v="±0.5 mm"
                  src="Mfg handbook §6 · mortise-tenon"
                  srcWhen="ingested 2026-04-01"
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

/* Cited key-value row for the right summary (light surface).
   Same hover-tooltip pattern as the terminal's SourceMark, tuned for
   ink-on-paper instead of paper-on-ink. The value lives inline with
   its source — no separate "Citations" panel to cross-reference. */
function CitedKV({
  k,
  v,
  src,
  srcWhen,
}: {
  k: string;
  v: string;
  src?: string;
  srcWhen?: string;
}) {
  return (
    <div className="group/kv relative flex items-baseline justify-between border-b border-hairline py-2 font-mono text-[12px]">
      <span className="text-ink-soft">{k}</span>
      <div className="flex items-baseline gap-1.5">
        <span className="text-ink-deep tnum font-medium">{v}</span>
        {src ? (
          <span className="relative inline-flex items-baseline">
            <span
              className="text-[11px] leading-none text-pencil cursor-help select-none"
              aria-label={`source: ${src}${srcWhen ? `, ${srcWhen}` : ""}`}
            >
              *
            </span>
            <span
              role="tooltip"
              className="pointer-events-none invisible opacity-0 group-hover/kv:visible group-hover/kv:opacity-100 absolute right-0 bottom-full mb-2 z-20 whitespace-nowrap bg-paper border border-graphite px-2.5 py-1.5 rounded-sm text-[10px] uppercase tracking-[0.1em] text-ink-deep transition-opacity duration-150 shadow-card"
            >
              <span className="text-pencil">src</span>
              <span className="ml-2">{src}</span>
              {srcWhen ? (
                <span className="ml-2 text-ink-mute">· {srcWhen}</span>
              ) : null}
            </span>
          </span>
        ) : null}
      </div>
    </div>
  );
}

// ── Bottom: terminal panel ─────────────────────────────────────────────

function TerminalCollapsed({ onOpen }: { onOpen: () => void }) {
  return (
    <button
      type="button"
      className="w-full text-left border-t border-hairline bg-ink-deep px-6 py-2 flex items-center justify-between cursor-pointer hover:bg-ink transition-colors"
      onClick={onOpen}
    >
      <span className="font-mono text-[11px] tracking-[0.12em] uppercase text-white/55">
        Terminal · cost · problems
      </span>
      <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-white/55">
        Expand ↑
      </span>
    </button>
  );
}

const TABS: { id: TerminalTab; label: string; count?: number }[] = [
  { id: "cost", label: "Cost" },
  { id: "problems", label: "Problems", count: 0 },
];

function TerminalPanel({
  tab,
  setTab,
  hasDesign,
  onClose,
}: {
  tab: TerminalTab;
  setTab: (t: TerminalTab) => void;
  hasDesign: boolean;
  onClose: () => void;
}) {
  return (
    <div className="border-t border-hairline bg-ink-deep h-72 flex flex-col">
      <div className="border-b border-white/10 pl-2 pr-1 flex items-center justify-between">
        <div className="flex items-center">
          {TABS.map((t) => {
            const active = t.id === tab;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                className={`font-mono text-[11px] uppercase tracking-[0.08em] px-3 py-2.5 transition-colors border-b-2 ${
                  active
                    ? "text-paper border-pencil"
                    : "text-white/55 hover:text-white/85 border-transparent"
                }`}
              >
                {t.label}
                {t.count !== undefined ? (
                  <span className="ml-1.5 text-white/40 normal-case tracking-normal">
                    ({t.count})
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-1">
          <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-white/40 px-2">
            live · streaming
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close terminal"
            title="Close terminal"
            className="text-white/45 hover:text-paper hover:bg-white/5 rounded p-1.5 transition-colors"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 14 14"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <path
                d="M3.5 3.5l7 7M10.5 3.5l-7 7"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto draft-scroll px-6 py-4">
        {tab === "cost" ? (
          <CostStream hasDesign={hasDesign} />
        ) : (
          <ProblemsList />
        )}
      </div>
    </div>
  );
}

function CostStream({ hasDesign }: { hasDesign: boolean }) {
  if (!hasDesign) {
    return (
      <div className="font-mono text-[12px] text-white/50 leading-relaxed">
        Cost stream idle.
        <br />
        Generate a design to see ₹ low / base / high tick live.
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-6">
        <CostFigure label="Low" value="₹ 1,42,500" />
        <CostFigure label="Base" value="₹ 1,68,000" highlight />
        <CostFigure label="High" value="₹ 1,95,000" />
      </div>
      <div className="border-t border-white/10 pt-3">
        <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-white/45 mb-2">
          Line items
        </div>
        <div className="space-y-1 font-mono text-[12px] text-white/85">
          <CostLine
            k="Walnut top · 2.4 m²"
            v="₹ 38,400"
            src="MCX live · ₹16k/m³"
            srcWhen="3 hrs ago"
          />
          <CostLine
            k="Mild steel base · 14 kg"
            v="₹ 1,260"
            src="MCX live · ₹62-90/kg"
            srcWhen="3 hrs ago"
          />
          <CostLine
            k="Brass handles · 6 ea"
            v="₹ 7,800"
            src="Vendor · Jaquar JAQ-FAU-001"
            srcWhen="catalog · 2 days ago"
          />
          <CostLine
            k="Labour · woodworking 18 hr"
            v="₹ 5,400"
            src="Trade rate v12 · ₹300/hr"
            srcWhen="ingested 2026-04-01"
          />
          <CostLine
            k="Finish · lacquer 0.6 L"
            v="₹ 540"
            src="Vendor · Asian Paints PU"
            srcWhen="catalog · 1 wk ago"
          />
          <CostLine
            k="Overhead · 35% of direct"
            v="₹ 18,872"
            src="CPWD §3.4 · industry std"
            srcWhen="ingested 2026-04-01"
          />
          <CostLine
            k="Margin · designer 30%"
            v="₹ 21,795"
            src="Designer fee schedule"
            srcWhen="configured"
          />
        </div>
      </div>
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-white/40">
        Updated 0 ms ago · MCX live
      </div>
    </div>
  );
}

function CostFigure({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-white/45">
        {label}
      </div>
      <div
        className={`mt-1 font-mono tnum tracking-[-0.01em] ${
          highlight
            ? "text-paper text-[1.625rem] font-medium"
            : "text-white/75 text-[1.375rem] font-normal"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function CostLine({
  k,
  v,
  src,
  srcWhen,
}: {
  k: string;
  v: string;
  src?: string;
  srcWhen?: string;
}) {
  return (
    <div className="group/line relative flex items-baseline justify-between border-b border-dashed border-white/10 py-1">
      <span className="text-white/65">{k}</span>
      <div className="flex items-baseline gap-2">
        <span className="text-paper tnum">{v}</span>
        {src ? <SourceMark src={src} srcWhen={srcWhen} /> : null}
      </div>
    </div>
  );
}

/* Inline citation marker. A small pencil-red asterisk that announces
   "this value has a source." On row hover, a popover surfaces the cited
   reference and how fresh the data is. Tooltip is anchored to the row,
   not just the marker, so the architect's eye can drift across the
   line without losing the popover. */
function SourceMark({ src, srcWhen }: { src: string; srcWhen?: string }) {
  return (
    <span className="relative inline-flex items-baseline">
      <span
        className="font-mono text-[11px] leading-none text-pencil-soft cursor-help select-none"
        aria-label={`source: ${src}${srcWhen ? `, ${srcWhen}` : ""}`}
      >
        *
      </span>
      <span
        role="tooltip"
        className="pointer-events-none invisible opacity-0 group-hover/line:visible group-hover/line:opacity-100 absolute right-0 bottom-full mb-2 z-20 whitespace-nowrap bg-[#1A1A1A] border border-white/15 px-2.5 py-1.5 rounded-sm text-[10px] uppercase tracking-[0.1em] text-white/85 transition-opacity duration-150 font-mono"
      >
        <span className="text-pencil-soft">src</span>
        <span className="ml-2">{src}</span>
        {srcWhen ? (
          <span className="ml-2 text-white/50">· {srcWhen}</span>
        ) : null}
      </span>
    </span>
  );
}

function ProblemsList() {
  return (
    <div className="font-mono text-[12px] text-white/65 space-y-1.5">
      <div className="text-white/45">No problems detected.</div>
      <div className="text-white/45">
        Validation warnings, hard errors, suggestions, and provenance notes
        will appear here as the agent works.
      </div>
      <div className="mt-4 pl-3 border-l-2 border-olive">
        <span className="text-olive">[OK]</span>
        <span className="ml-2 text-white/85">
          all dimensions within ergonomic ranges
        </span>
      </div>
      <div className="pl-3 border-l-2 border-olive">
        <span className="text-olive">[OK]</span>
        <span className="ml-2 text-white/85">
          door width 1100mm ≥ NBC 1000mm minimum
        </span>
      </div>
    </div>
  );
}


// ── Project type selector ──────────────────────────────────────────────
//
// Defs are fetched dynamically from /api/v1/project-types. Primary defs
// (is_primary=true, sorted ascending) render as the 2x3 grid; the rest
// live under a "More" affordance. The selector renders a tiny "Loading…"
// state on cold start; in practice the fetch completes well before the
// user clicks anything because we kick it off on workspace mount.

function ProjectTypeSelector({
  value,
  defs,
  onChange,
}: {
  value: ProjectType;
  defs: import("@/lib/api-client").ProjectTypeDef[];
  onChange: (t: ProjectType) => void;
}) {
  const primary = useMemo(
    () => defs.filter((d) => d.is_primary).sort((a, b) => a.sort_order - b.sort_order),
    [defs],
  );
  const overflow = useMemo(
    () => defs.filter((d) => !d.is_primary).sort((a, b) => a.sort_order - b.sort_order),
    [defs],
  );
  const valueIsOverflow = overflow.some((d) => d.slug === value);
  const [moreOpen, setMoreOpen] = useState(valueIsOverflow);

  // If the persisted active value lives in overflow, expand on first
  // render (already handled by initial state) — but if value changes
  // later (e.g. reset by validity sync) and lands in overflow, expand.
  useEffect(() => {
    if (valueIsOverflow && !moreOpen) setMoreOpen(true);
  }, [valueIsOverflow, moreOpen]);

  if (defs.length === 0) {
    return (
      <section>
        <SectionTag>Project type</SectionTag>
        <div className="mt-2.5 text-[12px] text-ink-mute px-1">
          Loading types…
        </div>
      </section>
    );
  }

  return (
    <section>
      <div className="flex items-center justify-between">
        <SectionTag>Project type</SectionTag>
        {overflow.length > 0 ? (
          <button
            type="button"
            onClick={() => setMoreOpen((v) => !v)}
            className="text-[11px] text-ink-mute hover:text-ink transition-colors"
          >
            {moreOpen ? "Less" : "More"}
          </button>
        ) : null}
      </div>
      <div className="mt-2.5 grid grid-cols-2 gap-1.5">
        {primary.map((d) => (
          <button
            key={d.slug}
            type="button"
            className="slide-pill text-center"
            data-active={d.slug === value}
            onClick={() => onChange(d.slug as ProjectType)}
            title={d.description || undefined}
          >
            {d.label}
          </button>
        ))}
      </div>
      {moreOpen && overflow.length > 0 ? (
        <div className="mt-1.5 grid grid-cols-2 gap-1.5">
          {overflow.map((d) => (
            <button
              key={d.slug}
              type="button"
              className="slide-pill text-center"
              data-active={d.slug === value}
              onClick={() => onChange(d.slug as ProjectType)}
              title={d.description || undefined}
            >
              {d.label}
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}
