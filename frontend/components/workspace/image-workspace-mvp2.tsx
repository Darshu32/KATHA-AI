"use client";

/* MVP 2 — Design generation workspace.
 * Editorial 4-zone layout: left controls, centered canvas, right specs,
 * bottom terminal. Sans body, serif display headlines, mono technical
 * surfaces (cost stream, generation log, citations). Gridpaper appears
 * only on the canvas area, never on chrome. */

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
  BrassKV,
  BrassRule,
  PaperCard,
  SectionTag,
} from "@/components/primitives";

type Scope = "architecture" | "interior" | "furniture" | "product";
type Dim = "2d" | "3d" | "4d";
type TerminalTab = "cost" | "problems" | "log" | "citations";

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

        <main className="flex-1 flex flex-col min-w-0 border-x border-hairline bg-paper-soft/30">
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
            className="font-display text-[1.35rem] text-ink-deep tracking-tight font-medium leading-none"
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
      <h1 className="font-display text-4xl md:text-[2.75rem] text-ink-deep leading-[1.1] tracking-tight font-medium">
        A {lowerLabel} canvas,
        <br />
        <span className="italic text-ink-soft">ready when you are.</span>
      </h1>
      <p className="mt-5 text-ink-soft text-[1.0625rem] leading-relaxed max-w-xl">
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
      <h3 className="mt-2 font-display text-lg text-ink-deep font-medium">
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
              <div className="mt-3 text-[11px] font-mono text-brass">
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
            Specs, materials, BOQ, and citations will appear here once you
            generate a design. Every value sourced and cited.
          </p>
        ) : (
          <div className="mt-3 space-y-5">
            <div>
              <h4 className="font-mono text-[10px] tracking-tagged uppercase text-ink-mute mb-2">
                Meta
              </h4>
              <div className="space-y-1">
                <BrassKV k="Dim" v={dim.toUpperCase()} />
                <BrassKV k="Theme" v={theme} />
                <BrassKV k="Version" v="01" />
              </div>
            </div>
            <BrassRule />
            <div>
              <h4 className="font-mono text-[10px] tracking-tagged uppercase text-ink-mute mb-2">
                Primary materials
              </h4>
              <div className="space-y-1">
                <BrassKV k="Walnut (top)" v="₹560/kg" />
                <BrassKV k="Brass (handles)" v="₹820/kg" />
                <BrassKV k="Leather A" v="₹1,950/m²" />
              </div>
              <p className="mt-2 text-[10px] font-mono text-brass">
                Live MCX · 3 hrs ago
              </p>
            </div>
            <BrassRule />
            <div>
              <h4 className="font-mono text-[10px] tracking-tagged uppercase text-ink-mute mb-2">
                Citations
              </h4>
              <ul className="space-y-1.5 text-[12px]">
                <li className="flex items-baseline">
                  <span className="status-dot status-dot--src" />
                  <a
                    className="text-terracotta underline underline-offset-2"
                    href="#"
                  >
                    NBC-2016 Part 3 §4.2.1
                  </a>
                  <span className="text-ink-mute ml-1">· door widths</span>
                </li>
                <li className="flex items-baseline">
                  <span className="status-dot status-dot--src" />
                  <a
                    className="text-terracotta underline underline-offset-2"
                    href="#"
                  >
                    MCX feed 2026-05-05
                  </a>
                  <span className="text-ink-mute ml-1">· steel ₹/kg</span>
                </li>
                <li className="flex items-baseline">
                  <span className="status-dot status-dot--src" />
                  <a
                    className="text-terracotta underline underline-offset-2"
                    href="#"
                  >
                    Manufacturing handbook §6
                  </a>
                  <span className="text-ink-mute ml-1">· joinery</span>
                </li>
              </ul>
            </div>
          </div>
        )}
      </div>
    </aside>
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
      <span className="font-mono text-[11px] tracking-tagged uppercase text-paper/60">
        Terminal · cost · problems · log · citations
      </span>
      <span className="text-[11px] text-paper/60">Expand ↑</span>
    </button>
  );
}

const TABS: { id: TerminalTab; label: string; count?: number }[] = [
  { id: "cost", label: "Cost" },
  { id: "problems", label: "Problems", count: 0 },
  { id: "log", label: "Log" },
  { id: "citations", label: "Citations" },
];

function TerminalPanel({
  tab,
  setTab,
  hasDesign,
}: {
  tab: TerminalTab;
  setTab: (t: TerminalTab) => void;
  hasDesign: boolean;
}) {
  return (
    <div className="border-t border-hairline bg-ink-deep h-72 flex flex-col">
      <div className="border-b border-paper/10 px-3 flex items-center justify-between">
        <div className="flex items-center">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className="text-[12px] font-medium px-4 py-2.5 transition-colors"
              style={{
                color:
                  t.id === tab ? "#C2A375" : "rgba(250, 247, 241, 0.55)",
                borderBottom:
                  t.id === tab ? "2px solid #A8451B" : "2px solid transparent",
                background: "transparent",
              }}
              onClick={() => setTab(t.id)}
            >
              {t.label}
              {t.count !== undefined ? (
                <span
                  className="ml-1.5 text-[11px]"
                  style={{ color: "rgba(250, 247, 241, 0.4)" }}
                >
                  ({t.count})
                </span>
              ) : null}
            </button>
          ))}
        </div>
        <span className="font-mono text-[10px] text-paper/40 px-3">
          live · streaming
        </span>
      </div>

      <div className="flex-1 overflow-y-auto draft-scroll px-6 py-4">
        {tab === "cost" ? (
          <CostStream hasDesign={hasDesign} />
        ) : tab === "problems" ? (
          <ProblemsList />
        ) : tab === "log" ? (
          <GenerationLog />
        ) : (
          <CitationsList />
        )}
      </div>
    </div>
  );
}

function CostStream({ hasDesign }: { hasDesign: boolean }) {
  if (!hasDesign) {
    return (
      <div className="font-mono text-[12px] text-paper/50 leading-relaxed">
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
      <div className="border-t border-paper/10 pt-3">
        <div className="font-mono text-[10px] uppercase tracking-tagged text-paper/50 mb-2">
          Line items
        </div>
        <div className="space-y-1 font-mono text-[12px] text-paper/80">
          <CostLine k="Walnut top · 2.4 m²" v="₹ 38,400" />
          <CostLine k="Mild steel base · 14 kg" v="₹ 1,260" />
          <CostLine k="Brass handles · 6 ea" v="₹ 7,800" />
          <CostLine k="Labour · woodworking 18 hr" v="₹ 5,400" />
          <CostLine k="Finish · lacquer 0.6 L" v="₹ 540" />
          <CostLine k="Overhead · 35% of direct" v="₹ 18,872" />
          <CostLine k="Margin · designer 30%" v="₹ 21,795" />
        </div>
      </div>
      <div className="font-mono text-[10px] text-paper/40">
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
      <div className="font-mono text-[10px] uppercase tracking-tagged text-paper/50">
        {label}
      </div>
      <div
        className={`mt-1 font-display tnum ${
          highlight ? "text-brass-soft text-3xl" : "text-paper/85 text-2xl"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function CostLine({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between border-b border-dashed border-paper/10 py-1">
      <span className="text-paper/70">{k}</span>
      <span className="text-brass-soft">{v}</span>
    </div>
  );
}

function ProblemsList() {
  return (
    <div className="font-mono text-[12px] text-paper/60 space-y-1.5">
      <div className="text-paper/40">No problems detected.</div>
      <div className="text-paper/40">
        Validation warnings, hard errors, suggestions, and provenance notes
        will appear here as the agent works.
      </div>
      <div className="mt-4 pl-3 border-l-2 border-olive">
        <span className="text-olive">[OK]</span>
        <span className="ml-2 text-paper/80">
          all dimensions within ergonomic ranges
        </span>
      </div>
      <div className="pl-3 border-l-2 border-olive">
        <span className="text-olive">[OK]</span>
        <span className="ml-2 text-paper/80">
          door width 1100mm ≥ NBC 1000mm minimum
        </span>
      </div>
    </div>
  );
}

function GenerationLog() {
  const lines = [
    "[10:24:01] resolving brief → 5 sections detected",
    "[10:24:01] retrieving NBC §4.2 from RAG corpus…  done (3 chunks)",
    "[10:24:02] generating design graph (theme=contemporary, scope=interior)",
    "[10:24:03] cost engine → MCX live (steel ₹62/kg, captured 3h ago)",
    "[10:24:03] resolving labour rates → 5 trades, version 12",
    "[10:24:04] sensitivity → ±10% applied across 1/5/10 piece volumes",
    "[10:24:04] rendering depth map (Three.js, headless)",
    "[10:24:05] dispatching to Nano Banana Pro (gemini-3-pro-image)",
    "[10:24:09] photoreal output received (1024x576)",
    "[10:24:09] specs · drawings · diagrams generated",
    "[10:24:09] >>> done <<<",
  ];
  return (
    <div className="font-mono text-[11px] text-paper/75 space-y-0.5 leading-relaxed">
      {lines.map((l, i) => (
        <div
          key={i}
          className="anim-fade-in"
          style={{ animationDelay: `${i * 30}ms` }}
        >
          <span className="text-brass-soft mr-2">›</span>
          {l}
        </div>
      ))}
    </div>
  );
}

function CitationsList() {
  return (
    <div className="space-y-2 font-mono text-[11px]">
      <CitationRow
        srcRef="NBC-2016 Part 3 §4.2.1"
        what="Door widths · entry 1000mm minimum"
        when="ingested 2026-04-01"
      />
      <CitationRow
        srcRef="ECBC-2017 §4.3"
        what="Envelope U-value · 0.40 W/m²K wall"
        when="ingested 2026-04-01"
      />
      <CitationRow
        srcRef="MCX live feed"
        what="Mild steel ₹62-90/kg"
        when="captured 3 hrs ago"
      />
      <CitationRow
        srcRef="Vendor: Jaquar catalog"
        what="JAQ-FAU-001 · ₹12,000-14,500"
        when="catalog · 2 days ago"
      />
      <CitationRow
        srcRef="Manufacturing handbook §6"
        what="Mortise-tenon joint tolerance ±0.5mm"
        when="ingested 2026-04-01"
      />
    </div>
  );
}

function CitationRow({
  srcRef,
  what,
  when,
}: {
  srcRef: string;
  what: string;
  when: string;
}) {
  return (
    <div className="flex items-baseline gap-3 border-b border-dashed border-paper/10 py-1.5">
      <span className="text-brass-soft min-w-[12rem]">{srcRef}</span>
      <span className="text-paper/70 flex-1">{what}</span>
      <span className="text-paper/40 text-[10px]">{when}</span>
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
