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
import {
  ApiError,
  design as designApi,
  projects as projectsApi,
  resolveAssetUrl,
} from "@/lib/api-client";
import { toastError, useToastStore } from "@/lib/toast-store";
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
import { ImportDialog } from "@/components/workspace/import-dialog";
import {
  ProjectPicker,
  type OpenedProject,
} from "@/components/workspace/project-picker";

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
    activeProjectId,
    setActiveProject,
    replaceGenerations,
    clearGenerations,
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

  // ── Pass 2: edit-loop UX state ──────────────────────────────────────
  // Which object the architect has selected for editing, plus the
  // prompt they're typing and whether a submit is in flight. Cleared
  // after a successful edit so the popover collapses on its own.
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null);
  const [editPrompt, setEditPrompt] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // ── Pass 3: theme-switch state ──────────────────────────────────────
  // A single in-flight flag is enough — the chip itself owns its
  // open/closed state. Errors surface as a transient notice strip.
  const [isSwitchingTheme, setIsSwitchingTheme] = useState(false);
  const [themeSwitchError, setThemeSwitchError] = useState<string | null>(null);

  // ── BRD 5B: import dialog open/close ────────────────────────────────
  // The dialog owns its file-queue + parse state internally; the
  // workspace just toggles visibility and receives the parsed brief
  // text on apply, which gets appended to the prompt textarea.
  const [importOpen, setImportOpen] = useState(false);

  // ── Project picker open/close ──────────────────────────────────────
  // The picker owns its project-list state; the workspace receives an
  // OpenedProject callback that swaps the gallery + activeProjectId
  // in one shot.
  const [pickerOpen, setPickerOpen] = useState(false);

  /* Handle opening an existing project from the picker. The picker
     has already fetched the latest version; we replace the gallery
     with a single card for that version (older versions aren't
     loaded — only one card per re-opened project until the user
     re-generates / edits). */
  const handleOpenProject = (p: OpenedProject) => {
    setActiveProject(p.projectId, p.version || null, p.projectName ?? null);
    if (p.version > 0) {
      replaceGenerations([
        {
          id: crypto.randomUUID(),
          prompt: p.prompt || p.projectName,
          url: p.imageUrl ?? undefined,
          timestamp: new Date().toISOString(),
          theme,
          ratio,
          quality: "standard",
          drawingType: "3d-render",
          camera: "front",
          lighting: "daylight",
          width: 1024,
          height: 576,
          projectId: p.projectId,
          version: p.version,
          graphData: p.graphData,
          estimate: {},
          objectsBbox: p.objectsBbox,
        },
      ]);
    } else {
      // Project exists but has no versions yet — clear gallery so the
      // user sees the empty hero scoped to this project.
      replaceGenerations([]);
    }
    setPrompt(p.prompt || "");
    setSelectedObjectId(null);
    setEditPrompt("");
  };

  /* Handle "New project" from the picker. Clear everything and let
     the next Generate create a fresh project. */
  const handleNewProject = () => {
    clearGenerations();
    setPrompt("");
    setSelectedObjectId(null);
    setEditPrompt("");
  };

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

  /* Latest generation drives the editable-objects panel + the edit
     submission context. Older generations remain in the gallery as
     read-only history; only the latest version can be edited (the
     /edit endpoint always operates on get_latest_version). */
  const latestGeneration = generations[0] ?? null;
  const editableObjects = useMemo(() => {
    const data = latestGeneration?.graphData as
      | { objects?: Array<{ id: string; type: string; name?: string; material?: string; dimensions?: { length: number; width: number; height: number } | null }> }
      | undefined;
    return data?.objects ?? [];
  }, [latestGeneration]);

  /* submitThemeSwitch — Pass 3 of the edit loop.
   *
   * Reskins the active project to a new theme without re-prompting.
   * preserve_layout=true keeps the floor plan + object positions and
   * just swaps materials / finishes / palette. As with submitEdit we
   * also re-run the render so the gallery shows the visual change
   * alongside the bumped version.
   */
  const submitThemeSwitch = async (newStyle: string) => {
    if (
      !activeProjectId ||
      !latestGeneration ||
      isSwitchingTheme ||
      newStyle === theme
    ) {
      return;
    }
    setThemeSwitchError(null);
    setIsSwitchingTheme(true);
    try {
      const switchRes = await designApi.switchTheme(token, activeProjectId, {
        new_style: newStyle,
        preserve_layout: true,
      });
      addGeneration({
        id: crypto.randomUUID(),
        prompt: latestGeneration.prompt,
        url: switchRes.image_url ?? undefined,
        timestamp: new Date().toISOString(),
        theme: newStyle as ArchTheme,
        ratio,
        quality: latestGeneration.quality,
        drawingType: latestGeneration.drawingType,
        camera: latestGeneration.camera,
        lighting: latestGeneration.lighting,
        width: latestGeneration.width,
        height: latestGeneration.height,
        projectId: activeProjectId,
        version: switchRes.version,
        graphData: switchRes.graph_data,
        estimate: switchRes.estimate,
        objectsBbox: switchRes.objects_bbox,
      });
      setActiveProject(activeProjectId, switchRes.version);
      setTheme(newStyle as ArchTheme);
    } catch (e) {
      // Two surfaces for the same error so the architect can't miss it:
      // toast for the transient "what just happened" signal, inline
      // chip on the canvas so the next click on Switch sees the
      // last-failure context.
      toastError(e, "Theme switch failed");
      setThemeSwitchError(
        e instanceof ApiError
          ? `Backend rejected the theme switch (${e.status}).`
          : "Couldn't reach the backend for the theme switch.",
      );
    } finally {
      setIsSwitchingTheme(false);
    }
  };

  /* submitEdit — Pass 2 of the edit loop.
   *
   * Operates on whichever object the architect has selected. Calls
   * /projects/{id}/edit (graph + new version), and in parallel asks
   * /images/generate for a fresh render that reflects the change.
   * The new version becomes the gallery's latest; the user's prompt
   * is concatenated to the original so the audit trail reads as a
   * sentence ("…walnut top → swap legs to brass"). */
  const submitEdit = async () => {
    if (
      !selectedObjectId ||
      !editPrompt.trim() ||
      editPrompt.trim().length < 5 ||
      !activeProjectId ||
      !latestGeneration ||
      isEditing
    ) {
      return;
    }
    setEditError(null);
    setIsEditing(true);
    try {
      const editRes = await designApi.editObject(token, activeProjectId, {
        object_id: selectedObjectId,
        prompt: editPrompt.trim(),
      });

      addGeneration({
        id: crypto.randomUUID(),
        prompt: `${latestGeneration.prompt} — ${editPrompt.trim()}`,
        url: editRes.image_url ?? undefined,
        timestamp: new Date().toISOString(),
        theme,
        ratio,
        quality: latestGeneration.quality,
        drawingType: latestGeneration.drawingType,
        camera: latestGeneration.camera,
        lighting: latestGeneration.lighting,
        width: latestGeneration.width,
        height: latestGeneration.height,
        projectId: activeProjectId,
        version: editRes.version,
        graphData: editRes.graph_data,
        estimate: editRes.estimate,
        objectsBbox: editRes.objects_bbox,
      });
      setActiveProject(activeProjectId, editRes.version);
      setEditPrompt("");
      setSelectedObjectId(null);
    } catch (e) {
      toastError(e, "Edit failed");
      setEditError(
        e instanceof ApiError
          ? `Backend rejected the edit (${e.status}).`
          : "Couldn't reach the backend for the edit.",
      );
    } finally {
      setIsEditing(false);
    }
  };

  /* generate() — runs the full project pipeline.
   *
   * Prototype mode: the backend middleware attributes anonymous
   * requests to a shared dev user, so we always go through the
   * project pipeline (no auth-gated branching). When auth is
   * reintroduced, the only change here is the optional token thread
   * regaining a real value.
   *
   * Flow:
   *   1. Ensure an active project exists (create one on first run).
   *   2. POST /projects/{id}/generate — yields the design graph,
   *      cost estimate, and the photoreal render in one round trip
   *      (render baked in by the backend pipeline as of phase 0).
   *   3. Push the result to the gallery.
   */
  const generate = async () => {
    if (!prompt.trim() || isGenerating) return;
    setGenerateError(null);
    setGenerateNotice(null);
    setIsGenerating(true);

    try {
      // 1 — ensure active project
      let projectId = activeProjectId;
      if (!projectId) {
        const project = await projectsApi.create(token, {
          name: prompt.trim().slice(0, 60) || "Untitled design",
          project_type: projectType,
        });
        projectId = project.id;
        setActiveProject(projectId, null, project.name);
      }

      // 2 — single backend call: graph + render baked together
      const graphRes = await designApi.generate(token, projectId, {
        prompt: prompt.trim(),
        room_type: "living_room",
        style: theme,
        ratio,
        drawing_type: "3d-render",
      });

      if (!graphRes.image_url) {
        // Soft degraded-service path: graph generated fine but the
        // render step failed (no key, provider down). Surface as
        // warning toast + inline notice — not a hard error.
        useToastStore.getState().notify({
          type: "warning",
          title: "Render skipped",
          message: "Design graph generated, but no image was returned. Check GEMINI_API_KEY.",
        });
        setGenerateNotice(
          "Design graph generated. Render skipped — GEMINI_API_KEY not set or provider failed.",
        );
      }

      // 3 — push combined record (image_url comes from the same response)
      addGeneration({
        id: crypto.randomUUID(),
        prompt: prompt.trim(),
        url: graphRes.image_url ?? undefined,
        timestamp: new Date().toISOString(),
        theme,
        ratio,
        quality: "standard",
        drawingType: "3d-render",
        camera: "front",
        lighting: "daylight",
        width: 1024,
        height: 576,
        projectId,
        version: graphRes.version,
        graphData: graphRes.graph_data,
        estimate: graphRes.estimate,
        objectsBbox: graphRes.objects_bbox,
      });
      setActiveProject(projectId, graphRes.version);
    } catch (e) {
      toastError(e, "Generation failed");
      setGenerateError(
        e instanceof ApiError
          ? `Backend rejected the request (${e.status}). Check the API logs.`
          : "Couldn't reach the backend. Is uvicorn running on :8000?",
      );
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div className="h-screen w-full flex flex-col bg-paper">
      <TopBar
        onToggleTerminal={toggleTerminal}
        terminalOpen={terminalOpen}
        onOpenImport={() => setImportOpen(true)}
        onOpenProjects={() => setPickerOpen(true)}
      />
      <ImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onApply={(briefText) => {
          // Append to the prompt textarea. If the architect already
          // typed something we keep it as the lead and append the
          // imported brief beneath; otherwise the brief becomes the
          // prompt outright.
          setPrompt(prompt.trim() ? `${prompt.trim()}\n\n${briefText}` : briefText);
        }}
        token={token}
      />
      <ProjectPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onOpenProject={handleOpenProject}
        onNewProject={handleNewProject}
        activeProjectId={activeProjectId}
        token={token}
      />

      <div className="flex-1 flex min-h-0">
        <LeftControls
          projectType={projectType}
          setProjectType={setProjectType}
          projectTypeDefs={projectTypeDefs}
          scope={scope}
          setScope={setScope}
          dim={dim}
          setDim={setDim}
          ratio={ratio}
          setRatio={setRatio}
        />

        <main className="flex-1 flex flex-col min-w-0 border-x border-hairline bg-paper">
          <CanvasHeader
            scope={scope}
            dim={dim}
            projectType={projectType}
            projectTypeLabel={activeTypeDef?.label ?? projectType}
            theme={theme}
            themesList={themesList}
            onChooseTheme={(slug) => {
              // When there's an active project with at least one
              // generation, picking a theme is a *switch* op (backend
              // round-trip → new version). Otherwise it just stages
              // the theme for the next Generate.
              if (activeProjectId && latestGeneration) {
                void submitThemeSwitch(slug);
              } else {
                setTheme(slug as ArchTheme);
              }
            }}
            isSwitchingTheme={isSwitchingTheme}
            themeSwitchError={themeSwitchError}
            generations={generations}
            hasActiveProject={!!activeProjectId && !!latestGeneration}
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
              <CanvasGallery
                generations={generations}
                dim={dim}
                selectedObjectId={selectedObjectId}
                onSelectObject={setSelectedObjectId}
                isGenerating={isGenerating}
                isEditing={isEditing}
                isSwitchingTheme={isSwitchingTheme}
                pendingPrompt={prompt}
              />
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
          objects={editableObjects}
          selectedObjectId={selectedObjectId}
          onSelectObject={setSelectedObjectId}
          editPrompt={editPrompt}
          onEditPromptChange={setEditPrompt}
          onSubmitEdit={submitEdit}
          isEditing={isEditing}
          editError={editError}
          canEdit={!!activeProjectId}
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
  onOpenImport,
  onOpenProjects,
}: {
  onToggleTerminal: () => void;
  terminalOpen: boolean;
  onOpenImport: () => void;
  onOpenProjects: () => void;
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
          <button
            type="button"
            onClick={onOpenProjects}
            className="text-[12px] text-ink-soft hover:text-ink transition-colors px-2 py-1 inline-flex items-center gap-1.5 border border-hairline hover:border-graphite rounded-sm"
            aria-label="Open projects"
            title="Switch project, rename, archive"
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 13 13"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M1.5 3.5h4l1 1h5v6h-10z"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinejoin="round"
              />
            </svg>
            Projects
          </button>
        </div>
        <nav className="flex items-center gap-2">
          <button
            type="button"
            onClick={onOpenImport}
            className="text-[12px] text-ink-soft hover:text-ink transition-colors px-2 py-1 inline-flex items-center gap-1"
            aria-label="Import files"
            title="Import briefs, plans, references"
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 13 13"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M6.5 1.5v6.5M3.5 5l3 3 3-3M2 11h9"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            Import
          </button>
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
  theme,
  themesList,
  onChooseTheme,
  isSwitchingTheme,
  themeSwitchError,
  generations,
  hasActiveProject,
}: {
  scope: Scope;
  dim: Dim;
  projectType: ProjectType;
  projectTypeLabel: string;
  theme: ArchTheme;
  themesList: import("@/lib/api-client").ThemeDef[];
  onChooseTheme: (newStyle: string) => void;
  isSwitchingTheme: boolean;
  themeSwitchError: string | null;
  generations: import("@/lib/types").ImageGeneration[];
  hasActiveProject: boolean;
}) {
  void projectType; // explicitly unused — kept on signature for future telemetry
  const projectGenerations = generations.filter((g) => g.version != null);
  return (
    <div className="px-6 py-2 border-b border-hairline bg-paper/85 backdrop-blur-sm flex items-center justify-between gap-4">
      <div className="flex items-center gap-3 min-w-0">
        <SectionTag>Canvas</SectionTag>
        <span className="text-[12px] text-ink-mute truncate">
          {projectTypeLabel} ·{" "}
          {SCOPES.find((s) => s.id === scope)?.label} · {dim.toUpperCase()}
        </span>
        {themeSwitchError ? (
          <span className="text-[11px] font-mono text-brick">
            {themeSwitchError}
          </span>
        ) : null}
      </div>
      <div className="flex items-center gap-3 shrink-0">
        <ThemeSwitchChip
          theme={theme}
          themesList={themesList}
          onChoose={onChooseTheme}
          isSwitching={isSwitchingTheme}
          hasActiveProject={hasActiveProject}
        />
        {projectGenerations.length > 0 ? (
          <VersionTimeline generations={projectGenerations} />
        ) : null}
      </div>
    </div>
  );
}

/* ThemeSwitchChip — single theme picker for the design surface.
   "Theme: Modern ▾" trigger; opens a dropdown of every registered
   theme. Always enabled — the parent decides what the click means:
     • No active project → onChoose() just sets local theme state,
       so the next Generate uses it.
     • Active project    → onChoose() triggers submitThemeSwitch(),
       which produces a new version with preserve_layout=true.
   The dropdown header label reflects the mode so the architect knows
   whether they're staging a theme for the next generation or
   reskinning the current design. */
function ThemeSwitchChip({
  theme,
  themesList,
  onChoose,
  isSwitching,
  hasActiveProject,
}: {
  theme: ArchTheme;
  themesList: import("@/lib/api-client").ThemeDef[];
  onChoose: (newStyle: string) => void;
  isSwitching: boolean;
  hasActiveProject: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  // Close on outside click — keeps the chip from sticking open when
  // the architect's attention moves to the canvas.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);
  const activeLabel =
    themesList.find((t) => t.slug === theme)?.display_name ?? theme;
  const headerLabel = hasActiveProject
    ? "Switch theme · layout preserved"
    : "Pick theme for next generation";
  const titleAttr = hasActiveProject
    ? "Switch theme — preserves layout, re-renders with new materials"
    : "Pick theme for the next generation";
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={isSwitching}
        className={`flex items-baseline gap-1.5 font-mono text-[11px] uppercase tracking-[0.1em] px-2 py-1 rounded-sm border border-hairline hover:border-graphite text-ink transition-colors ${
          isSwitching ? "opacity-60 cursor-wait" : ""
        }`}
        title={titleAttr}
      >
        <span className="text-ink-mute">Theme</span>
        <span className="text-ink-deep font-medium">
          {isSwitching ? "Switching…" : activeLabel}
        </span>
        <span className="text-ink-mute">▾</span>
      </button>
      {open ? (
        <div className="absolute right-0 top-full mt-1 z-30 min-w-[14rem] bg-paper border border-graphite rounded-sm shadow-card overflow-hidden">
          <div className="px-3 py-2 border-b border-hairline">
            <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute">
              {headerLabel}
            </span>
          </div>
          <div className="max-h-60 overflow-y-auto draft-scroll">
            {themesList.length === 0 ? (
              <div className="px-3 py-2 text-[12px] text-ink-mute">
                Loading themes…
              </div>
            ) : (
              themesList.map((t) => {
                const active = t.slug === theme;
                return (
                  <button
                    key={t.slug}
                    type="button"
                    onClick={() => {
                      onChoose(t.slug);
                      setOpen(false);
                    }}
                    className={`w-full text-left px-3 py-1.5 font-mono text-[12px] flex items-baseline justify-between transition-colors ${
                      active
                        ? "bg-pencil-bg/60 text-ink-deep"
                        : "hover:bg-paper-soft text-ink"
                    }`}
                  >
                    <span>{t.display_name}</span>
                    {active ? (
                      <span className="text-pencil text-[10px]">●</span>
                    ) : null}
                  </button>
                );
              })
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* VersionTimeline — Pass 3.
   Horizontal strip of v01 / v02 / v03 chips for the active project's
   versions. Clicking a chip scrolls the matching gallery card into
   view; the latest version is rendered in pencil-red as a reminder
   that edits always operate on it (the backend always loads
   get_latest_version, so older versions are read-only history). */
function VersionTimeline({
  generations,
}: {
  generations: import("@/lib/types").ImageGeneration[];
}) {
  // Generations are stored newest-first; the timeline reads
  // oldest-first so the eye scans left-to-right as a project grows.
  const ordered = useMemo(
    () => [...generations].reverse(),
    [generations],
  );
  const latestVersion = generations[0]?.version ?? null;
  return (
    <div className="flex items-baseline gap-1.5 font-mono text-[11px] tnum">
      <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute">
        ver
      </span>
      <div className="flex items-baseline gap-0.5 max-w-[20rem] overflow-x-auto draft-scroll">
        {ordered.map((g) => {
          const isLatest = g.version === latestVersion;
          return (
            <button
              key={g.id}
              type="button"
              onClick={() => {
                const el = document.getElementById(`gen-${g.id}`);
                if (!el) return;
                el.scrollIntoView({ behavior: "smooth", block: "start" });
                // Quick pencil-bg flash so the user sees what loaded.
                el.classList.add("ring-2", "ring-pencil-bg");
                setTimeout(() => {
                  el.classList.remove("ring-2", "ring-pencil-bg");
                }, 1400);
              }}
              className={`px-1.5 py-0.5 rounded-sm transition-colors ${
                isLatest
                  ? "text-pencil font-medium"
                  : "text-ink-soft hover:text-ink hover:bg-paper-soft"
              }`}
              title={`v${String(g.version).padStart(2, "0")} · ${new Date(g.timestamp).toLocaleString()}`}
            >
              v{String(g.version).padStart(2, "0")}
            </button>
          );
        })}
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
  selectedObjectId,
  onSelectObject,
  isGenerating,
  isEditing,
  isSwitchingTheme,
  pendingPrompt,
}: {
  generations: import("@/lib/types").ImageGeneration[];
  dim: Dim;
  selectedObjectId: string | null;
  onSelectObject: (id: string | null) => void;
  isGenerating: boolean;
  isEditing: boolean;
  isSwitchingTheme: boolean;
  pendingPrompt: string;
}) {
  // Any of the three async paths shows a skeleton — the user shouldn't
  // have to mentally map which spinner means what.
  const pending = isGenerating || isEditing || isSwitchingTheme;
  const pendingLabel = isGenerating
    ? "Generating"
    : isEditing
    ? "Applying edit"
    : "Switching theme";
  return (
    <div className="px-6 md:px-10 py-8 max-w-5xl mx-auto space-y-5">
      {pending ? (
        <GenerationSkeletonCard
          label={pendingLabel}
          version={generations.length + 1}
          prompt={pendingPrompt}
          dim={dim}
        />
      ) : null}
      {generations.map((g, i) => {
        const isLatest = i === 0;
        return (
        <PaperCard
          key={g.id}
          id={`gen-${g.id}`}
          className="p-5 anim-fade-in scroll-mt-4 transition-shadow"
        >
          <div className="flex items-baseline justify-between mb-3">
            <div className="flex items-baseline gap-3">
              <SectionTag>
                Render · {String(generations.length - i).padStart(2, "0")}
              </SectionTag>
              {g.version != null ? (
                <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-pencil tnum">
                  v{String(g.version).padStart(2, "0")}
                </span>
              ) : (
                <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute">
                  unversioned
                </span>
              )}
            </div>
            <Annotation>
              {new Date(g.timestamp).toLocaleString([], {
                hour: "2-digit",
                minute: "2-digit",
                day: "2-digit",
                month: "short",
              })}
            </Annotation>
          </div>
          {g.url ? (
            // Real render — rounded inset on white card. The image carries
            // its own pixels; no grid-paper background underneath. URL
            // resolver normalises legacy data:/http: URLs and prefixes
            // backend-relative paths with the API origin. ObjectOverlay
            // sits on top with click-to-edit hotspots when the
            // generation carries graph-derived bbox data.
            <div className="relative aspect-video bg-paper-deep border border-hairline rounded-md overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={resolveAssetUrl(g.url)}
                alt={g.prompt}
                className="absolute inset-0 w-full h-full object-cover"
              />
              {isLatest && g.objectsBbox && g.objectsBbox.length > 0 ? (
                <ObjectOverlay
                  bboxes={g.objectsBbox}
                  selectedObjectId={selectedObjectId}
                  onSelect={onSelectObject}
                />
              ) : null}
            </div>
          ) : (
            // Render absent — graph generated but Gemini key missing, or
            // legacy entry that never had a render. Show a quiet card so
            // the cost stream + spec rows still make sense.
            <div className="aspect-video bg-paper-deep border border-hairline rounded-md flex items-center justify-center grid-paper">
              <div className="text-center">
                <SectionTag>Render unavailable</SectionTag>
                <div className="mt-2 text-[12px] text-ink-soft">
                  {dim.toUpperCase()} · {g.prompt.slice(0, 60)}
                  {g.prompt.length > 60 ? "…" : ""}
                </div>
                <div className="mt-3 text-[11px] font-mono text-ink-mute">
                  GEMINI_API_KEY not set — graph saved, image skipped.
                </div>
              </div>
            </div>
          )}
          <div className="mt-3 text-[12px] text-ink-soft leading-relaxed">
            {g.prompt}
          </div>
        </PaperCard>
        );
      })}
    </div>
  );
}

/* GenerationSkeletonCard — placeholder shown above the gallery while
 * a generation / edit / theme-switch is in flight.
 *
 * Purpose: closes the silent-gap problem. Without this, the architect
 * presses Generate, the prompt input goes "Generating…", and the
 * canvas just sits there — no visual feedback for the 5-15s the
 * provider takes. The skeleton fills that gap with a quiet,
 * shimmering card that shares structure with real PaperCards so the
 * eye doesn't have to re-orient when the real result lands.
 *
 * Honest about being approximate: we don't know the final image's
 * objects, version, or cost yet. We show what we *do* know — the
 * prompt the architect typed — and shimmer the rest.
 */
function GenerationSkeletonCard({
  label,
  version,
  prompt,
  dim,
}: {
  label: string;
  version: number;
  prompt: string;
  dim: Dim;
}) {
  return (
    <PaperCard
      className="p-5 anim-fade-in transition-shadow"
      aria-busy="true"
      aria-live="polite"
    >
      <div className="flex items-baseline justify-between mb-3">
        <div className="flex items-baseline gap-3">
          <SectionTag>
            {label} · {String(version).padStart(2, "0")}
          </SectionTag>
          <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-pencil tnum">
            v{String(version).padStart(2, "0")} draft
          </span>
        </div>
        <Annotation>
          <span className="inline-flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-pencil animate-pulse" />
            {label.toLowerCase()}…
          </span>
        </Annotation>
      </div>
      {/* Canvas placeholder — aspect-video shimmer carrying the grid-
       *  paper underlay so the eye recognises it as "render space"
       *  even before pixels arrive. */}
      <div className="relative aspect-video rounded-md overflow-hidden border border-hairline skeleton-shimmer">
        <div className="absolute inset-0 grid-paper opacity-30" />
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-center px-6">
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-ink-mute">
              {dim.toUpperCase()} · {label}
            </p>
            <p className="mt-2 text-[12px] text-ink-soft max-w-md mx-auto leading-relaxed line-clamp-2">
              {prompt.trim() || "…preparing the design graph"}
            </p>
          </div>
        </div>
      </div>
      {/* Prose placeholders for the cost stream + spec rows that
       *  normally sit below the image. Two muted shimmer bars at
       *  staggered widths mimic the real rhythm. */}
      <div className="mt-4 space-y-2">
        <div className="h-2.5 w-3/4 rounded skeleton-shimmer" />
        <div className="h-2.5 w-1/2 rounded skeleton-shimmer" />
      </div>
    </PaperCard>
  );
}

/* ObjectOverlay — click-to-edit hotspots over the rendered image.
   Each bbox is an absolutely-positioned button anchored in normalised
   coordinates. Default: transparent; on hover or when selected, a
   pencil-red outline + name label appear. Click triggers the same
   selection state the right-panel objects list uses, so the edit
   popover opens consistently regardless of where the architect clicks
   from.
   Honest about being approximate — see backend/object_bboxes.py for
   the projection model. */
function ObjectOverlay({
  bboxes,
  selectedObjectId,
  onSelect,
}: {
  bboxes: NonNullable<import("@/lib/types").ImageGeneration["objectsBbox"]>;
  selectedObjectId: string | null;
  onSelect: (id: string | null) => void;
}) {
  return (
    <div
      className="absolute inset-0 pointer-events-none"
      aria-label="Object hotspots"
    >
      {bboxes.map((b) => {
        const selected = b.id === selectedObjectId;
        return (
          <button
            key={b.id}
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onSelect(selected ? null : b.id);
            }}
            aria-pressed={selected}
            aria-label={`Select ${b.name}`}
            title={b.name}
            className={`group/hotspot absolute pointer-events-auto rounded-sm transition-all ${
              selected
                ? "ring-2 ring-pencil ring-offset-1 ring-offset-paper/0"
                : "ring-0 hover:ring-2 hover:ring-pencil/70 hover:ring-offset-1 hover:ring-offset-paper/0"
            } cursor-crosshair`}
            style={{
              left: `${b.x * 100}%`,
              top: `${b.y * 100}%`,
              width: `${b.w * 100}%`,
              height: `${b.h * 100}%`,
              background: selected
                ? "rgba(200, 54, 45, 0.10)"
                : "transparent",
            }}
          >
            <span
              className={`absolute left-0 top-full mt-1 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.1em] bg-ink-deep text-paper rounded-sm whitespace-nowrap transition-opacity ${
                selected ? "opacity-100" : "opacity-0 group-hover/hotspot:opacity-100"
              }`}
            >
              {b.name}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// ── Right: spec summary + citations ────────────────────────────────────

type GraphObject = {
  id: string;
  type: string;
  name?: string;
  material?: string;
  dimensions?: { length: number; width: number; height: number } | null;
};

function RightSummary({
  hasDesign,
  dim,
  theme,
  objects,
  selectedObjectId,
  onSelectObject,
  editPrompt,
  onEditPromptChange,
  onSubmitEdit,
  isEditing,
  editError,
  canEdit,
}: {
  hasDesign: boolean;
  dim: Dim;
  theme: ArchTheme;
  objects: GraphObject[];
  selectedObjectId: string | null;
  onSelectObject: (id: string | null) => void;
  editPrompt: string;
  onEditPromptChange: (v: string) => void;
  onSubmitEdit: () => void;
  isEditing: boolean;
  editError: string | null;
  canEdit: boolean;
}) {
  const hasGraph = objects.length > 0;
  return (
    <aside className="w-80 shrink-0 bg-paper-soft border-l border-hairline overflow-y-auto draft-scroll">
      <div className="px-5 py-5">
        <SectionTag>Specification summary</SectionTag>
        {!hasDesign ? (
          <p className="mt-3 text-[13px] text-ink-soft leading-relaxed">
            Specs, materials, and BOQ will appear here once you generate a
            design. Every value carries its source inline.
          </p>
        ) : hasGraph ? (
          // Project-pipeline path — graph_data present, objects are
          // editable. The architect clicks any row to open an inline
          // prompt below it; submit calls /projects/{id}/edit and
          // pushes a new version into the gallery.
          <div className="mt-4 space-y-5">
            <ObjectsPanel
              objects={objects}
              selectedObjectId={selectedObjectId}
              onSelect={onSelectObject}
              editPrompt={editPrompt}
              onEditPromptChange={onEditPromptChange}
              onSubmit={onSubmitEdit}
              isEditing={isEditing}
              editError={editError}
              canEdit={canEdit}
            />
            <div>
              <h4 className="font-mono text-[10px] tracking-[0.14em] uppercase text-ink-mute mb-2">
                Meta
              </h4>
              <div className="border-t border-hairline">
                <CitedKV k="Dim" v={dim.toUpperCase()} />
                <CitedKV k="Theme" v={theme} />
              </div>
            </div>
          </div>
        ) : (
          // Anonymous / image-only fallback — no graph_data was
          // returned. Keep the static specification surfaces so the
          // page stays informative without an editable graph.
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

/* ObjectsPanel — Pass 2 of the edit loop.
   Shows every object the AI named in the design graph as a clickable
   row. Selecting a row opens an inline edit popover directly beneath
   it; submit fires /projects/{id}/edit and the gallery grows by one
   version. Architects iterate the design without re-prompting from
   scratch. */
function ObjectsPanel({
  objects,
  selectedObjectId,
  onSelect,
  editPrompt,
  onEditPromptChange,
  onSubmit,
  isEditing,
  editError,
  canEdit,
}: {
  objects: GraphObject[];
  selectedObjectId: string | null;
  onSelect: (id: string | null) => void;
  editPrompt: string;
  onEditPromptChange: (v: string) => void;
  onSubmit: () => void;
  isEditing: boolean;
  editError: string | null;
  canEdit: boolean;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <h4 className="font-mono text-[10px] tracking-[0.14em] uppercase text-ink-mute">
          Objects
        </h4>
        <span className="font-mono text-[10px] tnum text-ink-mute">
          {String(objects.length).padStart(2, "0")}
        </span>
      </div>
      <div className="border-t border-hairline">
        {objects.map((obj) => {
          const selected = obj.id === selectedObjectId;
          return (
            <div key={obj.id}>
              <button
                type="button"
                onClick={() => onSelect(selected ? null : obj.id)}
                disabled={!canEdit}
                className={`w-full text-left flex items-baseline justify-between border-b border-hairline py-2 font-mono text-[12px] transition-colors ${
                  selected
                    ? "bg-pencil-bg/60 -mx-2 px-2"
                    : canEdit
                    ? "hover:bg-paper -mx-2 px-2"
                    : "opacity-60 cursor-not-allowed"
                }`}
                aria-pressed={selected}
              >
                <span className="flex items-baseline gap-2">
                  {selected ? (
                    <span className="text-pencil text-[10px]" aria-hidden>
                      ●
                    </span>
                  ) : null}
                  <span className="text-ink-deep font-medium">
                    {obj.name?.trim() || formatObjectType(obj.type)}
                  </span>
                </span>
                <span className="text-ink-mute uppercase tracking-[0.08em] text-[10px]">
                  {obj.type}
                </span>
              </button>
              {selected ? (
                <EditPopover
                  prompt={editPrompt}
                  onPromptChange={onEditPromptChange}
                  onSubmit={onSubmit}
                  onCancel={() => onSelect(null)}
                  isEditing={isEditing}
                  editError={editError}
                  canEdit={canEdit}
                  objectName={obj.name?.trim() || formatObjectType(obj.type)}
                />
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* EditPopover — inline prompt + submit, opens directly beneath the
   selected object row. Pencil-red marker on the left edge marks it as
   the active edit context; pressing Esc or clicking another row closes
   it. Validation matches the backend schema (≥5 chars). */
function EditPopover({
  prompt,
  onPromptChange,
  onSubmit,
  onCancel,
  isEditing,
  editError,
  canEdit,
  objectName,
}: {
  prompt: string;
  onPromptChange: (v: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
  isEditing: boolean;
  editError: string | null;
  canEdit: boolean;
  objectName: string;
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  const valid = prompt.trim().length >= 5;
  return (
    <div className="border-b border-hairline -mx-2 px-3 py-3 bg-paper border-l-2 border-l-pencil">
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute">
          Edit · {objectName}
        </span>
        <button
          type="button"
          onClick={onCancel}
          className="text-ink-mute hover:text-ink text-[11px] font-mono"
          aria-label="Cancel edit"
        >
          ✕
        </button>
      </div>
      <textarea
        ref={ref}
        value={prompt}
        onChange={(e) => onPromptChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") onCancel();
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && valid) {
            e.preventDefault();
            onSubmit();
          }
        }}
        placeholder="Change material, dimensions, position, finish…"
        rows={2}
        disabled={isEditing || !canEdit}
        className="w-full resize-none outline-none bg-paper border border-hairline focus:border-graphite rounded-sm py-1.5 px-2 text-[12px] text-ink leading-relaxed font-mono placeholder:text-ink-mute"
      />
      {editError ? (
        <p className="mt-1.5 text-[11px] font-mono text-brick">{editError}</p>
      ) : null}
      <div className="mt-2 flex items-center justify-between">
        <span className="text-[10px] font-mono uppercase tracking-[0.1em] text-ink-mute">
          ⌘↵ to apply
        </span>
        <button
          type="button"
          onClick={onSubmit}
          disabled={!valid || isEditing || !canEdit}
          className="text-[11px] font-medium px-3 py-1.5 bg-ink-deep text-paper hover:bg-ink rounded-sm transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
        >
          {isEditing ? "Editing…" : "Apply edit"}
        </button>
      </div>
    </div>
  );
}

/* Pretty-print snake_case object types as Title-cased phrases.
   "dining_table" → "Dining table", "tv_unit" → "Tv unit". Used as a
   fallback when the AI didn't supply a `name` for an object. */
function formatObjectType(type: string): string {
  if (!type) return "Object";
  const first = type.replace(/_/g, " ");
  return first.charAt(0).toUpperCase() + first.slice(1);
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
