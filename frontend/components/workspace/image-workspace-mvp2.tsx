"use client";

/* MVP 2 — Design generation workspace.
 * Engineering-workstation 4-zone layout: left controls, centered canvas,
 * right specs, bottom terminal. Avenir on chrome, JetBrains Mono on
 * technical surfaces (cost stream, generation log, citations, dimensions).
 * No serif. Gridpaper appears only on the canvas surface, never on chrome.
 * Pencil-red is the single accent (active terminal tab, live links). */

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
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
  CameraMode,
  ImageRatio,
  LightingMode,
  ProjectType,
} from "@/lib/types";
import {
  Annotation,
  PaperCard,
  SectionTag,
} from "@/components/primitives";
import BackendHealthBanner from "@/components/primitives/backend-health-banner";
import { ImportDialog } from "@/components/workspace/import-dialog";
import { ModelImportDialog } from "@/components/workspace/model-import-dialog";
import { FloorplanImportDialog } from "@/components/workspace/floorplan-import-dialog";
import {
  ProjectPicker,
  type OpenedProject,
} from "@/components/workspace/project-picker";

// Live 3D viewport is client-only (R3F Canvas) — load without SSR.
const DesignViewport3D = dynamic(
  () => import("@/components/workspace/design-viewport-3d"),
  { ssr: false },
);
// Editable 2D plan (SVG) — client-only for pointer/CTM math.
const DesignPlanEditor = dynamic(
  () => import("@/components/workspace/design-plan-editor"),
  { ssr: false },
);

type Scope = "architecture" | "interior" | "furniture" | "product";
type Dim = "2d" | "3d" | "4d";
type TerminalTab = "cost" | "problems" | "genlog" | "citations";

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
const CAMERAS: { id: CameraMode; label: string }[] = [
  { id: "front", label: "Front" },
  { id: "eye-level", label: "Eye-level" },
  { id: "interior", label: "Interior" },
  { id: "aerial", label: "Aerial" },
];
const LIGHTINGS: { id: LightingMode; label: string }[] = [
  { id: "daylight", label: "Daylight" },
  { id: "golden-hour", label: "Golden hour" },
  { id: "night", label: "Night" },
  { id: "overcast", label: "Overcast" },
];

/* BRD §3A working-drawing catalogue. Mirrors the backend
 * /working-drawings/types response so the UI can render the picker
 * without an extra fetch on mount. If the backend gains a new
 * drawing type, sync this list (or upgrade ViewsTab to fetch /types
 * on mount). */
const DRAWINGS_CATALOGUE: {
  id: string;
  name: string;
  summary: string;
  /** True when the project-scoped fetch path is wired in api-client. */
  wired: boolean;
}[] = [
  { id: "plan_view",       name: "Plan View",       summary: "Top-down — every room, walls, furniture, doors, and overall dimensions.",           wired: true },
  { id: "elevation_view",  name: "Elevation View",  summary: "Exterior face — building silhouette, room heights, window & door openings.",       wired: true },
  { id: "section_view",    name: "Section View",    summary: "Vertical cut — rooms in section, floor/ceiling, poché walls, furniture at the cut.", wired: true },
  { id: "isometric_view",  name: "Isometric View",  summary: "3D axonometric — every room massed with its furniture placed inside it.",          wired: true },
  { id: "detail_sheet",    name: "Detail Sheet",    summary: "Construction junctions — wall/floor, wall/ceiling, jamb, threshold for the main room.", wired: true },
];

/* BRD §2B diagram catalogue. Each id MUST match a generator in the
 * backend deterministic registry (app/services/diagrams/__init__.py),
 * which is what /projects/:id/diagrams (design.generateDiagrams) serves.
 * These renderers are deterministic SVG — no LLM key required. Keep this
 * list in sync with design.listDiagramsAvailable() / the registry. */
const DIAGRAMS_CATALOGUE: {
  id: string;
  name: string;
  summary: string;
}[] = [
  { id: "concept_transparency", name: "Concept Transparency", summary: "Core design intent — material/form relationship, functional zones." },
  { id: "form_development",     name: "Form Development",     summary: "Four-stage evolution — volume → grid → subtract → articulate." },
  { id: "massing",              name: "Massing",              summary: "Horizontal + vertical massing — silhouette, weight, height bands." },
  { id: "volumetric",           name: "Volumetric",           summary: "Axonometric 3D block read — masses, voids, spatial volume." },
  { id: "design_process",       name: "Design Process",       summary: "Step-by-step narrative — decision points, rule drivers." },
  { id: "solid_void",           name: "Solid vs Void",        summary: "Solid % / void % — weight pattern, breathing room." },
  { id: "spatial_organism",     name: "Spatial Organism",     summary: "How a body inhabits the space — touchpoints, movement." },
  { id: "hierarchy",            name: "Hierarchy",            summary: "Three rankings — visual, material, functional." },
];

export default function ImageWorkspaceMvp2() {
  const {
    prompt,
    setPrompt,
    projectType,
    setProjectType,
    region,
    theme,
    setTheme,
    ratio,
    setRatio,
    camera,
    setCamera,
    lighting,
    setLighting,
    viewMode,
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
  // Coerce null → undefined at the source: every API call and child prop here
  // expects ``string | undefined`` (no auth ⇒ no Authorization header), and the
  // store models "signed out" as null. One coercion keeps all call sites typed.
  const token = useAuthStore((s) => s.token) ?? undefined;

  const [scope, setScope] = useState<Scope>("interior");
  const [dim, setDim] = useState<Dim>("3d");
  // Left-rail brief (Space & Site / Requirements / Regulatory) lives here so
  // Generate can fold it into the prompt; LeftControls edits it + Save brief
  // still packages it to /brief/intake.
  const [briefSpace, setBriefSpace] = useState<BriefSpace>(emptySpace);
  const [briefRequirements, setBriefRequirements] = useState<BriefRequirements>(emptyRequirements);
  const [briefRegulatory, setBriefRegulatory] = useState<BriefRegulatory>(emptyRegulatory);
  const [terminalTab, setTerminalTab] = useState<TerminalTab>("cost");
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [generateNotice, setGenerateNotice] = useState<string | null>(null);

  // ── Canvas focus — which generation the hero shows ──────────────────
  // The canvas is a focused-hero + history filmstrip (not a tall feed):
  // one render large, the rest a glance away in the strip. Focus is a
  // *view* concern — the right rail + edit/theme/export still target the
  // latest (working) version, since the backend /edit always operates on
  // get_latest_version. Focusing an older render is for visual compare.
  const [focusedGenId, setFocusedGenId] = useState<string | null>(null);

  // ── Pass 2: edit-loop UX state ──────────────────────────────────────
  // Which object the architect has selected for editing, plus the
  // prompt they're typing and whether a submit is in flight. Cleared
  // after a successful edit so the popover collapses on its own.
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null);
  // A version whose spec landed (fast edit) but whose photoreal still needs a
  // refresh. The effect below fires the rerender once it becomes the latest.
  const [staleRenderVersion, setStaleRenderVersion] = useState<number | null>(null);
  const [editPrompt, setEditPrompt] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // ── Pass 3: theme-switch state ──────────────────────────────────────
  // A single in-flight flag is enough — the chip itself owns its
  // open/closed state. Errors surface as a transient notice strip.
  const [isSwitchingTheme, setIsSwitchingTheme] = useState(false);
  const [isRerendering, setIsRerendering] = useState(false);
  const [isPresenting, setIsPresenting] = useState(false);
  const [themeSwitchError, setThemeSwitchError] = useState<string | null>(null);

  // ── BRD 5B: import dialog open/close ────────────────────────────────
  // The dialog owns its file-queue + parse state internally; the
  // workspace just toggles visibility and receives the parsed brief
  // text on apply, which gets appended to the prompt textarea.
  const [importOpen, setImportOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [floorplanOpen, setFloorplanOpen] = useState(false);

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

  // When a new generation lands (or the gallery is replaced/cleared),
  // snap the hero to the newest result. Clicking a filmstrip thumb sets
  // focusedGenId directly and persists until the next generation, since
  // those clicks don't change the `generations` reference.
  useEffect(() => {
    setFocusedGenId(generations[0]?.id ?? null);
  }, [generations]);

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

  /* submitRerender — regenerate the photoreal 2D render from the current
   * (directly-edited) spec. Drag edits in Plan / 3D mutate the spec in place
   * and the 3D model re-derives instantly, but the photoreal image goes stale;
   * this refreshes it + the exact hotspots on the same version. */
  const submitRerender = async (): Promise<boolean> => {
    if (!activeProjectId || !latestGeneration || isRerendering) return false;
    setIsRerendering(true);
    try {
      const res = await designApi.rerender(token, activeProjectId);
      if (res.image_url) {
        replaceGenerations(
          generations.map((g) =>
            g.id === latestGeneration.id
              ? { ...g, url: res.image_url ?? g.url, objectsBbox: res.objects_bbox ?? g.objectsBbox }
              : g,
          ),
        );
      }
      return true;
    } catch (e) {
      toastError(e, "Re-render failed");
      return false;
    } finally {
      setIsRerendering(false);
    }
  };

  /* submitPresent — PRESENTATION (hero) render: an atmospheric, styled
   * architectural photo of the current design for client/manager decks.
   * Distinct from the faithful technical render; swaps the hero image to the
   * result. Photoreal today via the image provider; faithful-photoreal once a
   * Replicate token enables ControlNet-depth. */
  const submitPresent = async (
    mood?: { setting?: string; light?: string; palette?: string },
  ): Promise<boolean> => {
    if (!activeProjectId || !latestGeneration || isPresenting) return false;
    setIsPresenting(true);
    try {
      const res = await designApi.present(token, activeProjectId, mood);
      if (res.image_url) {
        replaceGenerations(
          generations.map((g) =>
            g.id === latestGeneration.id ? { ...g, url: res.image_url ?? g.url } : g,
          ),
        );
      }
      return true;
    } catch (e) {
      toastError(e, "Presentation render failed");
      return false;
    } finally {
      setIsPresenting(false);
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
      // render:false returns the saved spec fast (graph, estimate, validation)
      // and skips the ~minute photoreal finish. The drawings, 3D and spec reflect
      // the edit immediately; the image is refreshed right after by the
      // stale-render effect below, so the edit never blocks the UI on the finish.
      const editRes = await designApi.editObject(
        token,
        activeProjectId,
        { object_id: selectedObjectId, prompt: editPrompt.trim() },
        { render: false },
      );

      addGeneration({
        id: crypto.randomUUID(),
        prompt: `${latestGeneration.prompt} — ${editPrompt.trim()}`,
        // Carry the previous image forward so the hero isn't blank while the
        // fresh photoreal renders; the stale-render effect swaps it in.
        url: editRes.image_url ?? latestGeneration.url,
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
      // Refresh the photoreal once this new version is the active one. The
      // effect (below) fires when latestGeneration catches up, so submitRerender
      // reads fresh state instead of the stale closure we'd have here.
      setStaleRenderVersion(editRes.version);
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

  /* After a fast (render-skipped) edit, refresh the photoreal once the new
     version is the active/latest one. Running it here — rather than inline in
     submitEdit — means submitRerender reads the freshly-committed state instead
     of the stale closure it would capture mid-submit. */
  useEffect(() => {
    if (staleRenderVersion == null) return;
    if (latestGeneration?.version !== staleRenderVersion) return;
    setStaleRenderVersion(null);
    void submitRerender();
    // submitRerender + latestGeneration are intentionally excluded — this must
    // fire exactly once, when the target version becomes latest.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latestGeneration?.version, staleRenderVersion]);

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

    // Fold the left-rail brief (dimensions / needs / budget / codes / climate)
    // into the prompt so the design honours it instead of guessing. The raw
    // user prompt is still what we store + display on the generation record.
    const briefSuffix = assembleBriefPrompt(briefSpace, briefRequirements, briefRegulatory);
    const effectivePrompt = (prompt.trim() + briefSuffix).trim();

    try {
      // 1 — ensure active project
      let projectId = activeProjectId;
      if (!projectId) {
        const project = await projectsApi.create(token, {
          name: prompt.trim().slice(0, 60) || "Untitled design",
          // Backend ProjectCreate requires a prompt (min 10 chars). It's
          // unused by the create route — generation gets its own prompt
          // below — but must be present for schema validation. Pad short
          // briefs so a terse prompt can't trip the 10-char minimum.
          prompt: prompt.trim().padEnd(10, " "),
          project_type: projectType,
          region,
        });
        projectId = project.id;
        setActiveProject(projectId, null, project.name);
      }

      // 2 — single backend call: graph + render baked together
      const graphRes = await designApi.generate(token, projectId, {
        prompt: effectivePrompt,
        // room_type intentionally omitted — the backend derives it from
        // the prompt (knowledge.infer_room_type) instead of assuming one.
        style: theme,
        ratio,
        // The actual workspace selections drive the render, not fixed
        // strings — the camera / lighting controls now reach the model.
        camera,
        lighting,
        view_mode: viewMode,
        drawing_type: "3d-render",
        // Site + climate brief → the backend reasons from constraints for
        // exterior designs (e.g. adds a brise-soleil on a sun-exposed facade)
        // and returns design_rationale. Built from the left-rail Space & Site
        // (orientation) + Regulatory (climate zone); absent fields are a no-op.
        site: {
          climate_zone: briefRegulatory.climatic_zone || undefined,
          facade_orientation: briefSpace.orientation || undefined,
          location: briefSpace.site_notes?.trim() || undefined,
        },
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

      // Surface the climate-responsive design decisions the backend reasoned
      // from the site & climate brief (design_reasoning) — the "what it decided
      // and why". Present only for exterior designs given a site brief.
      if (graphRes.design_rationale?.length) {
        const n = graphRes.design_rationale.length;
        useToastStore.getState().notify({
          type: "success",
          title: `Design decisions · ${n} applied`,
          message: graphRes.design_rationale[0],
        });
        setGenerateNotice("Your brief shaped this design — " + graphRes.design_rationale[0]);
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
        camera,
        lighting,
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
        onOpenModel={() => setModelOpen(true)}
        onOpenFloorplan={() => setFloorplanOpen(true)}
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
      <ModelImportDialog
        open={modelOpen}
        onClose={() => setModelOpen(false)}
        token={token}
        onOpened={(projectId, version, name) => setActiveProject(projectId, version, name)}
      />
      <FloorplanImportDialog
        open={floorplanOpen}
        onClose={() => setFloorplanOpen(false)}
        token={token}
        onOpened={(projectId, version, name) => setActiveProject(projectId, version, name)}
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
          camera={camera}
          setCamera={setCamera}
          lighting={lighting}
          setLighting={setLighting}
          theme={theme}
          space={briefSpace}
          setSpace={setBriefSpace}
          requirements={briefRequirements}
          setRequirements={setBriefRequirements}
          regulatory={briefRegulatory}
          setRegulatory={setBriefRegulatory}
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
            focusedId={focusedGenId}
            onFocus={setFocusedGenId}
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
                focusedId={focusedGenId}
                onFocus={setFocusedGenId}
                selectedObjectId={selectedObjectId}
                onSelectObject={setSelectedObjectId}
                isGenerating={isGenerating}
                isEditing={isEditing}
                isSwitchingTheme={isSwitchingTheme}
                pendingPrompt={prompt}
                onRerender={submitRerender}
                isRerendering={isRerendering}
                onPresent={submitPresent}
                isPresenting={isPresenting}
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
          estimate={latestGeneration?.estimate}
          activeProjectId={activeProjectId}
          latestVersion={latestGeneration?.version ?? null}
          token={token ?? ""}
          scope={scope}
        />
      </div>

      {terminalOpen ? (
        <TerminalPanel
          tab={terminalTab}
          setTab={setTerminalTab}
          hasDesign={generations.length > 0}
          validation={latestGeneration?.validation}
          mepCost={latestGeneration?.mepCostEstimate}
          codeCompliance={latestGeneration?.codeCompliance}
          generation={latestGeneration}
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
  onOpenModel,
  onOpenFloorplan,
  onOpenProjects,
}: {
  onToggleTerminal: () => void;
  terminalOpen: boolean;
  onOpenImport: () => void;
  onOpenModel: () => void;
  onOpenFloorplan: () => void;
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
            onClick={onOpenModel}
            className="text-[12px] text-ink-soft hover:text-ink transition-colors px-2 py-1 inline-flex items-center gap-1"
            aria-label="Import 3D model"
            title="Upload a 3D model → render + spec sheet"
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 13 13"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M6.5 1.2 11 3.6v5.8L6.5 11.8 2 9.4V3.6z M2 3.6 6.5 6 11 3.6 M6.5 6v5.8"
                stroke="currentColor"
                strokeWidth="1.2"
                strokeLinejoin="round"
              />
            </svg>
            3D model
          </button>
          <button
            type="button"
            onClick={onOpenFloorplan}
            className="text-[12px] text-ink-soft hover:text-ink transition-colors px-2 py-1 inline-flex items-center gap-1"
            aria-label="Import floor plan"
            title="Upload a floor plan → multi-room design"
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 13 13"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M1.5 1.5h10v10h-10z M1.5 6.5h6 M7.5 1.5v10 M7.5 6.5h4"
                stroke="currentColor"
                strokeWidth="1.2"
                strokeLinejoin="round"
              />
            </svg>
            Floor plan
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

// Fold the left-rail brief into a natural-language constraint suffix so the
// generator honours the architect's dimensions / budget / needs / codes /
// climate instead of guessing them. Returns "" when nothing is filled.
function assembleBriefPrompt(space: BriefSpace, req: BriefRequirements, reg: BriefRegulatory): string {
  const bits: string[] = [];
  const u = space.unit || "m";
  const L = parseFloat(space.length), W = parseFloat(space.width), H = parseFloat(space.height);
  if (isFinite(L) && isFinite(W) && L > 0 && W > 0) {
    bits.push(`sized exactly ${space.length}${u} by ${space.width}${u}` +
      (isFinite(H) && H > 0 ? ` with a ${space.height}${u} ceiling` : ""));
  }
  if (space.orientation.trim()) bits.push(`${space.orientation.trim()}-facing`);
  if (space.constraints.trim()) bits.push(`site constraints: ${space.constraints.trim()}`);
  if (space.site_notes.trim()) bits.push(space.site_notes.trim());
  if (req.functional_needs.trim()) bits.push(`must include: ${req.functional_needs.trim()}`);
  if (req.aesthetic_preferences.trim()) bits.push(`aesthetic: ${req.aesthetic_preferences.trim()}`);
  const budget = parseFloat(req.budget);
  if (isFinite(budget) && budget > 0) bits.push(`budget approximately INR ${budget.toLocaleString("en-IN")}`);
  const weeks = parseInt(req.timeline_weeks, 10);
  if (isFinite(weeks) && weeks > 0) bits.push(`timeline about ${weeks} weeks`);
  if (req.narrative.trim()) bits.push(req.narrative.trim());
  const loc = [reg.city, reg.state, reg.country].map((x) => x.trim()).filter(Boolean).join(", ");
  if (loc) bits.push(`located in ${loc}`);
  if (reg.building_codes.trim()) bits.push(`must comply with ${reg.building_codes.trim()}`);
  if (reg.climatic_zone) bits.push(`${reg.climatic_zone.replace(/_/g, " ")} climate`);
  if (reg.compliance_notes.trim()) bits.push(reg.compliance_notes.trim());
  return bits.length ? ` Brief constraints — ${bits.join("; ")}.` : "";
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
  camera,
  setCamera,
  lighting,
  setLighting,
  theme,
  space,
  setSpace,
  requirements,
  setRequirements,
  regulatory,
  setRegulatory,
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
  camera: CameraMode;
  setCamera: (c: CameraMode) => void;
  lighting: LightingMode;
  setLighting: (l: LightingMode) => void;
  theme: ArchTheme;
  space: BriefSpace;
  setSpace: (v: BriefSpace) => void;
  requirements: BriefRequirements;
  setRequirements: (v: BriefRequirements) => void;
  regulatory: BriefRegulatory;
  setRegulatory: (v: BriefRegulatory) => void;
}) {
  // Multi-open accordion — architects often want to see Brief + Space
  // simultaneously when tuning a design. State persists to localStorage
  // so the next session re-opens the same sections (small but high-
  // value for architects who tune Brief + Regulatory together every
  // time). Brief is open by default on first visit.
  const ACCORDION_KEY = "katha.design.accordion.openSections";
  // Start from the deterministic default so the server-rendered HTML and
  // the first client render agree (reading localStorage during render
  // causes a hydration mismatch). Persisted state is applied after mount.
  const [openSections, setOpenSections] = useState<Set<string>>(
    () => new Set(["brief"]),
  );
  const [accordionHydrated, setAccordionHydrated] = useState(false);
  useEffect(() => {
    try {
      const raw = localStorage.getItem(ACCORDION_KEY);
      if (raw) setOpenSections(new Set(JSON.parse(raw) as string[]));
    } catch {}
    setAccordionHydrated(true);
  }, []);
  useEffect(() => {
    // Don't persist until the stored state has been loaded, otherwise the
    // initial default would clobber the user's saved sections on mount.
    if (!accordionHydrated) return;
    try {
      localStorage.setItem(ACCORDION_KEY, JSON.stringify([...openSections]));
    } catch {}
  }, [openSections, accordionHydrated]);
  const toggle = (id: string) => {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Brief section state (Space & Site / Requirements / Regulatory) is owned by
  // the workspace and passed in as props, so Generate can fold it into the
  // prompt. Save brief still packages all three into a single /brief/intake POST.
  const [saving, setSaving] = useState(false);
  const [briefSaved, setBriefSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const notify = useToastStore((s) => s.notify);

  const saveBrief = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      // `theme` is REQUIRED by /brief/intake — omitting it 422'd every save.
      // The sidebar has no theme selector, so carry the workspace theme: map it
      // to the brief enum, or fall back to `custom` with the raw value so any
      // theme still validates.
      const KNOWN_THEMES = new Set(["pedestal", "contemporary", "modern", "mid_century_modern"]);
      const t = String(theme || "modern").toLowerCase().replace(/[\s-]+/g, "_");
      const themeSection = KNOWN_THEMES.has(t)
        ? { theme: t }
        : { theme: "custom", custom_spec: String(theme || "modern") };
      const payload: import("@/lib/api-client").BriefIntakePayload = {
        project_type: { type: projectType, scale: "" },
        theme: themeSection,
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
          <section>
            <SectionTag>Camera</SectionTag>
            <div className="mt-2.5 grid grid-cols-2 gap-1.5">
              {CAMERAS.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className="slide-pill text-center"
                  data-active={c.id === camera}
                  onClick={() => setCamera(c.id)}
                >
                  {c.label}
                </button>
              ))}
            </div>
          </section>
          <section>
            <SectionTag>Lighting</SectionTag>
            <div className="mt-2.5 grid grid-cols-2 gap-1.5">
              {LIGHTINGS.map((l) => (
                <button
                  key={l.id}
                  type="button"
                  className="slide-pill text-center"
                  data-active={l.id === lighting}
                  onClick={() => setLighting(l.id)}
                >
                  {l.label}
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
  focusedId,
  onFocus,
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
  focusedId: string | null;
  onFocus: (id: string) => void;
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
    <div className="relative z-40 px-6 py-2 border-b border-hairline bg-paper/85 backdrop-blur-sm flex items-center justify-end gap-3">
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
      {/* HapticReadyBadge removed from the header for now (revisiting haptic
          later). The component below is kept so re-enabling is a one-liner. */}
      <ExportButton
        onClick={onOpenExport}
        disabled={!hasActiveProject}
      />
      {projectGenerations.length > 0 ? (
        <VersionTimeline
          generations={projectGenerations}
          focusedId={focusedId}
          onFocus={onFocus}
        />
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
  focusedId,
  onFocus,
}: {
  generations: import("@/lib/types").ImageGeneration[];
  focusedId: string | null;
  onFocus: (id: string) => void;
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
          const isFocused = g.id === focusedId;
          // Clicking a version chip focuses that render in the hero
          // (the canvas is a focused-hero + filmstrip, so there's no
          // per-card anchor to scroll to anymore). Pencil marks the
          // focused chip; the latest stays pencil-weighted as the
          // working version even when another is being viewed.
          return (
            <button
              key={g.id}
              type="button"
              aria-pressed={isFocused}
              onClick={() => onFocus(g.id)}
              className={`px-1.5 py-0.5 rounded-sm transition-colors ${
                isFocused
                  ? "text-pencil font-medium bg-pencil-bg"
                  : isLatest
                  ? "text-pencil font-medium hover:bg-paper-soft"
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
  const scopeLabel = SCOPES.find((s) => s.id === scope)?.label ?? "Interior";

  // The three moves, drawn as a numbered sequence rather than three
  // generic cards — brass numerals echo the drawing-index register.
  const steps: { n: string; title: string; body: string }[] = [
    {
      n: "01",
      title: "Configure",
      body: `Scope set to ${scopeLabel}, ${dim.toUpperCase()} — standards and cost bands load to match.`,
    },
    {
      n: "02",
      title: "Prompt",
      body: `Describe the design. KATHA reads it as a ${lowerLabel} project and pulls the right codes.`,
    },
    {
      n: "03",
      title: "Iterate",
      body: "Cost streams live in the terminal below. Re-prompt to refine; export to edit.",
    },
  ];

  return (
    <div className="px-6 md:px-10 py-14 max-w-3xl mx-auto">
      {/* Drawing sheet — pinned on the drafting table (the gridpaper
          canvas). Corner registration marks + a title-block header make
          the sheet metaphor legible; the whole surface is where the
          architect is about to draw. */}
      <div className="relative bg-paper border border-hairline shadow-card px-7 md:px-11 py-9 md:py-11">
        {/* Registration / crop marks at the four corners. */}
        <span aria-hidden className="absolute -top-px -left-px h-3.5 w-3.5 border-t-2 border-l-2 border-graphite" />
        <span aria-hidden className="absolute -top-px -right-px h-3.5 w-3.5 border-t-2 border-r-2 border-graphite" />
        <span aria-hidden className="absolute -bottom-px -left-px h-3.5 w-3.5 border-b-2 border-l-2 border-graphite" />
        <span aria-hidden className="absolute -bottom-px -right-px h-3.5 w-3.5 border-b-2 border-r-2 border-graphite" />

        {/* Title block — mono sheet designation left, ready status right. */}
        <div className="flex items-center justify-between gap-4">
          <span className="mono-tag">
            New sheet · {projectTypeLabel} / {scopeLabel} · {dim.toUpperCase()}
          </span>
          <span className="mono-tag inline-flex items-center whitespace-nowrap">
            <span aria-hidden className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-pencil align-middle" />
            Ready
          </span>
        </div>

        <div className="mt-4 h-px bg-hairline" />

        {/* Headline — the editorial serif moment (Newsreader). */}
        <h1 className="mt-7 font-display text-[2.1rem] md:text-[2.6rem] text-ink-deep leading-[1.1] tracking-[-0.015em]">
          A {lowerLabel} canvas,
          <br />
          ready when you are.
        </h1>
        <p className="mt-4 max-w-lg text-[15px] leading-relaxed text-ink-soft">
          Standards, ergonomic ranges, and cost defaults are tuned for{" "}
          <strong className="font-semibold text-ink">{lowerLabel}</strong>{" "}
          projects. Pick a starter below, or write your own prompt.
        </p>

        {/* Starter prompts as pinned, indexed reference notes. */}
        {starterPrompts.length > 0 ? (
          <div className="mt-9">
            <SectionTag>Starter prompts</SectionTag>
            <div className="mt-3.5">
              {starterPrompts.map((s, i) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => onPickPrompt(s)}
                  className="group flex w-full items-start gap-3.5 rounded-md border border-transparent px-3 py-3 text-left transition-colors hover:border-hairline hover:bg-paper-soft"
                >
                  <span className="pt-0.5 font-mono text-[12px] tabular-nums text-ink-mute transition-colors group-hover:text-pencil">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className="flex-1 text-[14px] leading-snug text-ink">{s}</span>
                  <span aria-hidden className="pt-0.5 text-[13px] text-ink-mute transition-all group-hover:translate-x-0.5 group-hover:text-pencil">
                    →
                  </span>
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      {/* Workflow strip — three moves as a connected numbered sequence,
          hairline-separated so they read as one drawing, not three cards. */}
      <div className="mt-8 grid grid-cols-1 gap-px overflow-hidden rounded-md border border-hairline bg-hairline md:grid-cols-3">
        {steps.map((step) => (
          <div key={step.n} className="bg-paper px-5 py-5">
            <div className="flex items-baseline gap-2.5">
              <span className="font-mono text-[15px] tabular-nums text-brass">{step.n}</span>
              <h3 className="text-[13.5px] font-semibold tracking-[-0.01em] text-ink-deep">
                {step.title}
              </h3>
            </div>
            <p className="mt-2 text-[12.5px] leading-relaxed text-ink-soft">{step.body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

/* Presentation-render mood options — mirror presentation.py's knobs. "" = Auto
   (the backend derives a tasteful default from the design). */
const PRESENT_SETTINGS: [string, string][] = [
  ["", "Auto"], ["mediterranean", "Mediterranean"], ["coastal", "Coastal"],
  ["desert", "Desert"], ["quarry", "Quarry"], ["forest", "Forest"],
  ["garden", "Garden"], ["urban", "Urban"],
];
const PRESENT_LIGHTS: [string, string][] = [
  ["", "Auto"], ["golden_hour", "Golden hour"], ["morning", "Morning"],
  ["midday", "Midday"], ["blue_hour", "Blue hour"], ["overcast", "Overcast"],
];
const PRESENT_PALETTES: [string, string][] = [
  ["", "Auto"], ["natural_warm", "Warm natural"], ["coastal_light", "Coastal light"],
  ["mineral", "Mineral"], ["monochrome_stone", "Stone"],
];

function MoodSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: [string, string][];
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-2 text-[11px]">
      <span className="font-mono uppercase tracking-[0.1em] text-ink-mute">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="flex-1 max-w-[8.5rem] rounded border border-hairline bg-paper px-1.5 py-1 text-[11px] text-ink-deep focus:outline-none focus:ring-1 focus:ring-pencil/40"
      >
        {options.map(([v, l]) => (
          <option key={v} value={v}>{l}</option>
        ))}
      </select>
    </label>
  );
}

/* CanvasGallery — focused-hero + history filmstrip.
 *
 * The architect iterates by comparing attempts, so the canvas reads like
 * the render tools they already use (Midjourney / Vizcom / Veras): ONE
 * render large (the hero) with every prior attempt a glance away in a
 * horizontal filmstrip. Clicking a thumb focuses it in the hero for
 * visual compare; the working (latest) version still drives the right
 * rail + edit loop, so focusing an older render is explicitly read-only.
 */
function CanvasGallery({
  generations,
  dim,
  focusedId,
  onFocus,
  selectedObjectId,
  onSelectObject,
  isGenerating,
  isEditing,
  isSwitchingTheme,
  pendingPrompt,
  onRerender,
  isRerendering,
  onPresent,
  isPresenting,
}: {
  generations: import("@/lib/types").ImageGeneration[];
  dim: Dim;
  focusedId: string | null;
  onFocus: (id: string) => void;
  selectedObjectId: string | null;
  onSelectObject: (id: string | null) => void;
  isGenerating: boolean;
  isEditing: boolean;
  isSwitchingTheme: boolean;
  pendingPrompt: string;
  onRerender?: () => Promise<boolean>;
  isRerendering?: boolean;
  onPresent?: (mood?: { setting?: string; light?: string; palette?: string }) => Promise<boolean>;
  isPresenting?: boolean;
}) {
  // Any of the three async paths shows a skeleton — the user shouldn't
  // have to mentally map which spinner means what.
  const pending = isGenerating || isEditing || isSwitchingTheme;
  const pendingLabel = isGenerating
    ? "Generating"
    : isEditing
    ? "Applying edit"
    : "Switching theme";

  // Hero surface: finished 2D render · live orbitable 3D model · editable 2D plan.
  const [heroView, setHeroView] = useState<"image" | "model" | "plan">("image");
  // Presentation mood — Setting · Light · Palette knobs for the ✨ Present render
  // ("" = let the backend auto-derive a tasteful default from the design).
  const [presentMood, setPresentMood] = useState({ setting: "", light: "", palette: "" });
  const [moodOpen, setMoodOpen] = useState(false);

  // Resolve the hero: the focused render, falling back to the latest.
  const focusedIndex = Math.max(
    0,
    generations.findIndex((g) => g.id === focusedId),
  );
  const hero = generations[focusedIndex] ?? generations[0] ?? null;
  const isHeroLatest = focusedIndex === 0;
  // Filmstrip earns its space once there's more than one render, or while
  // a new one is in flight (so the pending thumb has a home).
  const showStrip = generations.length > 1 || pending;

  return (
    <div className="px-6 md:px-10 py-6 max-w-5xl mx-auto space-y-4">
      {/* HERO — the render under evaluation, large. */}
      {pending ? (
        <GenerationSkeletonCard
          label={pendingLabel}
          version={generations.length + 1}
          prompt={pendingPrompt}
          dim={dim}
        />
      ) : hero ? (
        <PaperCard
          key={hero.id}
          className="p-5 anim-fade-in transition-shadow"
        >
          <div className="flex items-baseline justify-between mb-3">
            <div className="flex items-baseline gap-3">
              <SectionTag>
                Render · {String(generations.length - focusedIndex).padStart(2, "0")}
              </SectionTag>
              {hero.version != null ? (
                <span
                  className={`font-mono text-[10px] uppercase tracking-[0.12em] tnum ${
                    isHeroLatest ? "text-pencil" : "text-ink-mute"
                  }`}
                >
                  v{String(hero.version).padStart(2, "0")}
                </span>
              ) : (
                <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute">
                  unversioned
                </span>
              )}
              {!isHeroLatest ? (
                <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute">
                  history · read-only
                </span>
              ) : null}
            </div>
            <Annotation>
              {new Date(hero.timestamp).toLocaleString([], {
                hour: "2-digit",
                minute: "2-digit",
                day: "2-digit",
                month: "short",
              })}
            </Annotation>
          </div>
          {hero.url ? (
            // Real render — rounded inset on white card. The image carries
            // its own pixels; no grid-paper background underneath. URL
            // resolver normalises legacy data:/http: URLs and prefixes
            // backend-relative paths with the API origin. This render is the
            // EXACT kernel model (it matches the plan / 3D / drawings). Object
            // select + edit still lives on the 3D / Plan views (below), which
            // raycast and drag the real geometry — the cleaner edit surface.
            <div className="relative aspect-video bg-paper-deep border border-hairline rounded-md overflow-hidden">
              {heroView === "model" && hero.projectId ? (
                <DesignViewport3D
                  projectId={hero.projectId}
                  version={hero.version ?? undefined}
                  graph={hero.graphData}
                  selectedObjectId={selectedObjectId}
                  onSelectObject={onSelectObject}
                />
              ) : heroView === "plan" && hero.projectId ? (
                <DesignPlanEditor
                  projectId={hero.projectId}
                  graph={hero.graphData}
                  selectedObjectId={selectedObjectId}
                  onSelectObject={onSelectObject}
                />
              ) : (
                <>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={resolveAssetUrl(hero.url)}
                    alt={hero.prompt}
                    className="absolute inset-0 w-full h-full object-cover"
                  />
                  {/* The render IS the exact kernel model — the clay render, or a
                      depth-locked ControlNet finish when a Replicate token is set —
                      so it matches the plan / 3D / drawings. Object select + edit
                      lives on the 3D and Plan views (which raycast / drag the real
                      geometry) and the Objects list, so it stays pixel-accurate; we
                      don't draw a click-to-edit overlay on the render itself. */}
                  {isHeroLatest ? (
                    <div className="absolute bottom-2 left-2 z-10 flex items-center gap-1.5 rounded-md border border-hairline bg-paper/85 px-2.5 py-1 font-mono text-[9px] uppercase tracking-[0.12em] text-ink-mute backdrop-blur-sm pointer-events-none">
                      Model render · select &amp; edit in 3D / Plan
                    </div>
                  ) : null}
                </>
              )}
              {/* Render · live 3D model · editable 2D plan */}
              {hero.projectId ? (
                <div className="absolute top-2 right-2 z-10 flex rounded-md border border-hairline bg-paper/85 backdrop-blur-sm overflow-hidden">
                  {([
                    ["image", "Render"],
                    ["model", "3D"],
                    ["plan", "Plan"],
                  ] as const).map(([v, label]) => (
                    <button
                      key={v}
                      type="button"
                      onClick={() => setHeroView(v)}
                      aria-pressed={heroView === v}
                      className={`px-2.5 py-1 font-mono text-[9px] uppercase tracking-[0.12em] transition-colors ${
                        heroView === v
                          ? "bg-ink text-paper"
                          : "text-ink-soft hover:text-ink"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              ) : null}
              {/* Re-render the photoreal image from the edited spec */}
              {heroView !== "image" && hero.projectId && onRerender ? (
                <button
                  type="button"
                  disabled={isRerendering}
                  onClick={async () => {
                    const ok = await onRerender();
                    if (ok) setHeroView("image");
                  }}
                  className="absolute top-2 left-2 z-10 rounded-md border border-hairline bg-paper/85 backdrop-blur-sm px-2.5 py-1 font-mono text-[9px] uppercase tracking-[0.12em] text-ink-soft hover:text-ink disabled:opacity-60 transition-colors"
                >
                  {isRerendering ? "Re-rendering…" : "⟳ Re-render"}
                </button>
              ) : null}
              {/* Presentation (hero) render + mood picker — atmospheric, styled
                  photo for client/manager decks. Distinct from the faithful render. */}
              {heroView === "image" && hero.projectId && onPresent ? (
                <div className="absolute top-2 left-2 z-10 flex items-center gap-1">
                  <button
                    type="button"
                    disabled={isPresenting}
                    onClick={() => void onPresent(presentMood)}
                    title="Hero render — atmospheric, styled architectural photo for decks"
                    className="rounded-md border border-pencil/30 bg-pencil-bg/70 backdrop-blur-sm px-2.5 py-1 font-mono text-[9px] uppercase tracking-[0.12em] text-pencil hover:bg-pencil-bg disabled:opacity-60 transition-colors"
                  >
                    {isPresenting ? "Rendering…" : "✨ Present"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setMoodOpen((o) => !o)}
                    aria-expanded={moodOpen}
                    aria-label="Presentation mood"
                    title="Mood — setting · light · palette"
                    className="rounded-md border border-pencil/30 bg-pencil-bg/70 backdrop-blur-sm px-1.5 py-1 font-mono text-[9px] text-pencil hover:bg-pencil-bg transition-colors"
                  >
                    {moodOpen ? "▴" : "▾"}
                  </button>
                  {moodOpen ? (
                    <div className="absolute top-full left-0 mt-1 w-60 rounded-md border border-hairline bg-paper shadow-card p-2.5 space-y-2">
                      <div className="font-mono text-[9px] uppercase tracking-[0.12em] text-ink-mute">
                        Presentation mood
                      </div>
                      <MoodSelect label="Setting" value={presentMood.setting} options={PRESENT_SETTINGS}
                        onChange={(v) => setPresentMood((m) => ({ ...m, setting: v }))} />
                      <MoodSelect label="Light" value={presentMood.light} options={PRESENT_LIGHTS}
                        onChange={(v) => setPresentMood((m) => ({ ...m, light: v }))} />
                      <MoodSelect label="Palette" value={presentMood.palette} options={PRESENT_PALETTES}
                        onChange={(v) => setPresentMood((m) => ({ ...m, palette: v }))} />
                      <button
                        type="button"
                        disabled={isPresenting}
                        onClick={() => { setMoodOpen(false); void onPresent(presentMood); }}
                        className="w-full mt-1 rounded border border-pencil/40 bg-pencil-bg px-2 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-pencil hover:bg-pencil-bg/80 disabled:opacity-60 transition-colors"
                      >
                        {isPresenting ? "Rendering…" : "✨ Render this mood"}
                      </button>
                    </div>
                  ) : null}
                </div>
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
                  {dim.toUpperCase()} · {hero.prompt.slice(0, 60)}
                  {hero.prompt.length > 60 ? "…" : ""}
                </div>
                <div className="mt-3 text-[11px] font-mono text-ink-mute">
                  GEMINI_API_KEY not set — graph saved, image skipped.
                </div>
              </div>
            </div>
          )}
          <div className="mt-3 text-[12px] text-ink-soft leading-relaxed">
            {hero.prompt}
          </div>
        </PaperCard>
      ) : null}

      {/* HISTORY FILMSTRIP — every attempt, newest first, click to focus. */}
      {showStrip ? (
        <div className="rounded-lg border border-hairline bg-paper-soft p-2">
          <div className="flex items-baseline justify-between px-1 pb-2">
            <SectionTag>History · {String(generations.length).padStart(2, "0")}</SectionTag>
            <Annotation>click to compare</Annotation>
          </div>
          <div className="flex gap-2 overflow-x-auto draft-scroll pb-1">
            {pending ? (
              <div className="shrink-0 w-[132px] aspect-video rounded-md border border-hairline bg-paper-deep skeleton-shimmer flex items-center justify-center">
                <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-ink-mute">
                  {pendingLabel}
                </span>
              </div>
            ) : null}
            {generations.map((g, i) => {
              const isFocused = g.id === hero?.id;
              const isLatest = i === 0;
              return (
                <button
                  key={g.id}
                  type="button"
                  aria-pressed={isFocused}
                  aria-label={`Focus render ${generations.length - i}${g.version != null ? `, version ${g.version}` : ""}`}
                  onClick={() => onFocus(g.id)}
                  className={`group relative shrink-0 w-[132px] aspect-video rounded-md overflow-hidden border transition-all ${
                    isFocused
                      ? "border-pencil ring-1 ring-pencil"
                      : "border-hairline hover:border-graphite"
                  }`}
                >
                  {g.url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={resolveAssetUrl(g.url)}
                      alt={g.prompt}
                      className="absolute inset-0 w-full h-full object-cover"
                    />
                  ) : (
                    <div className="absolute inset-0 bg-paper-deep grid-paper flex items-center justify-center">
                      <span className="font-mono text-[10px] text-ink-mute">no render</span>
                    </div>
                  )}
                  {/* Bottom label strip — version + latest marker. Kept
                      legible over any image with a soft ink gradient. */}
                  <div className="absolute inset-x-0 bottom-0 flex items-center justify-between px-1.5 py-1 bg-gradient-to-t from-ink-deep/70 to-transparent">
                    <span className="font-mono text-[9px] uppercase tracking-[0.1em] tnum text-paper">
                      {g.version != null ? `v${String(g.version).padStart(2, "0")}` : "—"}
                    </span>
                    {isLatest ? (
                      <span className="font-mono text-[8px] uppercase tracking-[0.12em] text-pencil-soft">
                        latest
                      </span>
                    ) : null}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
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
  estimate,
  activeProjectId,
  latestVersion,
  token,
  scope,
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
  estimate?: unknown;
  activeProjectId: string | null;
  latestVersion: number | null;
  token: string;
  scope: Scope;
}) {
  const hasGraph = objects.length > 0;
  const TAB_KEY = "katha.design.rightRail.activeTab";
  // Deterministic default on first render so SSR HTML matches the first
  // client render; the persisted tab is restored after mount to avoid a
  // hydration mismatch.
  const [tab, setTab] = useState<RightTab>("summary");
  const [tabHydrated, setTabHydrated] = useState(false);
  useEffect(() => {
    try {
      const saved = localStorage.getItem(TAB_KEY) as RightTab | null;
      const allowed: RightTab[] = ["summary", "views", "specs", "cost", "compliance", "recs"];
      if (saved && allowed.includes(saved)) setTab(saved);
    } catch {}
    setTabHydrated(true);
  }, []);
  useEffect(() => {
    if (!tabHydrated) return;
    try { localStorage.setItem(TAB_KEY, tab); } catch {}
  }, [tab, tabHydrated]);

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
    <aside className="w-80 shrink-0 bg-paper-soft border-l border-hairline overflow-y-auto draft-scroll">
      {/* Sticky tab bar — sits at the top of the rail; pencil-red
          underline marks the active tab (same register as the bottom
          terminal tabs for visual continuity). ARIA roles let screen
          readers and keyboard users navigate with arrow keys + Tab.

          NOTE: the aside is intentionally NOT `flex flex-col`. Position
          sticky inside an overflow-y-auto flex column container is
          unreliable — the flex layout can compress the sticky child
          and break the anchor. Block flow + overflow-y-auto on the
          aside gives sticky a stable scroll context. */}
      <div
        role="tablist"
        aria-label="Design review surfaces"
        className="sticky top-0 z-20 bg-paper-soft border-b border-hairline shadow-[0_1px_0_rgba(0,0,0,0.02),0_4px_8px_-6px_rgba(0,0,0,0.08)] px-1.5 flex items-center overflow-x-auto draft-scroll"
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
              className={`font-mono text-[10.5px] uppercase tracking-[0.06em] px-1.5 py-2.5 transition-colors border-b-2 whitespace-nowrap focus:outline-none focus-visible:ring-2 focus-visible:ring-pencil/40 focus-visible:rounded-sm ${
                active
                  ? "text-ink-deep border-pencil"
                  : "text-ink-soft hover:text-ink-deep border-transparent"
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
        className="px-5 py-5"
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
            scope={scope}
          />
        ) : tab === "cost" ? (
          <CostTab hasDesign={hasDesign} estimate={estimate} mepCost={mepCost} />
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
  scope,
}: {
  hasActiveProject: boolean;
  activeProjectId: string | null;
  latestVersion: number | null;
  token: string;
  /** Workspace scope selector — drives room-scale vs piece-scale drawings. */
  scope: string;
}) {
  const [loading, setLoading] = useState<string | null>(null);
  const [view, setView] = useState<{
    title: string;
    svg: string;
  } | null>(null);
  const notify = useToastStore((s) => s.notify);

  // Maps a working-drawing id to its project-scoped GET slug. plan_view
  // uses the deterministic floor-plan package; the other four are
  // LLM-backed furniture-scale generators (elevation/section/iso/detail).
  const DRAWING_SLUG: Record<string, "elevation-view" | "section-view" | "isometric-view" | "detail-sheet"> = {
    elevation_view: "elevation-view",
    section_view: "section-view",
    isometric_view: "isometric-view",
    detail_sheet: "detail-sheet",
  };

  // Fires the right project-scoped backend call. plan_view → floor-plan
  // package; the other working drawings → their deterministic geometry view route;
  // diagrams → design.generateDiagrams, which targets a single diagram_id.
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
          scope,
        );
        if (!res.preview_svg) {
          notify({ type: "warning", title: name, message: "No preview returned." });
        } else {
          setView({ title: name, svg: res.preview_svg });
        }
      } else if (DRAWING_SLUG[id]) {
        const res = await designApi.getDrawingView(
          token,
          activeProjectId,
          DRAWING_SLUG[id],
          latestVersion ?? undefined,
          scope,
        );
        if (!res.preview_svg) {
          notify({ type: "warning", title: name, message: "Generator returned no SVG." });
        } else {
          setView({ title: name, svg: res.preview_svg });
        }
      } else {
        notify({
          type: "warning",
          title: name,
          message: "This drawing type isn't available yet.",
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
      <ViewsSection title="Working Drawings" badge="5 sheets">
        {DRAWINGS_CATALOGUE.map((d) => (
          <ViewCard
            key={d.id}
            name={d.name}
            summary={d.summary}
            loading={loading === `drawing:${d.id}`}
            disabled={!hasActiveProject}
            extra={d.wired ? null : "Day 3"}
            onClick={() => open("drawing", d.id, d.name)}
          />
        ))}
      </ViewsSection>

      <ViewsSection title="Diagrams" badge="8 types">
        {DIAGRAMS_CATALOGUE.map((d) => (
          <ViewCard
            key={d.id}
            name={d.name}
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
  summary,
  loading,
  disabled,
  extra,
  onClick,
}: {
  name: string;
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
          {loading ? "…" : extra}
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
          // Injected SVG uses a viewBox with no intrinsic width/height, so we
          // size it to the body and let preserveAspectRatio letterbox the whole
          // sheet into view — no scrolling to reach the dimension row / title block.
          className="flex-1 min-h-0 overflow-hidden p-5 bg-paper-soft flex items-center justify-center [&>svg]:h-full [&>svg]:w-full [&>svg]:max-h-full"
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
type EstimateShape = {
  status?: string;
  area?: { total_sqft?: number; cost_per_sqft?: number };
  pricing_adjustments?: { final_total?: number };
  estimate?: Record<string, { total_cost?: number } | undefined>;
  total_low?: number;
  total_high?: number;
  confidence?: { score?: number; level?: string };
  currency?: string;
  display?: {
    currency?: string;
    currency_symbol?: string;
    region?: string;
    locale?: string;
    final_total?: number;
    cost_per_sqft?: number;
  };
};

function CostTab({
  hasDesign,
  estimate,
  mepCost,
}: {
  hasDesign: boolean;
  estimate?: unknown;
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
          ← /estimates/*
        </p>
      </div>
    );
  }
  const est = estimate as EstimateShape | undefined;
  const estFinalTotal = est?.pricing_adjustments?.final_total ?? 0;
  const hasEstimate = !!est && est.status === "computed" && estFinalTotal > 0;

  if (!hasEstimate && !mepCost) {
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

  const formatINR = (n?: number) =>
    n == null ? "—" : `₹${Math.round(n).toLocaleString("en-IN")}`;

  return (
    <div className="space-y-5">
      {/* Project estimate — the full build cost from the estimation engine
          (compute_estimate). Surfaces for EVERY design type: interior fit-out,
          architecture shell on built-up area, and per-unit products. */}
      {hasEstimate
        ? (() => {
            const d = est!.display;
            const sym = d?.currency_symbol || "₹";
            const locale = d?.locale || "en-IN";
            const fmt = (n?: number) =>
              n == null
                ? "—"
                : `${sym}${Math.round(n).toLocaleString(locale)}`;
            const displayTotal = d?.final_total ?? estFinalTotal;
            const totalSqft = est!.area?.total_sqft ?? 0;
            const costPerSqft = d?.cost_per_sqft ?? est!.area?.cost_per_sqft;
            const region = d?.region;
            const cats = est!.estimate || {};
            const catRows = (
              [
                ["Materials", cats.materials?.total_cost],
                ["Furniture", cats.furniture?.total_cost],
                ["Labour", cats.labor?.total_cost],
                ["Services", cats.services?.total_cost],
                ["Misc", cats.misc?.total_cost],
              ] as [string, number | undefined][]
            ).filter((r): r is [string, number] => (r[1] ?? 0) > 0);
            const conf = est!.confidence;
            return (
              <>
                <section>
                  <SectionTag>Project estimate</SectionTag>
                  <div className="mt-2 border border-hairline rounded-md bg-paper p-3">
                    <div className="font-mono text-[22px] text-ink-deep tnum tracking-tight">
                      {fmt(displayTotal)}
                    </div>
                    <div className="mt-1 flex items-center justify-between font-mono text-[10.5px] uppercase tracking-tagged text-ink-mute">
                      <span>
                        {totalSqft > 0
                          ? `${Math.round(totalSqft).toLocaleString(locale)} sqft${
                              costPerSqft != null
                                ? ` · ${fmt(costPerSqft)}/sqft`
                                : ""
                            }`
                          : "per-unit"}
                      </span>
                      <span>
                        {region
                          ? region.replace(/_/g, " ")
                          : d?.currency || est!.currency || "INR"}
                      </span>
                    </div>
                    {est!.total_low != null &&
                    est!.total_high != null &&
                    est!.total_high > 0 ? (
                      <div className="mt-1.5 font-mono text-[10.5px] text-ink-mute tnum">
                        range {formatINR(est!.total_low)}
                        <span className="mx-1">→</span>
                        {formatINR(est!.total_high)}
                      </div>
                    ) : null}
                  </div>
                </section>

                {catRows.length > 0 ? (
                  <section>
                    <SectionTag>By category</SectionTag>
                    <div className="mt-2 border-t border-hairline">
                      {catRows.map(([label, val]) => (
                        <div
                          key={label}
                          className="py-2 border-b border-hairline last:border-b-0 flex items-baseline justify-between gap-2"
                        >
                          <div className="text-[12.5px] text-ink-deep font-medium">
                            {label}
                          </div>
                          <div className="text-right shrink-0 font-mono text-[12px] text-ink tnum">
                            {formatINR(val)}
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                ) : null}

                {conf?.level ? (
                  <section className="flex items-baseline justify-between">
                    <SectionTag>Confidence</SectionTag>
                    <span className="font-mono text-[10.5px] uppercase tracking-tagged text-ink-mute">
                      {conf.level}
                      {conf.score != null
                        ? ` · ${Math.round(conf.score * 100)}%`
                        : ""}
                    </span>
                  </section>
                ) : null}
              </>
            );
          })()
        : null}

      {/* Building systems (MEP) — HVAC / Electrical / Plumbing / Fire, per m².
          A secondary block when a project estimate is present; the sole total
          for legacy versions that only carried an MEP estimate. */}
      {mepCost ? (
        <>
          <section>
            <SectionTag>
              {hasEstimate ? "Building systems (MEP)" : "Total estimate"}
            </SectionTag>
            <div className="mt-2 border border-hairline rounded-md bg-paper p-3">
              <div className="font-mono text-[20px] text-ink-deep tnum tracking-tight">
                {formatINR(mepCost.total_inr.low)}
                <span className="text-ink-mute mx-1.5">→</span>
                {formatINR(mepCost.total_inr.high)}
              </div>
              <div className="mt-1 flex items-center justify-between font-mono text-[10.5px] uppercase tracking-tagged text-ink-mute">
                <span>
                  {mepCost.area_m2.toFixed(1)} m² · {mepCost.currency}
                </span>
                <span>{mepCost.jurisdiction || "—"}</span>
              </div>
            </div>
          </section>

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
        </>
      ) : null}
    </div>
  );
}

/* ExportModal — opens from the Export chip in the canvas header.
 * Lists every backend-supported format, grouped by family so the
 * architect picks by recipient (Documents · CAD · BIM · 3D · CNC ·
 * Data). Click triggers design.exportFile() and downloads the blob. */
const EXPORT_FAMILIES: {
  family: string;
  formats: {
    id: import("@/lib/types").ExportFormat | string;
    label: string;
    ext: string;
    // Geometry-true drawing sheets route to /drawings/sheet, not /export.
    drawings?: "svg" | "pdf" | "dxf";
  }[];
}[] = [
  {
    family: "Documents",
    formats: [
      { id: "pdf",  label: "PDF",         ext: ".pdf" },
      { id: "docx", label: "Word",        ext: ".docx" },
      { id: "xlsx", label: "Excel",       ext: ".xlsx" },
      { id: "pptx", label: "PowerPoint",  ext: ".pptx" },
      { id: "html", label: "HTML Viewer", ext: ".html" },
      { id: "psd",  label: "Photoshop",   ext: ".psd" },
    ],
  },
  {
    // Geometry-true general-arrangement sheet (plan + section + elevation,
    // title block + code stamp) cut from the real kernel solids.
    family: "Drawings",
    formats: [
      { id: "sheet:pdf", label: "GA Sheet", ext: ".pdf", drawings: "pdf" },
      { id: "sheet:dxf", label: "GA Sheet (CAD)", ext: ".dxf", drawings: "dxf" },
      { id: "sheet:svg", label: "GA Sheet (vector)", ext: ".svg", drawings: "svg" },
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
    family: "Interop",
    formats: [{ id: "speckle", label: "Speckle (Revit · Rhino · Grasshopper)", ext: ".speckle.json" }],
  },
  {
    family: "CAD Exchange",
    formats: [
      { id: "step", label: "STEP", ext: ".step" },
      { id: "iges", label: "IGES", ext: ".iges" },
      { id: "3dm",  label: "Rhino 3DM", ext: ".3dm" },
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

// Single source of truth for the "N formats" copy — derived from the list above
// so the header tooltip and the modal footer can never drift out of sync.
const EXPORT_FORMAT_COUNT = EXPORT_FAMILIES.reduce((n, g) => n + g.formats.length, 0);

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

  const download = async (format: string, label: string, drawings?: "svg" | "pdf" | "dxf") => {
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
      const { blob, filename } = drawings
        ? await designApi.exportDrawingSheet(token, projectId, drawings)
        : await designApi.exportFile(
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
                  // Drawing sheets have their own endpoint, so they're always
                  // available (not gated on the /export registry format list).
                  const isAvailable = !!f.drawings || !available || available.has(f.id);
                  const isDownloading = downloading === f.id;
                  return (
                    <button
                      key={f.id}
                      type="button"
                      disabled={!isAvailable || isDownloading || !projectId}
                      onClick={() => download(f.id, f.label, f.drawings)}
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
            ← /projects/{"{id}"}/export · {EXPORT_FORMAT_COUNT} formats supported
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
      title="Haptic-ready data layer shipped. Hardware integration lands Phase 2 — Aug–Sept 2026."
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
      title={disabled ? "Generate a design first" : `Export to ${EXPORT_FORMAT_COUNT} formats`}
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
          ← /projects/{"{id}"}/specs
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
        <SpecTree data={bundle.manufacturing as unknown as Record<string, unknown>} />
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
              <SpecTree data={bundle.mep?.[sys] as Record<string, unknown> | undefined} />
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

/* SpecTree — recursively renders a spec section into readable rows instead
 * of dumping JSON: scalars become label/value rows, [low, high] pairs become
 * a range, scalar arrays become bullet lists, and nested objects / arrays of
 * objects become indented sub-blocks. Handles Manufacturing's joinery + QA
 * gates and MEP's ductwork / registers cleanly. */
const _isScalar = (v: unknown): boolean =>
  v === null || ["string", "number", "boolean"].includes(typeof v);

function _fmtNum(n: number): string {
  return Number.isInteger(n)
    ? n.toLocaleString("en-IN")
    : n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function _fmtScalar(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return _fmtNum(v);
  if (typeof v === "boolean") return v ? "Yes" : "No";
  return String(v);
}

/* Drop empty values so the tree never shows blank rows. */
function _specEntries(data?: Record<string, unknown>): [string, unknown][] {
  return Object.entries(data ?? {}).filter(
    ([, v]) =>
      v !== null &&
      v !== undefined &&
      v !== "" &&
      !(Array.isArray(v) && v.length === 0) &&
      !(typeof v === "object" && !Array.isArray(v) && Object.keys(v as object).length === 0),
  );
}

function SpecRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="py-1.5 border-b border-hairline last:border-b-0 flex items-baseline justify-between gap-3">
      <span className="font-mono text-[10px] uppercase tracking-tagged text-ink-mute shrink-0">
        {label.replace(/_/g, " ")}
      </span>
      <span className="text-[11.5px] text-ink text-right font-mono tnum break-words">{value}</span>
    </div>
  );
}

function SpecEntry({ k, v }: { k: string; v: unknown }) {
  const label = k.replace(/_/g, " ");
  if (_isScalar(v)) return <SpecRow label={label} value={_fmtScalar(v)} />;
  // [low, high] numeric pair → a range
  if (Array.isArray(v) && v.length === 2 && v.every((x) => typeof x === "number")) {
    return <SpecRow label={label} value={`${_fmtNum(v[0] as number)}–${_fmtNum(v[1] as number)}`} />;
  }
  // list of scalars → bullets
  if (Array.isArray(v) && v.every(_isScalar)) {
    return (
      <div className="py-1.5 border-b border-hairline last:border-b-0">
        <div className="font-mono text-[10px] uppercase tracking-tagged text-ink-mute mb-1">{label}</div>
        <ul className="space-y-1">
          {v.map((it, i) => (
            <li key={i} className="flex gap-1.5 text-[11.5px] text-ink-soft leading-snug">
              <span className="text-ink-mute shrink-0">·</span>
              <span>{_fmtScalar(it)}</span>
            </li>
          ))}
        </ul>
      </div>
    );
  }
  // list of objects → indented sub-blocks
  if (Array.isArray(v)) {
    return (
      <div className="py-1.5 border-b border-hairline last:border-b-0">
        <div className="font-mono text-[10px] uppercase tracking-tagged text-ink-mute mb-1.5">
          {label} · {v.length}
        </div>
        <div className="space-y-2.5">
          {v.map((item, i) => (
            <div key={i} className="pl-2.5 border-l-2 border-graphite">
              {_specEntries(item as Record<string, unknown>).map(([ck, cv]) => (
                <SpecEntry key={ck} k={ck} v={cv} />
              ))}
            </div>
          ))}
        </div>
      </div>
    );
  }
  // nested object → indented sub-block
  return (
    <div className="py-1.5 border-b border-hairline last:border-b-0">
      <div className="font-mono text-[10px] uppercase tracking-tagged text-ink-soft mb-1">{label}</div>
      <div className="pl-2.5 border-l border-hairline">
        {_specEntries(v as Record<string, unknown>).map(([ck, cv]) => (
          <SpecEntry key={ck} k={ck} v={cv} />
        ))}
      </div>
    </div>
  );
}

function SpecTree({ data }: { data?: Record<string, unknown> }) {
  const entries = _specEntries(data);
  if (entries.length === 0)
    return <p className="text-[11.5px] text-ink-mute italic">No data on this version.</p>;
  return (
    <div className="border-t border-hairline">
      {entries.map(([k, v]) => (
        <SpecEntry key={k} k={k} v={v} />
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
 * "Run full LLM review" — an on-demand live LLM call (~3-8s) that adds
 * confidence / impact / effort labels and catalogue-grounded
 * alternatives on top of the deterministic items. */
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

  // Second-speed advisor (LLM-authored, ~3-8s). Triggered on demand by
  // the "Run full LLM review" button; not auto-fired since it costs a
  // live LLM round-trip per click.
  const [fullReview, setFullReview] = useState<
    import("@/lib/types").FullRecommendationsReport | null
  >(null);
  const [fullLoading, setFullLoading] = useState(false);
  const [fullErr, setFullErr] = useState<string | null>(null);

  // Reset the full review when the project / version changes so stale
  // LLM output from a prior version never lingers on screen.
  useEffect(() => {
    setFullReview(null);
    setFullErr(null);
  }, [activeProjectId, latestVersion]);

  const runFullReview = () => {
    if (!activeProjectId) return;
    setFullLoading(true);
    setFullErr(null);
    designApi
      .fullReview(token, activeProjectId, latestVersion ?? undefined)
      .then((res) => setFullReview(res.report))
      .catch((e) =>
        setFullErr(
          e instanceof Error ? e.message : "Full LLM review is unavailable",
        ),
      )
      .finally(() => setFullLoading(false));
  };

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
          ← /projects/{"{id}"}/validate
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

      <div className="pt-2 border-t border-hairline space-y-3">
        <button
          type="button"
          onClick={runFullReview}
          disabled={fullLoading}
          className="w-full text-left px-3 py-2 border border-hairline rounded-md text-[12.5px] text-ink-deep hover:bg-paper-soft hover:border-pencil transition-colors disabled:opacity-60 disabled:cursor-wait"
          title="Live LLM advisor — confidence, impact and effort labels (~3-8s)"
        >
          {fullLoading ? "Running full LLM review…" : "Run full LLM review"}
          <span className="ml-2 font-mono text-[10px] uppercase tracking-tagged text-pencil">
            LLM
          </span>
        </button>

        {fullErr && (
          <p className="text-[12px] text-brick">{fullErr}</p>
        )}

        {fullReview && <FullReviewPanel report={fullReview} />}
      </div>
    </div>
  );
}

/* FullReviewPanel — renders the LLM-authored (second-speed) advisor
 * output: each recommendation with its confidence / impact / effort
 * labels, catalogue-grounded alternatives, plus the model's stated
 * assumptions. Ordered by the model's own ranking when present. */
function FullReviewPanel({
  report,
}: {
  report: import("@/lib/types").FullRecommendationsReport;
}) {
  const block = report.recommendations;
  const items = block?.recommendations ?? [];
  const ranking = block?.ranking ?? [];
  const assumptions = block?.assumptions ?? [];

  // Apply the model's ranking (indices into items) when valid; fall back
  // to source order otherwise.
  const ordered =
    ranking.length === items.length
      ? ranking
          .filter((i) => i >= 0 && i < items.length)
          .map((i) => items[i])
      : items;

  return (
    <div className="space-y-3 rounded-md border border-hairline bg-paper-soft/40 p-3">
      <div className="flex items-baseline justify-between">
        <SectionTag>Full LLM review</SectionTag>
        <span className="font-mono text-[10px] text-ink-mute lowercase">
          {report.model}
        </span>
      </div>

      {ordered.length === 0 ? (
        <p className="text-[12.5px] text-ink-soft italic">
          The advisor returned no recommendations for this version.
        </p>
      ) : (
        <div className="space-y-3">
          {ordered.map((item, i) => (
            <FullRecCard key={`${i}-${item.title}`} item={item} />
          ))}
        </div>
      )}

      {assumptions.length > 0 && (
        <div className="pt-2 border-t border-hairline">
          <p className="font-mono text-[10px] uppercase tracking-tagged text-ink-mute mb-1">
            Assumptions
          </p>
          <ul className="list-disc list-inside space-y-0.5">
            {assumptions.map((a, i) => (
              <li key={`${i}-${a}`} className="text-[11.5px] text-ink-soft">
                {a}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function FullRecCard({
  item,
}: {
  item: import("@/lib/types").FullRecItem;
}) {
  return (
    <div className="border-b border-hairline last:border-b-0 pb-2.5 last:pb-0">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[12.5px] text-ink-deep font-medium">
          {item.title}
        </span>
        <span className="font-mono text-[10px] uppercase tracking-tagged text-ink-mute shrink-0">
          {item.category}
        </span>
      </div>
      {item.detail && (
        <p className="mt-1 text-[12px] text-ink-soft leading-relaxed">
          {item.detail}
        </p>
      )}
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        <LabelPill label="confidence" value={item.confidence} />
        <LabelPill label="impact" value={item.impact} />
        <LabelPill label="effort" value={item.effort} />
      </div>
      {item.alternatives && item.alternatives.length > 0 && (
        <p className="mt-1.5 text-[11.5px] text-ink-mute">
          Alternatives:{" "}
          {item.alternatives
            .map((a) => a.name)
            .filter(Boolean)
            .join(", ")}
        </p>
      )}
    </div>
  );
}

function LabelPill({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <span className="inline-flex items-baseline gap-1 rounded border border-hairline px-1.5 py-0.5 font-mono text-[9.5px] uppercase tracking-tagged">
      <span className="text-ink-mute">{label}</span>
      <span className="text-ink-deep">{value}</span>
    </span>
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
      body: "Switcher for 5 working drawings (plan · elevation · section · isometric · detail) and 8 diagrams (concept · form · massing · volumetric · process · solid-vs-void · spatial organism · hierarchy). Click a thumbnail → it swaps into the canvas.",
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
        // The render came back as a flat image with no structured design
        // graph, so there are no real objects, materials, or BOQ rows to
        // cite. We surface only what we actually know (Dim + Theme) and an
        // honest note — never fabricated material prices. Real, sourced
        // figures live in the Specs + Cost tabs once a graph exists.
        <div className="mt-4 space-y-5">
          <div>
            <h4 className="font-mono text-[10px] tracking-[0.14em] uppercase text-ink-mute mb-2">
              Meta
            </h4>
            <div className="border-t border-hairline">
              <CitedKV k="Dim" v={dim.toUpperCase()} />
              <CitedKV k="Theme" v={theme} />
            </div>
          </div>
          <div>
            <h4 className="font-mono text-[10px] tracking-[0.14em] uppercase text-ink-mute mb-2">
              Materials &amp; BOQ
            </h4>
            <div className="border-t border-hairline pt-3">
              <p className="text-[12px] text-ink-soft leading-relaxed italic">
                This render came back image-only — no structured design
                graph, so there are no objects or sourced material prices
                to show yet. Re-prompt or regenerate to engage the spec and
                cost engines; figures will populate the Specs and Cost tabs
                with their sources inline.
              </p>
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
        placeholder="Change material, finish, colour, or size…"
        rows={2}
        disabled={isEditing || !canEdit}
        className="w-full resize-none outline-none bg-paper border border-hairline focus:border-graphite rounded-sm py-1.5 px-2 text-[12px] text-ink leading-relaxed font-mono placeholder:text-ink-mute"
      />
      {/* Precise placement is a direct manipulation, not a prompt — point the
          architect at the plan editor rather than asking the LLM to guess new
          coordinates from prose. */}
      <p className="mt-1.5 text-[10px] text-ink-mute leading-snug">
        To move or resize by hand, drag it in the{" "}
        <span className="font-medium text-ink-soft">Plan</span> view.
      </p>
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
      className="w-full text-left border-t border-hairline bg-paper-deep px-6 py-2 flex items-center justify-between cursor-pointer hover:bg-paper-edge transition-colors"
      onClick={onOpen}
    >
      <span className="font-mono text-[11px] tracking-[0.12em] uppercase text-ink-soft">
        Terminal · cost · problems · log · citations
      </span>
      <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-soft">
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
  codeCompliance,
  generation,
  onClose,
}: {
  tab: TerminalTab;
  setTab: (t: TerminalTab) => void;
  hasDesign: boolean;
  validation?: import("@/lib/types").ValidationReport;
  mepCost?: import("@/lib/types").MepCostEstimate;
  codeCompliance?: import("@/lib/types").CodeComplianceEntry[];
  generation?: import("@/lib/types").ImageGeneration | null;
  onClose: () => void;
}) {
  // BRD §11.3 — Problems tab count reflects errors + warnings (suggestions
  // are advisory only and don't drive the badge). 0 when there's no design
  // yet or when the validator hasn't run.
  const problemCount =
    (validation?.errors?.length ?? 0) + (validation?.warnings?.length ?? 0);

  // Citations badge — every datum the design draws on that carries a
  // source: validation issues with a source_section/reference + code
  // compliance rows + the MEP cost jurisdiction band.
  const citationCount = countCitations(validation, codeCompliance, mepCost);

  const tabs: { id: TerminalTab; label: string; count?: number }[] = [
    { id: "cost", label: "Cost" },
    { id: "problems", label: "Problems", count: problemCount },
    { id: "genlog", label: "Generation Log" },
    { id: "citations", label: "Citations", count: citationCount },
  ];

  return (
    <div className="border-t border-hairline bg-paper-soft h-72 flex flex-col">
      <div className="border-b border-hairline pl-2 pr-1 flex items-center justify-between">
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
                    ? "text-ink-deep border-pencil"
                    : "text-ink-soft hover:text-ink border-transparent"
                }`}
              >
                {t.label}
                {t.count !== undefined ? (
                  <span className="ml-1.5 text-ink-mute normal-case tracking-normal">
                    ({t.count})
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-1">
          <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute px-2">
            live · streaming
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close terminal"
            title="Close terminal"
            className="text-ink-mute hover:text-ink-deep hover:bg-paper-edge rounded p-1.5 transition-colors"
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
          <CostStream
            hasDesign={hasDesign}
            estimate={generation?.estimate}
            mepCost={mepCost}
          />
        ) : tab === "problems" ? (
          <ProblemsList hasDesign={hasDesign} validation={validation} />
        ) : tab === "genlog" ? (
          <GenerationLog hasDesign={hasDesign} generation={generation} />
        ) : (
          <CitationsList
            hasDesign={hasDesign}
            validation={validation}
            codeCompliance={codeCompliance}
            mepCost={mepCost}
          />
        )}
      </div>
    </div>
  );
}

// ── Citations + Generation Log helpers ────────────────────────────────

type CitationRow = {
  label: string;
  detail: string;
  source: string;
  kind: "code" | "validation" | "cost";
};

/* Aggregate every cited datum the current design draws on. Pulls from
   three already-wired sources: validation issues (NBC / code clauses),
   the code-compliance summary, and the MEP cost jurisdiction band. No
   new backend call — this is a read over data the generation response
   already carries. */
function collectCitations(
  validation?: import("@/lib/types").ValidationReport,
  codeCompliance?: import("@/lib/types").CodeComplianceEntry[],
  mepCost?: import("@/lib/types").MepCostEstimate,
): CitationRow[] {
  const rows: CitationRow[] = [];

  for (const entry of codeCompliance ?? []) {
    const src = [entry.code, entry.source_section, entry.jurisdiction]
      .filter(Boolean)
      .join(" · ");
    if (!src) continue;
    rows.push({
      label: entry.label,
      detail: `${entry.value} (target ${entry.target})`,
      source: src,
      kind: "code",
    });
  }

  const issues = [
    ...(validation?.errors ?? []),
    ...(validation?.warnings ?? []),
    ...(validation?.suggestions ?? []),
  ];
  for (const issue of issues) {
    const src = [issue.reference, issue.source_section, issue.jurisdiction]
      .filter(Boolean)
      .join(" · ");
    if (!src) continue;
    rows.push({
      label: issue.code || issue.path || "Rule",
      detail: issue.message,
      source: src,
      kind: "validation",
    });
  }

  if (mepCost?.jurisdiction) {
    rows.push({
      label: "MEP cost bands",
      detail: `${mepCost.systems?.length ?? 0} systems · ${mepCost.area_m2} m²`,
      source: [mepCost.jurisdiction, mepCost.region].filter(Boolean).join(" · "),
      kind: "cost",
    });
  }

  return rows;
}

function countCitations(
  validation?: import("@/lib/types").ValidationReport,
  codeCompliance?: import("@/lib/types").CodeComplianceEntry[],
  mepCost?: import("@/lib/types").MepCostEstimate,
): number {
  return collectCitations(validation, codeCompliance, mepCost).length;
}

function CitationsList({
  hasDesign,
  validation,
  codeCompliance,
  mepCost,
}: {
  hasDesign: boolean;
  validation?: import("@/lib/types").ValidationReport;
  codeCompliance?: import("@/lib/types").CodeComplianceEntry[];
  mepCost?: import("@/lib/types").MepCostEstimate;
}) {
  if (!hasDesign) {
    return (
      <div className="font-mono text-[12px] text-ink-mute leading-relaxed">
        No citations yet.
        <br />
        Generate a design — every code clause, cost band, and validated
        datum it draws on lists here with its source.
      </div>
    );
  }

  const rows = collectCitations(validation, codeCompliance, mepCost);
  if (rows.length === 0) {
    return (
      <div className="font-mono text-[12px] text-ink-mute leading-relaxed">
        This generation carries no source-tagged data yet.
        <br />
        Code-backed validation runs on designs with resolvable dimensions.
      </div>
    );
  }

  const kindLabel: Record<CitationRow["kind"], string> = {
    code: "CODE",
    validation: "RULE",
    cost: "COST",
  };

  return (
    <div className="space-y-2">
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute mb-1">
        {rows.length} cited {rows.length === 1 ? "source" : "sources"} · every datum is traceable
      </div>
      {rows.map((r, i) => (
        <div
          key={`${r.kind}-${i}`}
          className="border-l-2 border-hairline pl-3 py-1"
        >
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-pencil shrink-0">
              {kindLabel[r.kind]}
            </span>
            <span className="font-mono text-[12px] text-ink-deep">{r.label}</span>
          </div>
          <div className="font-mono text-[11px] text-ink leading-snug">{r.detail}</div>
          <div className="font-mono text-[10px] text-ink-mute mt-0.5">↳ {r.source}</div>
        </div>
      ))}
    </div>
  );
}

/* GenerationLog — a deterministic record of what the latest generation
   produced. Generate is a single request (not a streaming agent feed),
   so this honestly summarises the completed pipeline steps from the
   response the design already carries, rather than faking live tokens. */
function GenerationLog({
  hasDesign,
  generation,
}: {
  hasDesign: boolean;
  generation?: import("@/lib/types").ImageGeneration | null;
}) {
  if (!hasDesign || !generation) {
    return (
      <div className="font-mono text-[12px] text-ink-mute leading-relaxed">
        Generation log idle.
        <br />
        Each generate / edit / theme-switch records its pipeline steps here.
      </div>
    );
  }

  const graph = generation.graphData as
    | {
        objects?: unknown[];
        room?: { type?: string; dimensions?: { length?: number; width?: number; height?: number } };
        style?: { primary?: string };
      }
    | undefined;
  const objectCount = graph?.objects?.length ?? 0;
  const room = graph?.room;
  const dims = room?.dimensions;
  const dimLabel =
    dims?.length && dims?.width
      ? `${dims.length}×${dims.width}${dims.height ? `×${dims.height}` : ""} m`
      : "—";
  const validation = generation.validation;
  const errs = validation?.errors?.length ?? 0;
  const warns = validation?.warnings?.length ?? 0;
  const mep = generation.mepCostEstimate;

  const steps: { ok: boolean; label: string }[] = [
    { ok: true, label: `Design graph resolved — ${objectCount} object${objectCount === 1 ? "" : "s"}, room ${room?.type ?? "—"} ${dimLabel}` },
    { ok: true, label: `Theme applied — ${generation.theme ?? graph?.style?.primary ?? "—"}` },
    { ok: !!generation.url, label: generation.url ? "Render produced" : "Render skipped (no image)" },
    { ok: !!generation.estimate, label: generation.estimate ? "Cost estimate computed" : "Cost estimate unavailable" },
    { ok: !!mep, label: mep ? `MEP cost rolled up — ${mep.systems?.length ?? 0} systems over ${mep.area_m2} m²` : "MEP cost skipped (no room area)" },
    {
      ok: !validation || validation.ok,
      label: validation
        ? `Validation pass — ${errs} error${errs === 1 ? "" : "s"}, ${warns} warning${warns === 1 ? "" : "s"}`
        : "Validation not run",
    },
  ];

  return (
    <div className="space-y-2">
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute mb-1">
        Version {generation.version ?? "—"} ·{" "}
        {new Date(generation.timestamp).toLocaleString()}
      </div>
      {steps.map((s, i) => (
        <div key={i} className="flex items-baseline gap-2 font-mono text-[12px]">
          <span className={s.ok ? "text-pencil" : "text-ink-mute"}>
            {s.ok ? "✓" : "·"}
          </span>
          <span className={s.ok ? "text-ink" : "text-ink-mute"}>{s.label}</span>
        </div>
      ))}
      {generation.prompt ? (
        <div className="border-t border-hairline pt-2 mt-2">
          <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute mb-1">
            Prompt
          </div>
          <div className="font-mono text-[11px] text-ink leading-snug whitespace-pre-wrap">
            {generation.prompt}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function CostStream({
  hasDesign,
  estimate,
  mepCost,
}: {
  hasDesign: boolean;
  estimate?: unknown;
  mepCost?: import("@/lib/types").MepCostEstimate;
}) {
  if (!hasDesign) {
    return (
      <div className="font-mono text-[12px] text-ink-mute leading-relaxed">
        Cost stream idle.
        <br />
        Generate a design to see ₹ low / base / high tick live.
      </div>
    );
  }

  // Mirror the sidebar Cost tab EXACTLY so the two panels never contradict:
  // same source (this version's estimate), same "computed" gate, same empty
  // state. This stream used to show hardcoded placeholder figures + line items
  // regardless of the design, which is why it disagreed with the rail.
  const est = estimate as EstimateShape | undefined;
  const estFinalTotal = est?.pricing_adjustments?.final_total ?? 0;
  const hasEstimate = !!est && est.status === "computed" && estFinalTotal > 0;

  if (!hasEstimate && !mepCost) {
    return (
      <div className="font-mono text-[12px] text-ink-mute leading-relaxed">
        This version didn&apos;t produce a cost estimate.
        <br />
        Re-prompt or regenerate to engage the cost engine.
      </div>
    );
  }

  const d = est?.display;
  const sym = d?.currency_symbol || "₹";
  const locale = d?.locale || "en-IN";
  const fmt = (n?: number) =>
    n == null ? "—" : `${sym}${Math.round(n).toLocaleString(locale)}`;
  const base = d?.final_total ?? estFinalTotal;
  const low = est?.total_low;
  const high = est?.total_high;
  const hasRange = low != null && high != null && high > 0;
  const cats = est?.estimate || {};
  const catRows = (
    [
      ["Materials", cats.materials?.total_cost],
      ["Furniture", cats.furniture?.total_cost],
      ["Labour", cats.labor?.total_cost],
      ["Services", cats.services?.total_cost],
      ["Misc", cats.misc?.total_cost],
    ] as [string, number | undefined][]
  ).filter((r): r is [string, number] => (r[1] ?? 0) > 0);

  return (
    <div className="space-y-4">
      {hasEstimate ? (
        // Total + range, mirroring the sidebar. NOT a Low/Base/High triptych:
        // the engine's final_total (incl. margin/overhead) can sit above its
        // low→high estimate band, which reads as "High < Base" in a triptych.
        <div className="flex flex-wrap items-end gap-x-8 gap-y-1">
          <CostFigure label="Total" value={fmt(base)} highlight />
          {hasRange ? (
            <div className="pb-1.5 font-mono text-[11px] text-ink-mute tnum">
              range {fmt(low)}
              <span className="mx-1 text-ink-mute/60">→</span>
              {fmt(high)}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* BRD §1B — MEP systems cost block. DB-backed; rolls up HVAC,
          electrical, plumbing, fire-fighting at ₹/m² bands for the
          generated room area. Hidden until the validator emits one
          (no usable room area → no block). */}
      {mepCost ? <MepCostBlock mepCost={mepCost} /> : null}
      {hasEstimate && catRows.length > 0 ? (
        <div className="border-t border-hairline pt-3">
          <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute mb-2">
            By category
          </div>
          <div className="space-y-1 font-mono text-[12px] text-ink">
            {catRows.map(([label, val]) => (
              <CostLine key={label} k={label} v={fmt(val)} />
            ))}
          </div>
        </div>
      ) : null}
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
    <div className="border-t border-hairline pt-3">
      <div className="flex items-baseline justify-between mb-2">
        <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute">
          MEP systems · per ₹/m² band
        </div>
        <div className="font-mono text-[10px] tracking-tight text-ink-soft">
          area {mepCost.area_m2.toFixed(1)} m² · {mepCost.jurisdiction}
        </div>
      </div>

      <div className="space-y-1 font-mono text-[12px] text-ink">
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

      <div className="border-t border-hairline mt-2 pt-2 flex items-baseline justify-between">
        <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-soft">
          MEP total
        </div>
        <div className="font-mono text-[13px] text-ink-deep tnum">
          {fmt(totalLow)} <span className="text-ink-mute px-1">–</span>{" "}
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
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute">
        {label}
      </div>
      <div
        className={`mt-1 font-mono tnum tracking-[-0.01em] ${
          highlight
            ? "text-ink-deep text-[1.625rem] font-medium"
            : "text-ink text-[1.375rem] font-normal"
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
    <div className="group/line relative flex items-baseline justify-between border-b border-dashed border-hairline py-1">
      <span className="text-ink-soft">{k}</span>
      <div className="flex items-baseline gap-2">
        <span className="text-ink-deep tnum">{v}</span>
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
        className="pointer-events-none invisible opacity-0 group-hover/line:visible group-hover/line:opacity-100 absolute right-0 bottom-full mb-2 z-20 whitespace-nowrap bg-paper-deep border border-hairline px-2.5 py-1.5 rounded-sm text-[10px] uppercase tracking-[0.1em] text-ink transition-opacity duration-150 font-mono"
      >
        <span className="text-pencil-soft">src</span>
        <span className="ml-2">{src}</span>
        {srcWhen ? (
          <span className="ml-2 text-ink-mute">· {srcWhen}</span>
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
      <div className="font-mono text-[12px] text-ink space-y-1.5">
        <div className="text-ink-mute">No problems detected.</div>
        <div className="text-ink-mute">
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
      <div className="font-mono text-[12px] text-ink space-y-1.5">
        <div className="pl-3 border-l-2 border-olive">
          <span className="text-olive">[OK]</span>
          <span className="ml-2 text-ink">
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
      <div className="font-mono text-[12px] text-ink space-y-1.5">
        <div className="pl-3 border-l-2 border-olive">
          <span className="text-olive">[OK]</span>
          <span className="ml-2 text-ink">{validation.summary}</span>
        </div>
        <div className="text-ink-mute pl-3">
          All rooms, ergonomics, and clearances within standard.
        </div>
      </div>
    );
  }

  return (
    <div className="font-mono text-[12px] text-ink space-y-3">
      <div className="text-ink-soft">{validation.summary}</div>

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
      <div className="text-ink-soft uppercase tracking-wider text-[10px] mb-1">
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
              <span className="text-ink-soft">{issue.code}</span>{" "}
              <span className="text-ink">{issue.message}</span>
            </div>
            <div className="text-ink-mute text-[10.5px] pl-1">
              {issue.path}
              {issue.source_section && (
                <span>
                  {" · cite: "}
                  <span className="text-pencil">{issue.source_section}</span>
                  {issue.jurisdiction && (
                    <span className="text-ink-mute"> ({issue.jurisdiction})</span>
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
