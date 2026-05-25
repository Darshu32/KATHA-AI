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
  brief as briefApi,
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
import BackendHealthBanner from "@/components/primitives/backend-health-banner";
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

/* BRD §3A working-drawing catalogue. Mirrors the backend
 * /working-drawings/types response so the UI can render the picker
 * without an extra fetch on mount. If the backend gains a new
 * drawing type, sync this list (or upgrade ViewsTab to fetch /types
 * on mount). */
const DRAWINGS_CATALOGUE: {
  id: string;
  name: string;
  stage: string;
  summary: string;
  /** True when the project-scoped fetch path is wired in api-client. */
  wired: boolean;
}[] = [
  { id: "plan_view",       name: "Plan View",       stage: "BRD 3A §1", summary: "Top-down — overall dims, key measurements, section refs, hatches.",                 wired: true },
  { id: "elevation_view",  name: "Elevation View",  stage: "BRD 3A §2", summary: "Front/side — heights, leg-base proportions, hardware + detail callouts.",          wired: false },
  { id: "section_view",    name: "Section View",    stage: "BRD 3A §3", summary: "Cut-through — internal layers, joints, seat depth, leg taper details.",            wired: false },
  { id: "isometric_view",  name: "Isometric View",  stage: "BRD 3A §4", summary: "3D iso — overall form, material finishes, superimposed dimensions.",               wired: false },
  { id: "detail_sheet",    name: "Detail Sheet",    stage: "BRD 3A §5", summary: "Zoomed details — joints, hardware, edge profiles, seams, transitions.",            wired: false },
];

/* BRD §2B diagram catalogue. Mirrors /diagrams/types. All 9 are wired
 * via design.generateDiagrams(projectId, version, diagramId). */
const DIAGRAMS_CATALOGUE: {
  id: string;
  name: string;
  stage: string;
  summary: string;
}[] = [
  { id: "concept_transparency", name: "Concept Transparency", stage: "BRD 2B §1",  summary: "Core design intent — material/form relationship, functional zones." },
  { id: "form_development",     name: "Form Development",     stage: "BRD 2B §2",  summary: "Four-stage evolution — volume → grid → subtract → articulate." },
  { id: "massing",              name: "Massing",              stage: "BRD 2B §3",  summary: "Horizontal + vertical massing — silhouette, weight, height bands." },
  { id: "volumetric_hierarchy", name: "Volumetric Hierarchy", stage: "BRD 2B §3+", summary: "Vertical × horizontal reading — stacking + allocation logic." },
  { id: "volumetric_block",     name: "Volumetric (Block)",   stage: "BRD 2B §4",  summary: "3D block read — masses, voids, slicing strategy." },
  { id: "design_process",       name: "Design Process",       stage: "BRD 2B §5",  summary: "Step-by-step narrative — decision points, rule drivers." },
  { id: "solid_void",           name: "Solid vs Void",        stage: "BRD 2B §6",  summary: "Solid % / void % — weight pattern, breathing room." },
  { id: "spatial_organism",     name: "Spatial Organism",     stage: "BRD 2B §7",  summary: "How a body inhabits the space — touchpoints, movement." },
  { id: "hierarchy",            name: "Hierarchy",            stage: "BRD 2B §8",  summary: "Three rankings — visual, material, functional." },
];

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
    seededFromBriefId,
    clearBriefSeed,
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

  // ── BRD §5A: export modal open/close ────────────────────────────────
  // Lives at the workspace level so the modal mounts as a top-level
  // portal-like overlay rather than nested inside the canvas header.
  const [exportOpen, setExportOpen] = useState(false);

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
        validation: switchRes.validation,
        mepCostEstimate: switchRes.mep_cost_estimate ?? undefined,
        codeCompliance: switchRes.code_compliance_summary,
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
        validation: editRes.validation,
        mepCostEstimate: editRes.mep_cost_estimate ?? undefined,
        codeCompliance: editRes.code_compliance_summary,
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
        validation: graphRes.validation,
        mepCostEstimate: graphRes.mep_cost_estimate ?? undefined,
        codeCompliance: graphRes.code_compliance_summary,
      });
      setActiveProject(projectId, graphRes.version);

      // BRD §3.6 — first successful generation after a chat handoff
      // dismisses the seed banner. From now on the workspace state is
      // owned by this design session, not the originating brief.
      if (seededFromBriefId) clearBriefSeed();
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
      <BackendHealthBanner />
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
      <ExportModal
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        projectId={activeProjectId}
        latestVersion={latestGeneration?.version ?? null}
        token={token ?? ""}
      />

      {/* BRD §3.6 — chat→image-gen handoff banner. Shown after the
          chat workspace's "Ready to design" pill seeds this store.
          Dismiss removes the banner; first generation also auto-clears
          it (see runGeneration). */}
      {seededFromBriefId ? (
        <BriefSeedBanner
          briefId={seededFromBriefId}
          onDismiss={clearBriefSeed}
        />
      ) : null}

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
            onOpenExport={() => setExportOpen(true)}
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
          codeCompliance={latestGeneration?.codeCompliance}
          validation={latestGeneration?.validation}
          mepCost={latestGeneration?.mepCostEstimate}
          activeProjectId={activeProjectId}
          latestVersion={latestGeneration?.version ?? null}
          token={token ?? ""}
        />
      </div>

      {terminalOpen ? (
        <TerminalPanel
          tab={terminalTab}
          setTab={setTerminalTab}
          hasDesign={generations.length > 0}
          validation={latestGeneration?.validation}
          mepCost={latestGeneration?.mepCostEstimate}
          onClose={() => toggleTerminal()}
        />
      ) : (
        <TerminalCollapsed onOpen={() => toggleTerminal()} />
      )}
    </div>
  );
}

// ── Brief seed banner (BRD §3.6) ───────────────────────────────────────

function BriefSeedBanner({
  briefId,
  onDismiss,
}: {
  briefId: string;
  onDismiss: () => void;
}) {
  return (
    <div className="px-5 py-2 border-b border-hairline bg-emerald-50/60 flex items-center gap-3 text-[12px]">
      <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-emerald-600 text-white text-[10px] font-bold">
        ✓
      </span>
      <div className="flex-1 min-w-0">
        <span className="font-medium text-emerald-900">Seeded from chat brief.</span>{" "}
        <span className="text-emerald-800">
          Type, theme, dimensions, and brief have been auto-filled. Press{" "}
          <span className="font-mono font-medium">Generate</span> to start.
        </span>
      </div>
      <span className="text-[10px] font-mono text-emerald-700/70 hidden sm:inline">
        {briefId.slice(0, 8)}…
      </span>
      <button
        type="button"
        onClick={onDismiss}
        className="text-emerald-700 hover:text-emerald-900 text-[11px] underline-offset-2 hover:underline"
        title="Dismiss banner"
      >
        Dismiss
      </button>
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
            KATHA AI
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

/* AccordionSection — collapsible card used by the left rail.
 * Title sits in a clickable header row with a chevron; expanded body
 * sits below. Mono uppercase title to match the SectionTag register. */
function AccordionSection({
  title,
  badge,
  open,
  onToggle,
  children,
  defaultOpen,
}: {
  title: string;
  badge?: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  void defaultOpen; // reserved for future "remember last state" wiring
  return (
    <section className="border-b border-hairline last:border-b-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="w-full px-5 py-3 flex items-center justify-between gap-2 text-left hover:bg-paper transition-colors group"
      >
        <span className="font-mono text-[10.5px] uppercase tracking-tagged text-ink-soft group-hover:text-ink-deep transition-colors">
          {title}
        </span>
        <span className="flex items-center gap-2">
          {badge ? (
            <span className="font-mono text-[9.5px] uppercase tracking-tagged text-ink-mute">
              {badge}
            </span>
          ) : null}
          <svg
            width="10"
            height="10"
            viewBox="0 0 10 10"
            className={`text-ink-mute transition-transform ${open ? "rotate-90" : ""}`}
            aria-hidden="true"
          >
            <path d="M3 1.5l3 3.5-3 3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" fill="none" />
          </svg>
        </span>
      </button>
      {open ? <div className="px-5 pb-4">{children}</div> : null}
    </section>
  );
}

/* LeftControls — BRD §1A 5-section brief in a vertical accordion.
 *
 * Section map (Brief is expanded by default; the rest collapse for
 * focused entry, multi-open supported):
 *   1. Brief        — Project type, Scope, Theme (TBD), Dimensionality, Aspect ratio
 *   2. Space & Site — Dimensions, climate, site constraints (Day 2)
 *   3. Requirements — Functional, aesthetic, budget, timeline (Day 2)
 *   4. Regulatory   — Country/state/city, codes, compliance notes (Day 2)
 *
 * Day 1 ships the accordion shell with the existing brief controls
 * landed under section 1. Sections 2–4 carry "Coming Day 2" placeholders
 * so the architect sees where the brief grows into. */
// ── Brief form schemas (BRD §1A.3/4/5) ────────────────────────────────────
//
// Form state is kept loose (strings, comma-separated lists) so inputs
// feel forgiving. Serialisers below coerce into the strict types the
// backend Pydantic models expect:
//   BriefSpace        → SpaceParameters + DimensionsIn + SiteConditions
//   BriefRequirements → ClientRequirements
//   BriefRegulatory   → RegulatoryContext + ClimaticZoneEnum

type DimUnit = "m" | "mm" | "ft";
type ClimaticZone = "" | "hot_dry" | "warm_humid" | "composite" | "temperate" | "cold";

type BriefSpace = {
  length: string;
  width: string;
  height: string;
  unit: DimUnit;
  orientation: string;
  constraints: string;       // comma-separated, "no basement, slope ≤ 5%"
  site_notes: string;        // free-text rolling up floor/access/light/vent/noise
};

type BriefRequirements = {
  functional_needs: string;  // comma-separated
  aesthetic_preferences: string;
  narrative: string;
  budget: string;            // numeric string for input flexibility
  timeline_weeks: string;
};

type BriefRegulatory = {
  country: string;
  state: string;
  city: string;
  postal_code: string;
  building_codes: string;    // comma-separated
  climatic_zone: ClimaticZone;
  compliance_notes: string;
};

const emptySpace: BriefSpace = {
  length: "", width: "", height: "", unit: "m",
  orientation: "", constraints: "", site_notes: "",
};

const emptyRequirements: BriefRequirements = {
  functional_needs: "", aesthetic_preferences: "", narrative: "",
  budget: "", timeline_weeks: "",
};

const emptyRegulatory: BriefRegulatory = {
  country: "", state: "", city: "", postal_code: "",
  building_codes: "", climatic_zone: "", compliance_notes: "",
};

const splitCsv = (s: string): string[] =>
  s.split(",").map((x) => x.trim()).filter(Boolean);

function serialiseSpace(s: BriefSpace): Record<string, unknown> | undefined {
  const length = parseFloat(s.length);
  const width = parseFloat(s.width);
  // SpaceParameters requires length+width; skip the section if blank
  // (the backend tolerates omitted sections via Optional fields on
  // BriefIntakePayload). Architects can save without dimensions yet.
  if (!isFinite(length) || !isFinite(width) || length <= 0 || width <= 0) {
    return undefined;
  }
  const height = parseFloat(s.height);
  return {
    dimensions: {
      length,
      width,
      ...(isFinite(height) && height > 0 ? { height } : {}),
      unit: s.unit,
    },
    constraints: splitCsv(s.constraints),
    site_conditions: {
      orientation: s.orientation,
      noise_context: s.site_notes,  // rolled into noise_context for v1
    },
  };
}

function serialiseRequirements(r: BriefRequirements): Record<string, unknown> | undefined {
  const empty = !r.functional_needs && !r.aesthetic_preferences && !r.narrative && !r.budget && !r.timeline_weeks;
  if (empty) return undefined;
  const budget = parseFloat(r.budget);
  const weeks = parseInt(r.timeline_weeks, 10);
  return {
    functional_needs: splitCsv(r.functional_needs),
    aesthetic_preferences: splitCsv(r.aesthetic_preferences),
    narrative: r.narrative,
    ...(isFinite(budget) && budget >= 0 ? { budget, currency: "INR" } : {}),
    ...(isFinite(weeks) && weeks >= 0 ? { timeline_weeks: weeks } : {}),
  };
}

function serialiseRegulatory(g: BriefRegulatory): Record<string, unknown> | undefined {
  const empty = !g.country && !g.state && !g.city && !g.postal_code && !g.building_codes && !g.climatic_zone && !g.compliance_notes;
  if (empty) return undefined;
  return {
    country: g.country,
    state: g.state,
    city: g.city,
    postal_code: g.postal_code,
    building_codes: splitCsv(g.building_codes),
    ...(g.climatic_zone ? { climatic_zone: g.climatic_zone } : {}),
    compliance_notes: g.compliance_notes,
  };
}

// ── Brief form primitives — tiny styled inputs shared by all three
//    section forms. All keep the paper/ink/hairline register and
//    quiet hover/focus states. Width-100% so they stack cleanly in
//    the narrow left rail. ─────────────────────────────────────────

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="block font-mono text-[10.5px] uppercase tracking-tagged text-ink-mute mb-1">
      {children}
    </label>
  );
}

function TextInput({
  value, onChange, placeholder, type = "text",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: "text" | "number";
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full px-2 py-1.5 text-[12.5px] bg-paper border border-hairline rounded-sm outline-none focus:border-graphite placeholder:text-ink-mute"
    />
  );
}

function TextArea({
  value, onChange, placeholder, rows = 2,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      rows={rows}
      className="w-full px-2 py-1.5 text-[12.5px] bg-paper border border-hairline rounded-sm outline-none focus:border-graphite resize-none leading-snug placeholder:text-ink-mute"
    />
  );
}

function SelectInput<T extends string>({
  value, onChange, options, placeholder,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
  placeholder?: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as T)}
      className="w-full px-2 py-1.5 text-[12.5px] bg-paper border border-hairline rounded-sm outline-none focus:border-graphite"
    >
      {placeholder ? <option value="">{placeholder}</option> : null}
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

// ── Form components — one per BRD §1A section ─────────────────────────────

const ORIENTATIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const UNITS: DimUnit[] = ["m", "mm", "ft"];
const CLIMATE_ZONES: { value: ClimaticZone; label: string }[] = [
  { value: "hot_dry",     label: "Hot-Dry" },
  { value: "warm_humid",  label: "Warm-Humid" },
  { value: "composite",   label: "Composite" },
  { value: "temperate",   label: "Temperate" },
  { value: "cold",        label: "Cold" },
];

function SpaceSiteForm({
  value, onChange,
}: {
  value: BriefSpace;
  onChange: (v: BriefSpace) => void;
}) {
  const set = <K extends keyof BriefSpace>(k: K, v: BriefSpace[K]) =>
    onChange({ ...value, [k]: v });
  return (
    <div className="space-y-4">
      <div>
        <FieldLabel>Dimensions</FieldLabel>
        <div className="grid grid-cols-3 gap-1 mb-1.5">
          <TextInput type="number" placeholder="L"
            value={value.length} onChange={(v) => set("length", v)} />
          <TextInput type="number" placeholder="W"
            value={value.width} onChange={(v) => set("width", v)} />
          <TextInput type="number" placeholder="H"
            value={value.height} onChange={(v) => set("height", v)} />
        </div>
        <div className="flex gap-1">
          {UNITS.map((u) => (
            <button
              key={u}
              type="button"
              className="slide-pill flex-1 text-center !text-[11px] !px-1.5"
              data-active={u === value.unit}
              onClick={() => set("unit", u)}
            >
              {u}
            </button>
          ))}
        </div>
      </div>
      <div>
        <FieldLabel>Orientation</FieldLabel>
        <div className="grid grid-cols-4 gap-1">
          {ORIENTATIONS.map((o) => (
            <button
              key={o}
              type="button"
              className="slide-pill text-center !text-[11px] !px-1.5"
              data-active={o === value.orientation}
              onClick={() => set("orientation", o === value.orientation ? "" : o)}
            >
              {o}
            </button>
          ))}
        </div>
      </div>
      <div>
        <FieldLabel>Constraints (comma-separated)</FieldLabel>
        <TextArea rows={2}
          placeholder="No basement, slope ≤ 5%, retain 2 trees"
          value={value.constraints}
          onChange={(v) => set("constraints", v)} />
      </div>
      <div>
        <FieldLabel>Site notes</FieldLabel>
        <TextArea rows={2}
          placeholder="Floor level, access, natural light, ventilation, noise context"
          value={value.site_notes}
          onChange={(v) => set("site_notes", v)} />
      </div>
    </div>
  );
}

function RequirementsForm({
  value, onChange,
}: {
  value: BriefRequirements;
  onChange: (v: BriefRequirements) => void;
}) {
  const set = <K extends keyof BriefRequirements>(k: K, v: BriefRequirements[K]) =>
    onChange({ ...value, [k]: v });
  return (
    <div className="space-y-4">
      <div>
        <FieldLabel>Functional needs (comma-separated)</FieldLabel>
        <TextArea rows={2}
          placeholder="3 bedrooms, home office, prayer room"
          value={value.functional_needs}
          onChange={(v) => set("functional_needs", v)} />
      </div>
      <div>
        <FieldLabel>Aesthetic preferences (comma-separated)</FieldLabel>
        <TextArea rows={2}
          placeholder="Minimal, warm woods, indoor planting"
          value={value.aesthetic_preferences}
          onChange={(v) => set("aesthetic_preferences", v)} />
      </div>
      <div>
        <FieldLabel>Narrative</FieldLabel>
        <TextArea rows={3}
          placeholder="Long-form description of the client's intent"
          value={value.narrative}
          onChange={(v) => set("narrative", v)} />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <FieldLabel>Budget (₹)</FieldLabel>
          <TextInput type="number" placeholder="2500000"
            value={value.budget}
            onChange={(v) => set("budget", v)} />
        </div>
        <div>
          <FieldLabel>Timeline (weeks)</FieldLabel>
          <TextInput type="number" placeholder="12"
            value={value.timeline_weeks}
            onChange={(v) => set("timeline_weeks", v)} />
        </div>
      </div>
    </div>
  );
}

function RegulatoryForm({
  value, onChange,
}: {
  value: BriefRegulatory;
  onChange: (v: BriefRegulatory) => void;
}) {
  const set = <K extends keyof BriefRegulatory>(k: K, v: BriefRegulatory[K]) =>
    onChange({ ...value, [k]: v });
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2">
        <div>
          <FieldLabel>Country</FieldLabel>
          <TextInput placeholder="India"
            value={value.country} onChange={(v) => set("country", v)} />
        </div>
        <div>
          <FieldLabel>State</FieldLabel>
          <TextInput placeholder="Karnataka"
            value={value.state} onChange={(v) => set("state", v)} />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <FieldLabel>City</FieldLabel>
          <TextInput placeholder="Bangalore"
            value={value.city} onChange={(v) => set("city", v)} />
        </div>
        <div>
          <FieldLabel>Postal</FieldLabel>
          <TextInput placeholder="560001"
            value={value.postal_code} onChange={(v) => set("postal_code", v)} />
        </div>
      </div>
      <div>
        <FieldLabel>Building codes (comma-separated)</FieldLabel>
        <TextInput placeholder="NBC-2016, IS-875, ECBC"
          value={value.building_codes}
          onChange={(v) => set("building_codes", v)} />
      </div>
      <div>
        <FieldLabel>Climatic zone</FieldLabel>
        <SelectInput
          value={value.climatic_zone}
          onChange={(v) => set("climatic_zone", v)}
          options={CLIMATE_ZONES}
          placeholder="— Select zone —"
        />
      </div>
      <div>
        <FieldLabel>Compliance notes</FieldLabel>
        <TextArea rows={2}
          placeholder="Fire NOC, ramp slope ≤ 1:12, EV charging required"
          value={value.compliance_notes}
          onChange={(v) => set("compliance_notes", v)} />
      </div>
    </div>
  );
}

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
  // Multi-open accordion — architects often want to see Brief + Space
  // simultaneously when tuning a design. State persists to localStorage
  // so the next session re-opens the same sections (small but high-
  // value for architects who tune Brief + Regulatory together every
  // time). Brief is open by default on first visit.
  const ACCORDION_KEY = "katha.design.accordion.openSections";
  const [openSections, setOpenSections] = useState<Set<string>>(() => {
    if (typeof window === "undefined") return new Set(["brief"]);
    try {
      const raw = localStorage.getItem(ACCORDION_KEY);
      if (raw) return new Set(JSON.parse(raw) as string[]);
    } catch {}
    return new Set(["brief"]);
  });
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      localStorage.setItem(ACCORDION_KEY, JSON.stringify([...openSections]));
    } catch {}
  }, [openSections]);
  const toggle = (id: string) => {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Brief section state — three controlled forms backed by their own
  // schema (BRD §1A.3/4/5). Save button packages all three into a
  // single /brief/intake POST. State lives here for v1; if other
  // surfaces (Generate, Notes) need to read the brief we can lift it
  // up to the workspace store later.
  const [space, setSpace] = useState<BriefSpace>(emptySpace);
  const [requirements, setRequirements] = useState<BriefRequirements>(emptyRequirements);
  const [regulatory, setRegulatory] = useState<BriefRegulatory>(emptyRegulatory);
  const [saving, setSaving] = useState(false);
  const [briefSaved, setBriefSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const notify = useToastStore((s) => s.notify);

  const saveBrief = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const payload: import("@/lib/api-client").BriefIntakePayload = {
        project_type: { type: projectType, scale: "" },
        space: serialiseSpace(space),
        requirements: serialiseRequirements(requirements),
        regulatory: serialiseRegulatory(regulatory),
      };
      await briefApi.intake(payload);
      setBriefSaved(true);
      notify({
        type: "success",
        title: "Brief saved",
        message: "All five sections validated and stored.",
        durationMs: 2500,
      });
      setTimeout(() => setBriefSaved(false), 2500);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Could not save brief";
      setSaveError(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <aside className="w-72 shrink-0 bg-paper-soft border-r border-hairline overflow-y-auto draft-scroll">
      <AccordionSection
        title="Brief"
        open={openSections.has("brief")}
        onToggle={() => toggle("brief")}
      >
        <div className="space-y-5">
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
      </AccordionSection>

      <AccordionSection
        title="Space & Site"
        open={openSections.has("space")}
        onToggle={() => toggle("space")}
      >
        <SpaceSiteForm value={space} onChange={setSpace} />
      </AccordionSection>

      <AccordionSection
        title="Requirements"
        open={openSections.has("requirements")}
        onToggle={() => toggle("requirements")}
      >
        <RequirementsForm value={requirements} onChange={setRequirements} />
      </AccordionSection>

      <AccordionSection
        title="Regulatory"
        open={openSections.has("regulatory")}
        onToggle={() => toggle("regulatory")}
      >
        <RegulatoryForm value={regulatory} onChange={setRegulatory} />
      </AccordionSection>

      {/* Sticky Save brief footer — packages the three section forms
          (BRD §1A.3/4/5) plus the Brief chiclets into a /brief/intake
          payload. Currency hard-defaulted to INR for v1 since the
          cost engine is INR-only today. */}
      <div className="sticky bottom-0 bg-paper-soft border-t border-hairline px-5 py-3">
        <button
          type="button"
          onClick={saveBrief}
          disabled={saving}
          className="w-full text-[13px] font-medium px-3 py-2 bg-ink-deep text-paper hover:bg-ink rounded-md transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
        >
          {saving ? "Saving…" : briefSaved ? "Saved ✓" : "Save brief"}
        </button>
        {saveError ? (
          <p className="mt-1.5 text-[11px] font-mono text-brick">{saveError}</p>
        ) : null}
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
  const [elapsedSec, setElapsedSec] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 180) + "px";
  }, [prompt]);

  // Elapsed counter while generating — gives the architect a sense of
  // forward progress during the 5-15s provider round-trip. Resets on
  // each new generation. Reads as "Generating… 7s" on the button.
  useEffect(() => {
    if (!isGenerating) {
      setElapsedSec(0);
      return;
    }
    const startedAt = Date.now();
    const id = setInterval(() => {
      setElapsedSec(Math.floor((Date.now() - startedAt) / 1000));
    }, 250);
    return () => clearInterval(id);
  }, [isGenerating]);

  return (
    <div className="border-t border-hairline bg-paper px-6 py-4">
      <div className="max-w-4xl mx-auto">
        <div className="border border-hairline rounded-xl bg-paper-soft/60 p-3 flex items-end gap-3 focus-within:border-graphite transition-colors">
          <textarea
            ref={ref}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Describe what you want — KATHA AI tunes the output to your project type."
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
            className="shrink-0 text-[13px] font-medium px-4 py-1.5 bg-ink-deep text-paper hover:bg-ink rounded-md transition-colors disabled:opacity-30 disabled:cursor-not-allowed tabular-nums"
          >
            {isGenerating
              ? `Generating… ${elapsedSec}s`
              : "Generate"}
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
  onOpenExport,
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
  onOpenExport: () => void;
}) {
  void projectType; // explicitly unused — kept on signature for future telemetry
  void projectTypeLabel; // unused since the breadcrumb moved to left rail
  void scope;
  void dim;
  const projectGenerations = generations.filter((g) => g.version != null);
  // The left-side breadcrumb ("Canvas · Residential · Interior · 3D")
  // was redundant once the left rail's Brief accordion landed — that
  // info lives there now. Header is trimmed to the action controls
  // (Theme switcher + Version timeline) on the right.
  return (
    <div className="px-6 py-2 border-b border-hairline bg-paper/85 backdrop-blur-sm flex items-center justify-end gap-3">
      {themeSwitchError ? (
        <span className="text-[11px] font-mono text-brick mr-auto">
          {themeSwitchError}
        </span>
      ) : null}
      <ThemeSwitchChip
        theme={theme}
        themesList={themesList}
        onChoose={onChooseTheme}
        isSwitching={isSwitchingTheme}
        hasActiveProject={hasActiveProject}
      />
      <HapticReadyBadge hasActiveProject={hasActiveProject} />
      <ExportButton
        onClick={onOpenExport}
        disabled={!hasActiveProject}
      />
      {projectGenerations.length > 0 ? (
        <VersionTimeline generations={projectGenerations} />
      ) : null}
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
          body={`Describe the design. KATHA AI treats it as a ${lowerLabel} project and pulls the right codes + cost defaults.`}
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

type RightTab = "summary" | "views" | "specs" | "cost" | "compliance" | "recs";

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
  codeCompliance,
  validation,
  mepCost,
  activeProjectId,
  latestVersion,
  token,
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
  codeCompliance?: import("@/lib/types").CodeComplianceEntry[];
  validation?: import("@/lib/types").ValidationReport;
  mepCost?: import("@/lib/types").MepCostEstimate;
  activeProjectId: string | null;
  latestVersion: number | null;
  token: string;
}) {
  const hasGraph = objects.length > 0;
  const TAB_KEY = "katha.design.rightRail.activeTab";
  const [tab, setTab] = useState<RightTab>(() => {
    if (typeof window === "undefined") return "summary";
    try {
      const saved = localStorage.getItem(TAB_KEY) as RightTab | null;
      const allowed: RightTab[] = ["summary", "views", "specs", "cost", "compliance", "recs"];
      if (saved && allowed.includes(saved)) return saved;
    } catch {}
    return "summary";
  });
  useEffect(() => {
    if (typeof window === "undefined") return;
    try { localStorage.setItem(TAB_KEY, tab); } catch {}
  }, [tab]);

  // Tab definitions — all six surfaces visible at full width. Specs
  // is the placeholder tab; its body carries the "Post-sprint" note,
  // so no badge is needed on the strip itself.
  const tabs: { id: RightTab; label: string; badge?: string }[] = [
    { id: "summary", label: "Summary" },
    { id: "views", label: "Views" },
    { id: "specs", label: "Specs" },
    { id: "cost", label: "Cost" },
    { id: "compliance", label: "Checks" },
    { id: "recs", label: "Recs" },
  ];

  return (
    <aside className="w-80 shrink-0 bg-paper-soft border-l border-hairline overflow-y-auto draft-scroll flex flex-col">
      {/* Sticky tab bar — sits at the top of the rail; pencil-red
          underline marks the active tab (same register as the bottom
          terminal tabs for visual continuity). ARIA roles let screen
          readers and keyboard users navigate with arrow keys + Tab. */}
      <div
        role="tablist"
        aria-label="Design review surfaces"
        className="sticky top-0 z-10 bg-paper-soft border-b border-hairline px-2 flex items-center overflow-x-auto draft-scroll"
      >
        {tabs.map((t) => {
          const active = t.id === tab;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              id={`tab-${t.id}`}
              aria-selected={active}
              aria-controls={`tabpanel-${t.id}`}
              tabIndex={active ? 0 : -1}
              onClick={() => setTab(t.id)}
              className={`font-mono text-[10.5px] uppercase tracking-[0.10em] px-2 py-2.5 transition-colors border-b-2 whitespace-nowrap focus:outline-none focus-visible:ring-2 focus-visible:ring-pencil/40 focus-visible:rounded-sm ${
                active
                  ? "text-ink-deep border-pencil"
                  : "text-ink-mute hover:text-ink-soft border-transparent"
              }`}
            >
              {t.label}
              {t.badge ? (
                <span className="ml-1 text-ink-mute/70">·{t.badge}</span>
              ) : null}
            </button>
          );
        })}
      </div>

      <div
        role="tabpanel"
        id={`tabpanel-${tab}`}
        aria-labelledby={`tab-${tab}`}
        className="px-5 py-5 flex-1"
      >
        {tab === "summary" ? (
          <SummaryTab
            hasDesign={hasDesign}
            hasGraph={hasGraph}
            dim={dim}
            theme={theme}
            objects={objects}
            selectedObjectId={selectedObjectId}
            onSelectObject={onSelectObject}
            editPrompt={editPrompt}
            onEditPromptChange={onEditPromptChange}
            onSubmitEdit={onSubmitEdit}
            isEditing={isEditing}
            editError={editError}
            canEdit={canEdit}
          />
        ) : tab === "compliance" ? (
          <ChecksTab
            validation={validation}
            codeCompliance={codeCompliance}
          />
        ) : tab === "recs" ? (
          <RecsTab
            hasActiveProject={!!activeProjectId && hasDesign}
            activeProjectId={activeProjectId}
            latestVersion={latestVersion}
            token={token}
          />
        ) : tab === "views" ? (
          <ViewsTab
            hasActiveProject={!!activeProjectId && hasDesign}
            activeProjectId={activeProjectId}
            latestVersion={latestVersion}
            token={token}
          />
        ) : tab === "cost" ? (
          <CostTab hasDesign={hasDesign} mepCost={mepCost} />
        ) : tab === "specs" ? (
          <SpecsTab
            hasActiveProject={!!activeProjectId && hasDesign}
            activeProjectId={activeProjectId}
            latestVersion={latestVersion}
            token={token}
          />
        ) : (
          <TabPlaceholder tab={tab} />
        )}
      </div>
    </aside>
  );
}

/* ViewsTab — BRD §2B diagrams + §3A working drawings as click-to-view
 * cards. Clicking a wired entry fires the right project-scoped API call
 * and opens a modal with the returned SVG. Unwired drawings (everything
 * except plan_view today) surface a transparent "Coming Day 3" tag so
 * the architect sees the full surface area without bumping into dead
 * buttons silently. */
function ViewsTab({
  hasActiveProject,
  activeProjectId,
  latestVersion,
  token,
}: {
  hasActiveProject: boolean;
  activeProjectId: string | null;
  latestVersion: number | null;
  token: string;
}) {
  const [loading, setLoading] = useState<string | null>(null);
  const [view, setView] = useState<{
    title: string;
    svg: string;
  } | null>(null);
  const notify = useToastStore((s) => s.notify);

  // Fires the right project-scoped backend call. Drawings only have
  // plan_view wired today (via design.getFloorPlan); other drawings
  // need a project-pipeline endpoint that the design.* namespace will
  // gain later in the sprint. Diagrams are all wired via
  // design.generateDiagrams, which targets a single diagram_id.
  const open = async (kind: "drawing" | "diagram", id: string, name: string) => {
    if (!hasActiveProject || !activeProjectId) {
      notify({
        type: "warning",
        title: "Generate a design first",
        message: "Views unlock once the canvas has a project version to read from.",
      });
      return;
    }
    setLoading(`${kind}:${id}`);
    try {
      if (kind === "diagram") {
        const res = await designApi.generateDiagrams(
          token,
          activeProjectId,
          latestVersion ?? undefined,
          id,
        );
        const match = res.diagrams.find((d) => d.id === id) ?? res.diagrams[0];
        if (!match?.svg) {
          notify({
            type: "warning",
            title: name,
            message: match?.error ?? "Generator returned no SVG.",
          });
        } else {
          setView({ title: name, svg: match.svg });
        }
      } else if (id === "plan_view") {
        const res = await designApi.getFloorPlan(
          token,
          activeProjectId,
          latestVersion ?? undefined,
        );
        if (!res.preview_svg) {
          notify({ type: "warning", title: name, message: "No preview returned." });
        } else {
          setView({ title: name, svg: res.preview_svg });
        }
      } else {
        notify({
          type: "info",
          title: `${name} — Day 3`,
          message: "Project-pipeline route for this drawing lands in Day 3.",
        });
      }
    } catch (e) {
      toastError(e, `Could not load ${name}`);
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="space-y-6">
      <ViewsSection title="Working Drawings" badge="BRD §3A">
        {DRAWINGS_CATALOGUE.map((d) => (
          <ViewCard
            key={d.id}
            name={d.name}
            stage={d.stage}
            summary={d.summary}
            loading={loading === `drawing:${d.id}`}
            disabled={!hasActiveProject}
            extra={d.wired ? null : "Day 3"}
            onClick={() => open("drawing", d.id, d.name)}
          />
        ))}
      </ViewsSection>

      <ViewsSection title="BRD Diagrams" badge="BRD §2B · 9 types">
        {DIAGRAMS_CATALOGUE.map((d) => (
          <ViewCard
            key={d.id}
            name={d.name}
            stage={d.stage}
            summary={d.summary}
            loading={loading === `diagram:${d.id}`}
            disabled={!hasActiveProject}
            onClick={() => open("diagram", d.id, d.name)}
          />
        ))}
      </ViewsSection>

      {view ? (
        <ViewModal
          title={view.title}
          svg={view.svg}
          onClose={() => setView(null)}
        />
      ) : null}
    </div>
  );
}

/* ViewsSection — grouped cards with a quiet header. */
function ViewsSection({
  title,
  badge,
  children,
}: {
  title: string;
  badge: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="flex items-baseline justify-between mb-2.5">
        <SectionTag>{title}</SectionTag>
        <span className="font-mono text-[10px] uppercase tracking-tagged text-ink-mute">
          {badge}
        </span>
      </div>
      <div className="space-y-1.5">{children}</div>
    </section>
  );
}

/* ViewCard — one row in the catalogue list. Loading spinner + disabled
 * style + optional "Day N" tag for unwired entries. */
function ViewCard({
  name,
  stage,
  summary,
  loading,
  disabled,
  extra,
  onClick,
}: {
  name: string;
  stage: string;
  summary: string;
  loading: boolean;
  disabled: boolean;
  extra?: string | null;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || loading}
      className={`w-full text-left px-3 py-2 border border-hairline rounded-md bg-paper hover:bg-paper-deep/40 hover:border-graphite transition-colors ${
        disabled ? "opacity-50 cursor-not-allowed" : ""
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-medium text-ink-deep">
          {name}
        </span>
        <span className="font-mono text-[10px] uppercase tracking-tagged text-ink-mute shrink-0">
          {loading ? "…" : extra ?? stage}
        </span>
      </div>
      <p className="mt-0.5 text-[11.5px] text-ink-soft leading-snug line-clamp-2">
        {summary}
      </p>
    </button>
  );
}

/* ViewModal — full-bleed overlay that frames the returned SVG against
 * a paper-soft scrim. Click outside or press × to dismiss. */
function ViewModal({
  title,
  svg,
  onClose,
}: {
  title: string;
  svg: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 bg-ink-deep/40 backdrop-blur-sm flex items-center justify-center p-8"
      onClick={onClose}
    >
      <div
        className="bg-paper rounded-lg shadow-card max-w-5xl max-h-[90vh] w-full overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-3 border-b border-hairline flex items-center justify-between">
          <SectionTag>{title}</SectionTag>
          <button
            type="button"
            onClick={onClose}
            className="text-ink-mute hover:text-ink-deep transition-colors"
            aria-label="Close"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div
          className="flex-1 overflow-auto p-5 bg-paper-soft"
          // SVG comes from the backend generator; it's our own server-
          // rendered output, not user input.
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>
    </div>
  );
}

/* CostTab — BRD §4 cost engine surfaced into the right rail. Reads
 * the MepCostEstimate that arrives on every generation (no extra
 * fetch needed); falls back to a friendly placeholder when no design
 * is loaded yet. Sensitivity ±10% lands in Day 4 alongside the
 * recommendations panel — the placeholder strip below holds its slot. */
function CostTab({
  hasDesign,
  mepCost,
}: {
  hasDesign: boolean;
  mepCost?: import("@/lib/types").MepCostEstimate;
}) {
  if (!hasDesign) {
    return (
      <div className="space-y-3">
        <SectionTag>Cost</SectionTag>
        <p className="text-[13px] text-ink-soft leading-relaxed">
          Cost engine output — material / labor / overhead / margin
          breakdown, with live MCX prices and ±10% sensitivity — populates
          here after the first generation.
        </p>
        <p className="font-mono text-[10.5px] uppercase tracking-tagged text-ink-mute">
          ← /estimates/* · BRD §4
        </p>
      </div>
    );
  }
  if (!mepCost) {
    return (
      <div className="space-y-3">
        <SectionTag>Cost</SectionTag>
        <p className="text-[13px] text-ink-soft leading-relaxed italic">
          This version didn't produce a cost estimate. Re-prompt or
          regenerate to engage the cost engine.
        </p>
      </div>
    );
  }

  const total = mepCost.total_inr;
  const formatINR = (n?: number) =>
    n == null ? "—" : `₹${Math.round(n).toLocaleString("en-IN")}`;

  return (
    <div className="space-y-5">
      {/* Headline band — total cost range, area, and jurisdiction
          carry the BRD §4 framing in one glance. */}
      <section>
        <SectionTag>Total estimate</SectionTag>
        <div className="mt-2 border border-hairline rounded-md bg-paper p-3">
          <div className="font-mono text-[20px] text-ink-deep tnum tracking-tight">
            {formatINR(total.low)}
            <span className="text-ink-mute mx-1.5">→</span>
            {formatINR(total.high)}
          </div>
          <div className="mt-1 flex items-center justify-between font-mono text-[10.5px] uppercase tracking-tagged text-ink-mute">
            <span>{mepCost.area_m2.toFixed(1)} m² · {mepCost.currency}</span>
            <span>{mepCost.jurisdiction || "—"}</span>
          </div>
        </div>
      </section>

      {/* Per-system breakdown — HVAC / Electrical / Plumbing / Fire-fighting.
          Each row shows the system, its rate band per m², and total band. */}
      <section>
        <SectionTag>By system</SectionTag>
        <div className="mt-2 border-t border-hairline">
          {mepCost.systems.map((s) => (
            <div
              key={s.system + s.key}
              className="py-2 border-b border-hairline last:border-b-0 flex items-baseline justify-between gap-2"
            >
              <div className="min-w-0">
                <div className="text-[12.5px] text-ink-deep font-medium capitalize">
                  {s.system.replace(/_/g, " ")}
                </div>
                <div className="font-mono text-[10.5px] text-ink-mute tnum">
                  {formatINR(s.rate_inr_m2.low)}/m²
                  <span className="mx-1">→</span>
                  {formatINR(s.rate_inr_m2.high)}/m²
                </div>
              </div>
              <div className="text-right shrink-0 font-mono text-[12px] text-ink tnum">
                {formatINR(s.total_inr.low)}
                <span className="text-ink-mute mx-1">→</span>
                {formatINR(s.total_inr.high)}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Sensitivity placeholder — slot reserved for Day 4 wiring of
          /sensitivity. The 4 BRD what-ifs (material/labor/overhead ±10%)
          + volume curves (1·5·10 pieces) will land here. */}
      <section>
        <div className="flex items-baseline justify-between mb-2">
          <SectionTag>Sensitivity</SectionTag>
          <span className="font-mono text-[10px] uppercase tracking-tagged text-pencil">
            Day 4
          </span>
        </div>
        <p className="text-[11.5px] text-ink-soft leading-snug">
          ±10% shocks on material · labor · overhead and volume curves
          at 1 / 5 / 10 pieces land in Day 4 — wires to{" "}
          <span className="font-mono text-[11px]">/sensitivity</span>.
        </p>
      </section>
    </div>
  );
}

/* ExportModal — opens from the Export chip in the canvas header.
 * Lists every backend-supported format, grouped by family so the
 * architect picks by recipient (Documents · CAD · BIM · 3D · CNC ·
 * Data). Click triggers design.exportFile() and downloads the blob. */
const EXPORT_FAMILIES: {
  family: string;
  formats: { id: import("@/lib/types").ExportFormat | string; label: string; ext: string }[];
}[] = [
  {
    family: "Documents",
    formats: [
      { id: "pdf",  label: "PDF",         ext: ".pdf" },
      { id: "docx", label: "Word",        ext: ".docx" },
      { id: "xlsx", label: "Excel",       ext: ".xlsx" },
      { id: "pptx", label: "PowerPoint",  ext: ".pptx" },
      { id: "html", label: "HTML Viewer", ext: ".html" },
    ],
  },
  {
    family: "CAD 2D",
    formats: [{ id: "dxf", label: "AutoCAD DXF", ext: ".dxf" }],
  },
  {
    family: "3D Mesh",
    formats: [
      { id: "obj",  label: "OBJ",  ext: ".obj"  },
      { id: "gltf", label: "GLTF", ext: ".gltf" },
      { id: "fbx",  label: "FBX",  ext: ".fbx"  },
    ],
  },
  {
    family: "BIM",
    formats: [{ id: "ifc", label: "IFC4 (Revit-compatible)", ext: ".ifc" }],
  },
  {
    family: "CAD Exchange",
    formats: [
      { id: "step", label: "STEP", ext: ".step" },
      { id: "iges", label: "IGES", ext: ".iges" },
    ],
  },
  {
    family: "CNC",
    formats: [
      { id: "gcode",    label: "G-code",   ext: ".gcode" },
      { id: "cam_prep", label: "CAM Prep", ext: ".zip"   },
    ],
  },
  {
    family: "Data",
    formats: [{ id: "geojson", label: "GeoJSON", ext: ".geojson" }],
  },
];

function ExportModal({
  open,
  onClose,
  projectId,
  latestVersion,
  token,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string | null;
  latestVersion: number | null;
  token: string;
}) {
  const [available, setAvailable] = useState<Set<string> | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const notify = useToastStore((s) => s.notify);

  // Pull the live list of formats the backend actually exposes — if
  // an exporter is broken or behind a flag, we want it dimmed rather
  // than handed to the architect as a dead button.
  useEffect(() => {
    if (!open || !projectId) return;
    designApi
      .listExportFormats(token, projectId)
      .then((res) => setAvailable(new Set(res.formats)))
      .catch(() => setAvailable(null));
  }, [open, projectId, token]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const download = async (format: string, label: string) => {
    if (!projectId) {
      notify({
        type: "warning",
        title: "No project",
        message: "Open or generate a project before exporting.",
      });
      return;
    }
    setDownloading(format);
    try {
      const { blob, filename } = await designApi.exportFile(
        token,
        projectId,
        format as import("@/lib/types").ExportFormat,
        latestVersion ?? undefined,
      );
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      notify({
        type: "success",
        title: `${label} exported`,
        message: filename,
        durationMs: 3000,
      });
    } catch (e) {
      toastError(e, `Could not export ${label}`);
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-ink-deep/40 backdrop-blur-sm flex items-center justify-center p-8"
      onClick={onClose}
    >
      <div
        className="bg-paper rounded-lg shadow-card max-w-2xl w-full max-h-[85vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-3 border-b border-hairline flex items-center justify-between">
          <div>
            <SectionTag>Export</SectionTag>
            <p className="mt-0.5 text-[11.5px] text-ink-mute">
              Pick a format. Files download immediately — no email handoff.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-ink-mute hover:text-ink-deep transition-colors"
            aria-label="Close"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {EXPORT_FAMILIES.map((g) => (
            <section key={g.family}>
              <div className="flex items-baseline justify-between mb-2">
                <SectionTag>{g.family}</SectionTag>
                <span className="font-mono text-[10px] uppercase tracking-tagged text-ink-mute">
                  {g.formats.length} format{g.formats.length === 1 ? "" : "s"}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {g.formats.map((f) => {
                  const isAvailable = !available || available.has(f.id);
                  const isDownloading = downloading === f.id;
                  return (
                    <button
                      key={f.id}
                      type="button"
                      disabled={!isAvailable || isDownloading || !projectId}
                      onClick={() => download(f.id, f.label)}
                      className={`px-3 py-2 text-left border border-hairline rounded-md bg-paper hover:bg-paper-deep/40 hover:border-graphite transition-colors ${
                        !isAvailable || !projectId ? "opacity-40 cursor-not-allowed" : ""
                      }`}
                      title={!isAvailable ? "Not exposed by backend" : f.ext}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[12.5px] font-medium text-ink-deep">
                          {f.label}
                        </span>
                        <span className="font-mono text-[10px] uppercase tracking-tagged text-ink-mute">
                          {isDownloading ? "…" : f.ext}
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
        <div className="px-5 py-2.5 border-t border-hairline bg-paper-soft">
          <p className="font-mono text-[10px] uppercase tracking-tagged text-ink-mute">
            ← /projects/{"{id}"}/export · {EXPORT_FAMILIES.reduce((n, g) => n + g.formats.length, 0)} formats supported
          </p>
        </div>
      </div>
    </div>
  );
}

/* HapticReadyBadge — BRD §Layer 7 "Phase 1 taste". Static visual chip
 * that signals the design is haptic-ready: the Stage 9 catalog + JSON
 * exporter (textures · thermal · friction · firmness · dimension rules
 * · feedback loops) already produce a full payload, and Phase 2 (Aug-
 * Sept 2026) is the hardware integration. No interactive control — the
 * payload is consumed by the agent tool `export_haptic_payload`, not a
 * REST surface, so this chip's job is purely communicative. Hover for
 * the BRD trail explaining what's wired today vs what's hardware. */
function HapticReadyBadge({ hasActiveProject }: { hasActiveProject: boolean }) {
  if (!hasActiveProject) return null;
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-pencil-bg/60 text-pencil text-[11px] font-medium border border-pencil/20"
      title="Haptic-ready data layer shipped (BRD §Layer 7). Hardware integration lands Phase 2 — Aug–Sept 2026."
    >
      <span className="w-1.5 h-1.5 rounded-full bg-pencil" aria-hidden />
      Haptic ready
    </span>
  );
}

/* ExportButton — chip-style trigger that opens the ExportModal. Sits
 * in the canvas header next to ThemeSwitchChip + VersionTimeline. */
function ExportButton({
  onClick,
  disabled,
}: {
  onClick: () => void;
  disabled: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 border border-hairline rounded-md bg-paper hover:border-graphite hover:bg-paper-soft transition-colors text-[12px] font-medium text-ink-deep ${
        disabled ? "opacity-40 cursor-not-allowed" : ""
      }`}
      title={disabled ? "Generate a design first" : "Export to 15 formats"}
    >
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
        <path d="M6 1.5v6.5m0 0L3 5m3 3l3-3M2 10h8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      Export
    </button>
  );
}

/* SpecsTab — BRD §3B/C/D consolidated spec sheet in the right rail.
 *
 * One fetch (design.getSpecs) pulls the entire bundle:
 *   • material      — primary structure + secondary + hardware +
 *                     upholstery + finishing (each a row list)
 *   • manufacturing — free-form dict (woodworking notes, metal fab,
 *                     upholstery assembly, etc — depends on theme)
 *   • mep           — hvac · electrical · plumbing summaries
 *
 * Inside the tab we present three collapsible sub-sections so the
 * architect scans down without scroll-overload. Each subsection
 * stays consistent with the rail's hairline / paper / mono register. */
function SpecsTab({
  hasActiveProject,
  activeProjectId,
  latestVersion,
  token,
}: {
  hasActiveProject: boolean;
  activeProjectId: string | null;
  latestVersion: number | null;
  token: string;
}) {
  const [bundle, setBundle] = useState<
    import("@/lib/types").SpecBundle | null
  >(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<Set<string>>(() => new Set(["material"]));
  const toggle = (id: string) =>
    setOpen((p) => {
      const n = new Set(p);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });

  useEffect(() => {
    if (!hasActiveProject || !activeProjectId) {
      setBundle(null);
      return;
    }
    setLoading(true);
    setErr(null);
    designApi
      .getSpecs(token, activeProjectId, latestVersion ?? undefined)
      .then((res) => setBundle(res.spec_bundle))
      .catch((e) => setErr(e instanceof Error ? e.message : "Could not load specs"))
      .finally(() => setLoading(false));
  }, [hasActiveProject, activeProjectId, latestVersion, token]);

  if (!hasActiveProject) {
    return (
      <div className="space-y-3">
        <SectionTag>Specs</SectionTag>
        <p className="text-[13px] text-ink-soft leading-relaxed">
          Material / Manufacturing / MEP specs — five material categories,
          per-trade manufacturing notes, and HVAC + electrical + plumbing
          targets. Populates after the first generation.
        </p>
        <p className="font-mono text-[10.5px] uppercase tracking-tagged text-ink-mute">
          ← /projects/{"{id}"}/specs · BRD §3B/C/D
        </p>
      </div>
    );
  }
  if (loading) {
    return (
      <div className="space-y-3">
        <SectionTag>Specs</SectionTag>
        <p className="text-[13px] text-ink-soft italic">Loading spec bundle…</p>
      </div>
    );
  }
  if (err) {
    return (
      <div className="space-y-3">
        <SectionTag>Specs</SectionTag>
        <p className="text-[13px] text-brick">{err}</p>
      </div>
    );
  }
  if (!bundle) return null;

  const matGroups: { key: string; label: string; rows: import("@/lib/types").MaterialSpecRow[] }[] = [
    { key: "primary",   label: "Primary structure",   rows: bundle.material.primary_structure   ?? [] },
    { key: "secondary", label: "Secondary materials", rows: bundle.material.secondary_materials ?? [] },
    { key: "hardware",  label: "Hardware",            rows: bundle.material.hardware            ?? [] },
    { key: "uphol",     label: "Upholstery",          rows: bundle.material.upholstery          ?? [] },
    { key: "finish",    label: "Finishing",           rows: bundle.material.finishing           ?? [] },
  ];
  const matTotal = matGroups.reduce((n, g) => n + g.rows.length, 0);

  return (
    <div className="space-y-4">
      {/* Meta strip — one-line context for the bundle */}
      <div className="text-[11.5px] text-ink-mute">
        <span className="font-mono">v{bundle.objects_count ?? 0} objects</span>
        <span className="mx-1.5">·</span>
        <span>{bundle.meta?.theme ?? "—"}</span>
        <span className="mx-1.5">·</span>
        <span>{bundle.meta?.room_type ?? "—"}</span>
      </div>

      <SpecSubsection
        title="Material"
        badge={`${matTotal} row${matTotal === 1 ? "" : "s"}`}
        open={open.has("material")}
        onToggle={() => toggle("material")}
      >
        {matTotal === 0 ? (
          <p className="text-[11.5px] text-ink-mute italic">No material rows on this version.</p>
        ) : (
          matGroups.map((g) =>
            g.rows.length === 0 ? null : (
              <MaterialGroup key={g.key} label={g.label} rows={g.rows} />
            ),
          )
        )}
      </SpecSubsection>

      <SpecSubsection
        title="Manufacturing"
        badge={`${Object.keys(bundle.manufacturing ?? {}).length} trade${Object.keys(bundle.manufacturing ?? {}).length === 1 ? "" : "s"}`}
        open={open.has("manufacturing")}
        onToggle={() => toggle("manufacturing")}
      >
        <DictDump dict={bundle.manufacturing} />
      </SpecSubsection>

      <SpecSubsection
        title="MEP"
        badge="3 systems"
        open={open.has("mep")}
        onToggle={() => toggle("mep")}
      >
        <div className="space-y-3">
          {(["hvac", "electrical", "plumbing"] as const).map((sys) => (
            <div key={sys}>
              <h5 className="font-mono text-[10px] uppercase tracking-tagged text-ink-mute mb-1">
                {sys}
              </h5>
              <DictDump dict={bundle.mep?.[sys] as Record<string, unknown> | undefined} />
            </div>
          ))}
        </div>
      </SpecSubsection>
    </div>
  );
}

function SpecSubsection({
  title, badge, open, onToggle, children,
}: {
  title: string;
  badge?: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className="border border-hairline rounded-md overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        className="w-full px-3 py-2 flex items-center justify-between gap-2 hover:bg-paper transition-colors"
      >
        <span className="font-mono text-[10.5px] uppercase tracking-tagged text-ink-deep">
          {title}
        </span>
        <span className="flex items-center gap-2">
          {badge ? (
            <span className="font-mono text-[10px] text-ink-mute">{badge}</span>
          ) : null}
          <svg width="9" height="9" viewBox="0 0 9 9"
            className={`text-ink-mute transition-transform ${open ? "rotate-90" : ""}`}
            aria-hidden="true"
          >
            <path d="M3 1.5l3 3-3 3" stroke="currentColor" strokeWidth="1.3"
              strokeLinecap="round" fill="none" />
          </svg>
        </span>
      </button>
      {open ? (
        <div className="px-3 pb-3 pt-1 bg-paper">{children}</div>
      ) : null}
    </section>
  );
}

function MaterialGroup({
  label, rows,
}: {
  label: string;
  rows: import("@/lib/types").MaterialSpecRow[];
}) {
  const fmtRange = (r: [number, number] | null, suffix = "") =>
    !r ? "—" : `${Math.round(r[0]).toLocaleString("en-IN")}–${Math.round(r[1]).toLocaleString("en-IN")}${suffix}`;
  return (
    <div className="mb-3 last:mb-0">
      <h5 className="font-mono text-[10px] uppercase tracking-tagged text-ink-mute mb-1.5">
        {label}
      </h5>
      <div className="border-t border-hairline">
        {rows.map((r, i) => (
          <div key={`${r.name}-${i}`} className="py-2 border-b border-hairline last:border-b-0">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[12.5px] text-ink-deep font-medium">{r.name}</span>
              {r.cost_inr ? (
                <span className="font-mono text-[11px] text-pencil tnum shrink-0">
                  ₹{fmtRange(r.cost_inr)}/{r.unit || "u"}
                </span>
              ) : null}
            </div>
            <div className="mt-0.5 text-[11px] text-ink-soft leading-snug">
              {[r.grade, r.finish, r.color].filter(Boolean).join(" · ") || <span className="italic">—</span>}
            </div>
            <div className="mt-0.5 flex items-baseline justify-between gap-2 font-mono text-[10px] text-ink-mute">
              <span>{r.supplier || "—"}</span>
              {r.lead_time_weeks ? (
                <span className="tnum">{fmtRange(r.lead_time_weeks)} wk</span>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* DictDump — renders a Record<string, unknown> as flat key/value rows.
 * Nested objects collapse to JSON for now — manufacturing + MEP dicts
 * are usually flat scalars from the backend, so this looks clean. */
function DictDump({ dict }: { dict?: Record<string, unknown> }) {
  const entries = Object.entries(dict ?? {});
  if (entries.length === 0) {
    return <p className="text-[11.5px] text-ink-mute italic">No data on this version.</p>;
  }
  return (
    <div className="border-t border-hairline">
      {entries.map(([k, v]) => (
        <div key={k} className="py-1.5 border-b border-hairline last:border-b-0 flex items-baseline justify-between gap-2">
          <span className="font-mono text-[10.5px] uppercase tracking-tagged text-ink-mute">
            {k.replace(/_/g, " ")}
          </span>
          <span className="text-[11.5px] text-ink text-right font-mono break-all max-w-[60%]">
            {typeof v === "string" || typeof v === "number" || typeof v === "boolean"
              ? String(v)
              : JSON.stringify(v)}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ChecksTab — BRD §1B + §11.3 unified Checks panel. Combines the
 * validation report headline (ok/fail + summary, errors + warnings +
 * suggestions counts with per-issue rows) on top of the existing
 * CodeComplianceBlock. One scrollable column — architects scan the
 * top band for blockers, then drop into compliance citations below. */
function ChecksTab({
  validation,
  codeCompliance,
}: {
  validation?: import("@/lib/types").ValidationReport;
  codeCompliance?: import("@/lib/types").CodeComplianceEntry[];
}) {
  return (
    <div className="space-y-5">
      <ValidationSummary report={validation} />
      <CodeComplianceBlock entries={codeCompliance} />
    </div>
  );
}

function ValidationSummary({
  report,
}: {
  report?: import("@/lib/types").ValidationReport;
}) {
  if (!report) {
    return (
      <div>
        <SectionTag>Validator</SectionTag>
        <p className="mt-2 text-[11.5px] text-ink-mute italic">
          Validation report populates after the first generation.
        </p>
      </div>
    );
  }
  const counts = {
    errors:      report.errors?.length ?? 0,
    warnings:    report.warnings?.length ?? 0,
    suggestions: report.suggestions?.length ?? 0,
  };
  const ok = report.ok;
  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <SectionTag>Validator</SectionTag>
        <span className="font-mono text-[10px] tnum">
          {counts.errors > 0 && (
            <span className="text-rose-700">{counts.errors} error</span>
          )}
          {counts.errors > 0 && counts.warnings > 0 && (
            <span className="text-ink-mute"> · </span>
          )}
          {counts.warnings > 0 && (
            <span className="text-amber-700">{counts.warnings} warn</span>
          )}
          {counts.errors + counts.warnings === 0 && (
            <span className={ok ? "text-emerald-700" : "text-ink-mute"}>
              {ok ? "ok" : "—"}
            </span>
          )}
        </span>
      </div>
      <p className="text-[12px] text-ink-soft leading-snug">
        {report.summary}
      </p>
      {/* Issue list — errors first, then warnings, then suggestions —
          each row is the rule code + message. Bottom-terminal Problems
          tab carries the full breakdown; this is the in-rail digest. */}
      {(counts.errors + counts.warnings + counts.suggestions) > 0 && (
        <div className="mt-3 border-t border-hairline">
          {report.errors?.map((e, i) => (
            <IssueRow key={`e-${i}`} kind="error" issue={e} />
          ))}
          {report.warnings?.map((w, i) => (
            <IssueRow key={`w-${i}`} kind="warn" issue={w} />
          ))}
          {report.suggestions?.slice(0, 3).map((s, i) => (
            <IssueRow key={`s-${i}`} kind="suggest" issue={s} />
          ))}
        </div>
      )}
    </div>
  );
}

function IssueRow({
  kind,
  issue,
}: {
  kind: "error" | "warn" | "suggest";
  issue: import("@/lib/types").ValidationIssue;
}) {
  const dot = {
    error:   "bg-rose-600",
    warn:    "bg-amber-500",
    suggest: "bg-ink-mute",
  }[kind];
  // Best-effort label extraction — ValidationIssue carries a code +
  // message + path; we prefer code, fall back to path, then message.
  const issueObj = issue as unknown as {
    code?: string;
    path?: string;
    message?: string;
  };
  const code = issueObj.code ?? issueObj.path ?? "rule";
  return (
    <div className="py-2 border-b border-hairline last:border-b-0">
      <div className="flex items-start gap-2">
        <span className={`shrink-0 mt-1.5 w-1.5 h-1.5 rounded-full ${dot}`} aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[10.5px] uppercase tracking-tagged text-ink-mute">
            {code}
          </div>
          {issueObj.message && (
            <p className="mt-0.5 text-[11.5px] text-ink-soft leading-snug">
              {issueObj.message}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

/* RecsTab — BRD §6 two-speed recommendations advisor in the right rail.
 *
 * Calls design.validate() once per project version when the tab is
 * opened (cheap on backend — Python recommendations engine is ~1ms).
 * Renders the returned recommendations grouped by severity so the
 * architect scans nudges first, then tips, then info-level. Each item
 * shows its category as a mono tag and the message body.
 *
 * The LLM-driven full advisor (BRD §6 second speed) is reachable via
 * "Run full review" — placeholder for now since the route round-trip
 * is 3-8s and needs its own progress affordance (lands in polish day). */
function RecsTab({
  hasActiveProject,
  activeProjectId,
  latestVersion,
  token,
}: {
  hasActiveProject: boolean;
  activeProjectId: string | null;
  latestVersion: number | null;
  token: string;
}) {
  const [recs, setRecs] = useState<
    import("@/lib/types").RecommendationItem[] | null
  >(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Fetch once when the tab mounts and a project is loaded. Re-fires
  // when the project / version changes (so v01 → v02 pulls fresh recs).
  useEffect(() => {
    if (!hasActiveProject || !activeProjectId) {
      setRecs(null);
      return;
    }
    setLoading(true);
    setErr(null);
    designApi
      .validate(token, activeProjectId, latestVersion ?? undefined)
      .then((res) => setRecs(res.recommendations ?? []))
      .catch((e) => setErr(e instanceof Error ? e.message : "Could not load recommendations"))
      .finally(() => setLoading(false));
  }, [hasActiveProject, activeProjectId, latestVersion, token]);

  if (!hasActiveProject) {
    return (
      <div className="space-y-3">
        <SectionTag>Recommendations</SectionTag>
        <p className="text-[13px] text-ink-soft leading-relaxed">
          Two-speed advisor — quick deterministic checks (~1 ms) on every
          generation, plus a full LLM review with confidence + impact + effort
          labels. Populates once a project exists.
        </p>
        <p className="font-mono text-[10.5px] uppercase tracking-tagged text-ink-mute">
          ← /projects/{"{id}"}/validate · BRD §6
        </p>
      </div>
    );
  }
  if (loading) {
    return (
      <div className="space-y-3">
        <SectionTag>Recommendations</SectionTag>
        <p className="text-[13px] text-ink-soft italic">Running checks…</p>
      </div>
    );
  }
  if (err) {
    return (
      <div className="space-y-3">
        <SectionTag>Recommendations</SectionTag>
        <p className="text-[13px] text-brick">{err}</p>
      </div>
    );
  }
  const items = recs ?? [];
  // Severity rank so nudges (most urgent) show first, then tips, then info.
  const rank: Record<string, number> = { nudge: 0, tip: 1, info: 2 };
  const sorted = [...items].sort(
    (a, b) => (rank[a.severity] ?? 9) - (rank[b.severity] ?? 9),
  );
  const counts = {
    nudge: items.filter((i) => i.severity === "nudge").length,
    tip:   items.filter((i) => i.severity === "tip").length,
    info:  items.filter((i) => i.severity === "info").length,
  };

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <SectionTag>Recommendations</SectionTag>
        <span className="font-mono text-[10.5px] text-ink-mute tnum">
          {items.length === 0 ? "all clear" : (
            <>
              {counts.nudge > 0 && <span className="text-pencil">{counts.nudge} nudge</span>}
              {counts.nudge > 0 && (counts.tip + counts.info) > 0 && " · "}
              {counts.tip > 0 && <span className="text-mustard">{counts.tip} tip</span>}
              {counts.tip > 0 && counts.info > 0 && " · "}
              {counts.info > 0 && <span className="text-ink-mute">{counts.info} info</span>}
            </>
          )}
        </span>
      </div>

      {sorted.length === 0 ? (
        <p className="text-[12.5px] text-ink-soft italic">
          No recommendations on this version. The deterministic engine
          had nothing to flag — design looks solid.
        </p>
      ) : (
        <div className="border-t border-hairline">
          {sorted.map((item) => (
            <RecRow key={item.id} item={item} />
          ))}
        </div>
      )}

      <div className="pt-2 border-t border-hairline">
        <button
          type="button"
          disabled
          className="w-full text-left px-3 py-2 border border-hairline border-dashed rounded-md text-[12.5px] text-ink-mute opacity-70 cursor-not-allowed"
          title="LLM advisor lands in Day 5 polish"
        >
          Run full LLM review
          <span className="ml-2 font-mono text-[10px] uppercase tracking-tagged text-pencil">
            Day 5
          </span>
        </button>
      </div>
    </div>
  );
}

function RecRow({ item }: { item: import("@/lib/types").RecommendationItem }) {
  const dot = {
    nudge: "bg-pencil",
    tip:   "bg-mustard",
    info:  "bg-ink-mute",
  }[item.severity];
  return (
    <div className="py-2.5 border-b border-hairline last:border-b-0">
      <div className="flex items-start gap-2">
        <span className={`shrink-0 mt-1.5 w-1.5 h-1.5 rounded-full ${dot}`} aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[12.5px] text-ink-deep font-medium">
              {item.title}
            </span>
            <span className="font-mono text-[10px] uppercase tracking-tagged text-ink-mute shrink-0">
              {item.category}
            </span>
          </div>
          {item.message && (
            <p className="mt-0.5 text-[11.5px] text-ink-soft leading-snug">
              {item.message}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

/* TabPlaceholder — used for the Specs tab that ships later in the
   sprint. States what's coming and which BRD section / backend route
   it lights up. */
function TabPlaceholder({ tab }: { tab: RightTab }) {
  const meta: Record<RightTab, { title: string; body: string; day: string; backend: string }> = {
    summary: { title: "", body: "", day: "", backend: "" },
    compliance: { title: "", body: "", day: "", backend: "" },
    views: {
      title: "Views",
      body: "Switcher for 5 working drawings (plan · elevation · section · isometric · detail) and 8 BRD diagrams (concept · form · massing · volumetric · process · solid-vs-void · spatial organism · hierarchy). Click a thumbnail → it swaps into the canvas.",
      day: "Day 2",
      backend: "/drawings/* · /diagrams/*",
    },
    specs: {
      title: "Specs",
      body: "Material · Manufacturing · MEP spec sheets, with supplier, lead time, cost per unit, tolerances. Lands post-sprint — needs its own three-column layout the current rail width can't hold.",
      day: "Post-sprint",
      backend: "/specs/* (material · manufacturing · mep)",
    },
    cost: {
      title: "Cost",
      body: "Shipped Day 3.",
      day: "Day 3",
      backend: "/estimates/*",
    },
    recs: {
      title: "Recommendations",
      body: "Shipped Day 4.",
      day: "Day 4",
      backend: "/projects/{id}/validate",
    },
  };
  const m = meta[tab];
  return (
    <div className="space-y-3">
      <SectionTag>{m.title}</SectionTag>
      <p className="text-[13px] text-ink-soft leading-relaxed">{m.body}</p>
      <div className="pt-2 flex flex-col gap-1.5">
        <span className="font-mono text-[10.5px] uppercase tracking-tagged text-pencil">
          Coming {m.day}
        </span>
        <span className="font-mono text-[11px] text-ink-mute">
          ← {m.backend}
        </span>
      </div>
    </div>
  );
}

/* SummaryTab — current RightSummary body, lifted into its own component
   so the parent tab shell stays small. The "no design yet" placeholder
   and the populated meta/materials/objects path both render here. */
function SummaryTab({
  hasDesign,
  hasGraph,
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
  hasGraph: boolean;
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
  return (
    <>
      <SectionTag>Specification summary</SectionTag>
      {!hasDesign ? (
        <p className="mt-3 text-[13px] text-ink-soft leading-relaxed">
          Specs, materials, and BOQ will appear here once you generate a
          design. Every value carries its source inline.
        </p>
      ) : hasGraph ? (
        // Project-pipeline path — graph_data present, objects are
        // editable. Clicking a row opens an inline edit popover.
        // CodeCompliance is intentionally NOT rendered here — it lives
        // in the dedicated Checks tab in the new tabbed shell.
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
        // Anonymous / image-only fallback — no graph_data was returned.
        // Static spec surfaces so the page stays informative. Code
        // compliance has moved out to the Checks tab.
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
        </div>
      )}
    </>
  );
}

/* ObjectsPanel — Pass 2 of the edit loop.
   Shows every object the AI named in the design graph as a clickable
   row. Selecting a row opens an inline edit popover directly beneath
   it; submit fires /projects/{id}/edit and the gallery grows by one
   version. Architects iterate the design without re-prompting from
   scratch. */
/* BRD §1B — Code Compliance block in the right sidebar.
   Entries arrive pre-built from the generation pipeline; each row
   carries its severity (fail / warn / info) plus the DB source it
   was resolved from. We sort fail → warn → info so the architect
   sees blockers first. When the pipeline hasn't produced any entries
   yet (legacy generation, validator hiccup), show a thin idle line
   instead of the long-since-deleted hardcoded mock rows. */
function CodeComplianceBlock({
  entries,
}: {
  entries?: import("@/lib/types").CodeComplianceEntry[];
}) {
  const items = entries ?? [];
  // Fail first, warn second, info last — preserves order inside each.
  const orderRank: Record<string, number> = { fail: 0, warn: 1, info: 2 };
  const sorted = items
    .map((e, i) => ({ e, i }))
    .sort((a, b) => {
      const rA = orderRank[a.e.status] ?? 9;
      const rB = orderRank[b.e.status] ?? 9;
      return rA !== rB ? rA - rB : a.i - b.i;
    })
    .map((x) => x.e);

  const failCount = items.filter((e) => e.status === "fail").length;
  const warnCount = items.filter((e) => e.status === "warn").length;

  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <h4 className="font-mono text-[10px] tracking-[0.14em] uppercase text-ink-mute">
          Code compliance
        </h4>
        {items.length > 0 && (
          <span className="font-mono text-[10px] text-ink-mute tnum">
            {failCount > 0 && (
              <span className="text-rose-700">{failCount} fail</span>
            )}
            {failCount > 0 && warnCount > 0 && (
              <span className="text-ink-mute"> · </span>
            )}
            {warnCount > 0 && (
              <span className="text-amber-700">{warnCount} warn</span>
            )}
            {failCount === 0 && warnCount === 0 && (
              <span className="text-emerald-700">all clear</span>
            )}
          </span>
        )}
      </div>
      <div className="border-t border-hairline">
        {sorted.length === 0 ? (
          <p className="py-3 text-[11px] text-ink-mute italic">
            Code compliance will populate after the first generation.
          </p>
        ) : (
          sorted.map((entry, i) => (
            <ComplianceRow key={`${entry.code}-${i}`} entry={entry} />
          ))
        )}
      </div>
    </div>
  );
}

function ComplianceRow({
  entry,
}: {
  entry: import("@/lib/types").CodeComplianceEntry;
}) {
  const statusDot = {
    fail: "bg-rose-600",
    warn: "bg-amber-500",
    info: "bg-emerald-500",
  }[entry.status];

  // The source citation lives on its own line below the value — same
  // shape as the existing CitedKV but with a severity dot prepended.
  return (
    <div className="py-2 border-b border-hairline last:border-b-0">
      <div className="flex items-start gap-2">
        <span
          className={`shrink-0 mt-1.5 w-1.5 h-1.5 rounded-full ${statusDot}`}
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[12px] text-ink-deep font-medium">
              {entry.label}
            </span>
            {entry.status !== "info" && (
              <span className="font-mono text-[9px] uppercase tracking-wider text-ink-mute">
                {entry.status}
              </span>
            )}
          </div>
          <p className="text-[11px] text-ink-soft leading-snug mt-0.5">
            {entry.value}
          </p>
          {entry.source_section && (
            <p className="text-[10px] text-ink-mute mt-0.5">
              cite: <span className="text-pencil">{entry.source_section}</span>
              {entry.jurisdiction && (
                <span className="text-ink-mute"> ({entry.jurisdiction})</span>
              )}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}


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

function TerminalPanel({
  tab,
  setTab,
  hasDesign,
  validation,
  mepCost,
  onClose,
}: {
  tab: TerminalTab;
  setTab: (t: TerminalTab) => void;
  hasDesign: boolean;
  validation?: import("@/lib/types").ValidationReport;
  mepCost?: import("@/lib/types").MepCostEstimate;
  onClose: () => void;
}) {
  // BRD §11.3 — Problems tab count reflects errors + warnings (suggestions
  // are advisory only and don't drive the badge). 0 when there's no design
  // yet or when the validator hasn't run.
  const problemCount =
    (validation?.errors?.length ?? 0) + (validation?.warnings?.length ?? 0);

  const tabs: { id: TerminalTab; label: string; count?: number }[] = [
    { id: "cost", label: "Cost" },
    { id: "problems", label: "Problems", count: problemCount },
  ];

  return (
    <div className="border-t border-hairline bg-ink-deep h-72 flex flex-col">
      <div className="border-b border-white/10 pl-2 pr-1 flex items-center justify-between">
        <div className="flex items-center">
          {tabs.map((t) => {
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
          <CostStream hasDesign={hasDesign} mepCost={mepCost} />
        ) : (
          <ProblemsList hasDesign={hasDesign} validation={validation} />
        )}
      </div>
    </div>
  );
}

function CostStream({
  hasDesign,
  mepCost,
}: {
  hasDesign: boolean;
  mepCost?: import("@/lib/types").MepCostEstimate;
}) {
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

      {/* BRD §1B — MEP systems cost block. DB-backed; rolls up HVAC,
          electrical, plumbing, fire-fighting at ₹/m² bands for the
          generated room area. Hidden until the validator emits one
          (no usable room area → no block). */}
      {mepCost ? <MepCostBlock mepCost={mepCost} /> : null}
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

function MepCostBlock({
  mepCost,
}: {
  mepCost: import("@/lib/types").MepCostEstimate;
}) {
  // Compact INR formatter — uses lakhs/crores at >=1e5 / >=1e7 so the
  // numbers don't dominate the row width on big commercial projects.
  const fmt = (n: number | undefined): string => {
    if (n == null || Number.isNaN(n)) return "—";
    if (n >= 1e7) return `₹ ${(n / 1e7).toFixed(2)} Cr`;
    if (n >= 1e5) return `₹ ${(n / 1e5).toFixed(2)} L`;
    return `₹ ${Math.round(n).toLocaleString("en-IN")}`;
  };

  const SYSTEM_LABEL: Record<string, string> = {
    hvac: "HVAC",
    electrical: "Electrical",
    plumbing: "Plumbing",
    fire_fighting: "Fire-fighting",
  };

  const totalLow = mepCost.total_inr.low;
  const totalHigh = mepCost.total_inr.high;

  return (
    <div className="border-t border-white/10 pt-3">
      <div className="flex items-baseline justify-between mb-2">
        <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-white/45">
          MEP systems · per ₹/m² band
        </div>
        <div className="font-mono text-[10px] tracking-tight text-white/55">
          area {mepCost.area_m2.toFixed(1)} m² · {mepCost.jurisdiction}
        </div>
      </div>

      <div className="space-y-1 font-mono text-[12px] text-white/85">
        {mepCost.systems.map((s) => {
          const lo = s.rate_inr_m2.low;
          const hi = s.rate_inr_m2.high;
          const tlow = s.total_inr.low;
          const thigh = s.total_inr.high;
          const label = SYSTEM_LABEL[s.system] ?? s.system;
          return (
            <CostLine
              key={s.key}
              k={`${label} · ${s.key}`}
              v={`${fmt(tlow)}–${fmt(thigh)}`}
              src={`Rate ₹${lo ?? "?"}–${hi ?? "?"}/m² · DB`}
              srcWhen={mepCost.jurisdiction}
            />
          );
        })}
      </div>

      <div className="border-t border-white/10 mt-2 pt-2 flex items-baseline justify-between">
        <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-white/55">
          MEP total
        </div>
        <div className="font-mono text-[13px] text-paper tnum">
          {fmt(totalLow)} <span className="text-white/45 px-1">–</span>{" "}
          {fmt(totalHigh)}
        </div>
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

function ProblemsList({
  hasDesign,
  validation,
}: {
  hasDesign: boolean;
  validation?: import("@/lib/types").ValidationReport;
}) {
  // No design yet — explain what will populate here.
  if (!hasDesign) {
    return (
      <div className="font-mono text-[12px] text-white/65 space-y-1.5">
        <div className="text-white/45">No problems detected.</div>
        <div className="text-white/45">
          Validation warnings, hard errors, and suggestions will appear here
          once you generate a design. Every entry cites its source.
        </div>
      </div>
    );
  }

  // Design exists but no validation block — likely a legacy generation
  // saved before the validator was wired in. Treat as silent OK.
  if (!validation) {
    return (
      <div className="font-mono text-[12px] text-white/65 space-y-1.5">
        <div className="pl-3 border-l-2 border-olive">
          <span className="text-olive">[OK]</span>
          <span className="ml-2 text-white/85">
            no validation report attached to this version
          </span>
        </div>
      </div>
    );
  }

  const errors = validation.errors ?? [];
  const warnings = validation.warnings ?? [];
  const suggestions = validation.suggestions ?? [];
  const total = errors.length + warnings.length + suggestions.length;

  if (total === 0) {
    return (
      <div className="font-mono text-[12px] text-white/65 space-y-1.5">
        <div className="pl-3 border-l-2 border-olive">
          <span className="text-olive">[OK]</span>
          <span className="ml-2 text-white/85">{validation.summary}</span>
        </div>
        <div className="text-white/45 pl-3">
          All rooms, ergonomics, and clearances within standard.
        </div>
      </div>
    );
  }

  return (
    <div className="font-mono text-[12px] text-white/85 space-y-3">
      <div className="text-white/55">{validation.summary}</div>

      {errors.length > 0 && (
        <IssueSection
          label="Errors"
          color="rose"
          tag="[ERR]"
          items={errors}
        />
      )}
      {warnings.length > 0 && (
        <IssueSection
          label="Warnings"
          color="amber"
          tag="[WARN]"
          items={warnings}
        />
      )}
      {suggestions.length > 0 && (
        <IssueSection
          label="Suggestions"
          color="sky"
          tag="[NOTE]"
          items={suggestions}
        />
      )}
    </div>
  );
}

/* One severity group inside the Problems tab. Each entry shows:
   [TAG] code · message · path
        cite: source_section (jurisdiction)            ← when DB-backed
   The tag colour ties into the BRD severity palette
   (red error / amber warning / blue suggestion). */
function IssueSection({
  label,
  color,
  tag,
  items,
}: {
  label: string;
  color: "rose" | "amber" | "sky";
  tag: string;
  items: import("@/lib/types").ValidationIssue[];
}) {
  const colorClasses = {
    rose: { border: "border-rose-400", tag: "text-rose-300" },
    amber: { border: "border-amber-400", tag: "text-amber-300" },
    sky: { border: "border-sky-400", tag: "text-sky-300" },
  }[color];

  return (
    <div>
      <div className="text-white/55 uppercase tracking-wider text-[10px] mb-1">
        {label} · {items.length}
      </div>
      <div className="space-y-1.5">
        {items.map((issue, i) => (
          <div
            key={`${issue.code}-${issue.path}-${i}`}
            className={`pl-3 border-l-2 ${colorClasses.border} leading-snug`}
          >
            <div>
              <span className={colorClasses.tag}>{tag}</span>{" "}
              <span className="text-white/55">{issue.code}</span>{" "}
              <span className="text-white/85">{issue.message}</span>
            </div>
            <div className="text-white/40 text-[10.5px] pl-1">
              {issue.path}
              {issue.source_section && (
                <span>
                  {" · cite: "}
                  <span className="text-pencil">{issue.source_section}</span>
                  {issue.jurisdiction && (
                    <span className="text-white/35"> ({issue.jurisdiction})</span>
                  )}
                </span>
              )}
            </div>
          </div>
        ))}
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
