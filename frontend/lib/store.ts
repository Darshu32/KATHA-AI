/**
 * Zustand stores — global state for auth and chat.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  projectTypes as projectTypesApi,
  themes as themesApi,
  type ProjectTypeDef,
  type ThemeDef,
} from "./api-client";
import type {
  Message,
  Conversation,
  ChatMode,
  WorkspaceId,
  ArchTheme,
  DrawingType,
  ImageRatio,
  ImageQuality,
  CameraMode,
  LightingMode,
  ImageGeneration,
  GeneratedImage,
  DesignGraph,
  DesignObject,
  Vec3,
  NoteBlock,
  NoteSection,
  Notebook,
  ProjectType,
  ConvBrief,
  ConvBriefStatus,
} from "./types";

// ── Auth Store ──────────────────────────────────────────────────────────────

interface AuthState {
  token: string | null;
  user: { id: string; email: string; displayName: string } | null;
  setAuth: (token: string, user: AuthState["user"]) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setAuth: (token, user) => set({ token, user }),
      logout: () => set({ token: null, user: null }),
    }),
    { name: "katha-auth" },
  ),
);

// ── Chat Store ─────────────────────────────────────────────────────────────

interface ChatState {
  conversations: Conversation[];
  activeConversationId: string | null;
  isStreaming: boolean;
  sidebarOpen: boolean;
  chatMode: ChatMode;

  createConversation: () => string;
  deleteConversation: (id: string) => void;
  setActiveConversation: (id: string | null) => void;
  addMessage: (conversationId: string, message: Message) => void;
  updateLastMessage: (conversationId: string, content: string) => void;
  updateLastMessageFull: (conversationId: string, updates: Partial<Message>) => void;
  appendToLastMessage: (conversationId: string, token: string) => void;
  setStreaming: (v: boolean) => void;
  toggleSidebar: () => void;
  setSidebarOpen: (v: boolean) => void;
  setChatMode: (mode: ChatMode) => void;

  // BRD §1A — merge a freshly-emitted brief snapshot into the active
  // conversation. ``brief`` is deep-merged (section by section); the
  // status and missing-fields arrays are replaced wholesale because
  // they describe the current state, not an accumulation.
  mergeBrief: (
    conversationId: string,
    payload: {
      brief: ConvBrief | null;
      status: ConvBriefStatus | null;
      missing: string[];
    },
  ) => void;
  resetBrief: (conversationId: string) => void;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      conversations: [],
      activeConversationId: null,
      isStreaming: false,
      sidebarOpen: true,
      chatMode: "auto" as ChatMode,

      createConversation: () => {
        const id = crypto.randomUUID();
        const now = new Date().toISOString();
        // Auto-bind to the design workspace's active project so the
        // sidebar can show a project caption under the title. Snapshot
        // both id and name; if the user later renames the project,
        // the caption goes briefly stale until the next refresh —
        // acceptable for a prototype.
        const imgState = useImageGenStore.getState();
        const conversation: Conversation = {
          id,
          title: "New conversation",
          messages: [],
          createdAt: now,
          updatedAt: now,
          projectId: imgState.activeProjectId ?? undefined,
          projectName: imgState.activeProjectName ?? undefined,
        };
        set((state) => ({
          conversations: [conversation, ...state.conversations],
          activeConversationId: id,
        }));
        return id;
      },

      deleteConversation: (id) =>
        set((state) => {
          const filtered = state.conversations.filter((c) => c.id !== id);
          return {
            conversations: filtered,
            activeConversationId:
              state.activeConversationId === id
                ? filtered[0]?.id ?? null
                : state.activeConversationId,
          };
        }),

      setActiveConversation: (id) => set({ activeConversationId: id }),

      addMessage: (conversationId, message) =>
        set((state) => ({
          conversations: state.conversations.map((c) => {
            if (c.id !== conversationId) return c;
            const messages = [...c.messages, message];
            const title =
              c.title === "New conversation" && message.role === "user"
                ? message.content.slice(0, 60) + (message.content.length > 60 ? "..." : "")
                : c.title;
            return { ...c, messages, title, updatedAt: new Date().toISOString() };
          }),
        })),

      updateLastMessage: (conversationId, content) =>
        set((state) => ({
          conversations: state.conversations.map((c) => {
            if (c.id !== conversationId) return c;
            const messages = [...c.messages];
            if (messages.length > 0) {
              messages[messages.length - 1] = {
                ...messages[messages.length - 1],
                content,
              };
            }
            return { ...c, messages };
          }),
        })),

      updateLastMessageFull: (conversationId, updates) =>
        set((state) => ({
          conversations: state.conversations.map((c) => {
            if (c.id !== conversationId) return c;
            const messages = [...c.messages];
            if (messages.length > 0) {
              messages[messages.length - 1] = {
                ...messages[messages.length - 1],
                ...updates,
              };
            }
            return { ...c, messages };
          }),
        })),

      appendToLastMessage: (conversationId, token) =>
        set((state) => ({
          conversations: state.conversations.map((c) => {
            if (c.id !== conversationId) return c;
            const messages = [...c.messages];
            if (messages.length > 0) {
              const last = messages[messages.length - 1];
              messages[messages.length - 1] = {
                ...last,
                content: last.content + token,
              };
            }
            return { ...c, messages };
          }),
        })),

      setStreaming: (v) => set({ isStreaming: v }),
      toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
      setSidebarOpen: (v) => set({ sidebarOpen: v }),
      setChatMode: (mode) => set({ chatMode: mode }),

      mergeBrief: (conversationId, { brief, status, missing }) =>
        set((state) => ({
          conversations: state.conversations.map((c) => {
            if (c.id !== conversationId) return c;
            // Deep-merge brief sections. ``null`` from the LLM means
            // "this turn was a knowledge question, don't touch the
            // brief". A non-null brief deep-merges each section so
            // later turns add detail without erasing earlier captures.
            let nextBrief = c.brief;
            if (brief) {
              nextBrief = {
                ...(c.brief ?? {}),
                ...Object.fromEntries(
                  (
                    ["project_type", "theme", "space", "requirements", "regulatory"] as const
                  ).map((section) => {
                    const incoming = (brief as Record<string, unknown>)[section];
                    if (!incoming || typeof incoming !== "object") return [section, c.brief?.[section]];
                    return [
                      section,
                      { ...((c.brief?.[section] as object) ?? {}), ...(incoming as object) },
                    ];
                  }),
                ),
                notes: brief.notes ?? c.brief?.notes,
              };
            }
            return {
              ...c,
              brief: nextBrief,
              briefStatus: status ?? c.briefStatus,
              briefMissing: brief ? missing : c.briefMissing,
              updatedAt: new Date().toISOString(),
            };
          }),
        })),

      resetBrief: (conversationId) =>
        set((state) => ({
          conversations: state.conversations.map((c) =>
            c.id === conversationId
              ? { ...c, brief: undefined, briefStatus: undefined, briefMissing: undefined }
              : c,
          ),
        })),
    }),
    {
      name: "katha-chat",
      partialize: (state) => ({
        conversations: state.conversations,
        activeConversationId: state.activeConversationId,
        sidebarOpen: state.sidebarOpen,
        chatMode: state.chatMode,
      }),
    },
  ),
);

// ── Workspace Store ────────────────────────────────────────────────────────

interface WorkspaceState {
  activeWorkspace: WorkspaceId;
  setActiveWorkspace: (ws: WorkspaceId) => void;
}

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set) => ({
      activeWorkspace: "knowledge-chat",
      setActiveWorkspace: (ws) => set({ activeWorkspace: ws }),
    }),
    { name: "katha-workspace" },
  ),
);

// ── Image Generation Store ─────────────────────────────────────────────────

/* Capitalise the first letter — used for the auto-generated project
   name derived from a brief (e.g. "mid century modern office in
   Mumbai" → "Mid century modern office in Mumbai"). */
function cap(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

/* Convert a canonical BRD §1A brief (5 sections) into a single
   paragraph the design pipeline can use as the first generation
   prompt. We deliberately phrase it like a designer's brief — a
   compact opening sentence with type / theme / location / dims,
   followed by functional needs, narrative, budget, and a climate
   trailing note. Anything missing is silently skipped so the prompt
   never reads "in undefined". */
function briefToStarterPrompt(parts: {
  projectType?: string;
  subType?: string;
  scale?: string;
  theme?: string;
  space?: Record<string, unknown>;
  requirements?: Record<string, unknown>;
  regulatory?: Record<string, unknown>;
}): string {
  const sentences: string[] = [];

  const themeStr = parts.theme ? parts.theme.replace(/_/g, " ") : "";
  const opener = [parts.scale, themeStr, parts.subType, parts.projectType]
    .filter((x) => typeof x === "string" && x.trim())
    .join(" ");

  const dims = (parts.space?.dimensions as Record<string, unknown> | undefined) ?? undefined;
  const dimStr =
    dims && dims.length && dims.width
      ? `, ${dims.length}×${dims.width}${dims.unit ? ` ${dims.unit}` : ""}`
      : "";
  const city = typeof parts.regulatory?.city === "string" ? parts.regulatory.city : "";
  const locationStr = city ? ` in ${city}` : "";

  if (opener) sentences.push(`A ${opener}${locationStr}${dimStr}.`);
  else if (dimStr || locationStr) sentences.push(`A design${locationStr}${dimStr}.`);

  // Functional needs — collapse the array into a clause.
  const needs = parts.requirements?.functional_needs;
  if (Array.isArray(needs) && needs.length > 0) {
    sentences.push(needs.map((n) => String(n).trim()).filter(Boolean).join(", ") + ".");
  }

  // Aesthetic preferences — same treatment.
  const aesthetic = parts.requirements?.aesthetic_preferences;
  if (Array.isArray(aesthetic) && aesthetic.length > 0) {
    sentences.push(aesthetic.map((a) => String(a).trim()).filter(Boolean).join(", ") + ".");
  }

  // Free-form narrative is appended as-is.
  const narrative = parts.requirements?.narrative;
  if (typeof narrative === "string" && narrative.trim()) {
    sentences.push(narrative.trim().replace(/\.$/, "") + ".");
  }

  // Budget — only if numeric and > 0. Use a thin currency prefix.
  const budget = parts.requirements?.budget;
  if (typeof budget === "number" && budget > 0) {
    const currency =
      typeof parts.requirements?.currency === "string"
        ? (parts.requirements.currency as string)
        : "INR";
    sentences.push(`Budget ~${currency} ${budget.toLocaleString()}.`);
  }

  // Climate trailing note — sometimes inferred from city, so it's a
  // useful signal even when the user didn't mention it.
  const climate = parts.regulatory?.climatic_zone;
  if (typeof climate === "string" && climate.trim()) {
    sentences.push(`Climate: ${climate.replace(/_/g, " ")}.`);
  }

  return sentences.join(" ").trim();
}

interface ImageGenState {
  prompt: string;
  negativePrompt: string;
  projectType: ProjectType;
  projectSubType: string;
  projectScale: string;
  // Market — drives currency + building-code jurisdiction on the project.
  region: string;
  theme: ArchTheme;
  drawingType: DrawingType;
  ratio: ImageRatio;
  quality: ImageQuality;
  styleEnhance: boolean;
  camera: CameraMode;
  lighting: LightingMode;
  generations: ImageGeneration[];
  isGenerating: boolean;
  rightSidebarOpen: boolean;
  terminalOpen: boolean;
  viewMode: "2d" | "3d";

  // ── Project pipeline (Pass 1 of edit loop) ────────────────────────
  // Active project id for the design workspace. Set on first
  // successful generation via POST /projects (created server-side)
  // and reused for subsequent generations + edits so they all land
  // as new versions of the same project.
  // ``activeProjectName`` is the snapshotted display name — kept here
  // so the chat sidebar can render a project caption on conversations
  // without round-tripping to `/projects/{id}`.
  activeProjectId: string | null;
  activeProjectVersion: number | null;
  activeProjectName: string | null;

  // ── BRD §3.6 — chat → image-gen handoff ──────────────────────────
  // When the user confirms a brief in the chat workspace, the notes
  // sidebar calls ``seedFromBrief``. That sets ``seededFromBriefId`` so
  // the design workspace can render a "seeded from brief" banner and
  // the user knows the prefilled values came from the chat (not their
  // previous design session). The banner clears via ``clearBriefSeed``
  // either explicitly (user dismisses) or implicitly (first new
  // generation in the design workspace).
  seededFromBriefId: string | null;

  setPrompt: (v: string) => void;
  setNegativePrompt: (v: string) => void;
  setProjectType: (v: ProjectType) => void;
  setProjectSubType: (v: string) => void;
  setProjectScale: (v: string) => void;
  setRegion: (v: string) => void;
  setTheme: (v: ArchTheme) => void;
  setDrawingType: (v: DrawingType) => void;
  setRatio: (v: ImageRatio) => void;
  setQuality: (v: ImageQuality) => void;
  setStyleEnhance: (v: boolean) => void;
  setCamera: (v: CameraMode) => void;
  setLighting: (v: LightingMode) => void;
  setIsGenerating: (v: boolean) => void;
  addGeneration: (gen: ImageGeneration) => void;
  /** Replace the entire gallery — used by the project picker when
   *  the architect opens an existing project so the gallery shows
   *  that project's latest version instead of in-session history. */
  replaceGenerations: (gens: ImageGeneration[]) => void;
  /** Clear the gallery — used when the architect creates a new
   *  project. Resets activeProjectId at the same time. */
  clearGenerations: () => void;
  setRightSidebarOpen: (v: boolean) => void;
  toggleTerminal: () => void;
  setViewMode: (v: "2d" | "3d") => void;
  setActiveProject: (
    projectId: string | null,
    version?: number | null,
    name?: string | null,
  ) => void;

  // BRD §3.6 — populate the design workspace from a canonical brief
  // returned by ``POST /brief/intake``. Maps the 5 sections onto the
  // store's seedable fields (projectType / theme / sub-type / scale)
  // and assembles a starter prompt from requirements + dimensions.
  // Stores ``brief_id`` so the workspace can show a banner attributing
  // the prefill to a specific chat brief.
  seedFromBrief: (briefId: string, brief: Record<string, unknown>) => void;
  clearBriefSeed: () => void;
}

export const useImageGenStore = create<ImageGenState>()(
  persist(
    (set) => ({
      prompt: "",
      negativePrompt: "",
      projectType: "residential",
      projectSubType: "",
      projectScale: "",
      region: "india",
      theme: "modern",
      drawingType: "3d-render",
      ratio: "16:9",
      quality: "standard",
      styleEnhance: true,
      camera: "front",
      lighting: "daylight",
      generations: [],
      isGenerating: false,
      rightSidebarOpen: false,
      terminalOpen: false,
      viewMode: "2d",
      activeProjectId: null,
      activeProjectVersion: null,
      activeProjectName: null,
      seededFromBriefId: null,

      setPrompt: (v) => set({ prompt: v }),
      setNegativePrompt: (v) => set({ negativePrompt: v }),
      setProjectType: (v) => set({ projectType: v }),
      setProjectSubType: (v) => set({ projectSubType: v }),
      setProjectScale: (v) => set({ projectScale: v }),
      setRegion: (v) => set({ region: v }),
      setTheme: (v) => set({ theme: v }),
      setDrawingType: (v) => set({ drawingType: v }),
      setRatio: (v) => set({ ratio: v }),
      setQuality: (v) => set({ quality: v }),
      setStyleEnhance: (v) => set({ styleEnhance: v }),
      setCamera: (v) => set({ camera: v }),
      setLighting: (v) => set({ lighting: v }),
      setIsGenerating: (v) => set({ isGenerating: v }),
      addGeneration: (gen) =>
        set((state) => ({ generations: [gen, ...state.generations] })),
      replaceGenerations: (gens) => set({ generations: gens }),
      clearGenerations: () =>
        set({
          generations: [],
          activeProjectId: null,
          activeProjectVersion: null,
          activeProjectName: null,
        }),
      setRightSidebarOpen: (v) => set({ rightSidebarOpen: v }),
      toggleTerminal: () => set((state) => ({ terminalOpen: !state.terminalOpen })),
      setViewMode: (v) => set({ viewMode: v }),
      setActiveProject: (projectId, version = null, name) =>
        set((state) => ({
          activeProjectId: projectId,
          activeProjectVersion: version,
          // Keep the previously-known name when the caller doesn't
          // pass one (e.g. version-bump after an edit), but clear it
          // whenever the project itself clears.
          activeProjectName:
            projectId === null
              ? null
              : name !== undefined
              ? name
              : state.activeProjectName,
        })),

      seedFromBrief: (briefId, brief) => {
        const projectTypeBlock = (brief.project_type as Record<string, unknown>) ?? {};
        const themeBlock = (brief.theme as Record<string, unknown>) ?? {};
        const spaceBlock = (brief.space as Record<string, unknown>) ?? {};
        const reqBlock = (brief.requirements as Record<string, unknown>) ?? {};
        const regBlock = (brief.regulatory as Record<string, unknown>) ?? {};

        // Project type slug — the brief's BRD enum values map 1:1 onto
        // our frontend ProjectType union (residential / office / …).
        // Unknown / custom values fall back to the current value rather
        // than fighting the defensive resync useEffect that picks the
        // first available def when our seed doesn't match the registry.
        const projectType =
          typeof projectTypeBlock.type === "string"
            ? (projectTypeBlock.type as ProjectType)
            : undefined;
        const subType =
          typeof projectTypeBlock.sub_type === "string"
            ? (projectTypeBlock.sub_type as string)
            : "";
        const scale =
          typeof projectTypeBlock.scale === "string"
            ? (projectTypeBlock.scale as string)
            : "";

        // Theme — same dynamic resync applies; we trust the brief here
        // and let the defensive effect downgrade to the first DB slug
        // if our value isn't registered.
        const theme =
          typeof themeBlock.theme === "string"
            ? (themeBlock.theme as ArchTheme)
            : undefined;

        // Assemble the starter prompt. Architects expect a single
        // paragraph that reads like a brief, not a JSON dump.
        const prompt = briefToStarterPrompt({
          projectType,
          subType,
          scale,
          theme,
          space: spaceBlock,
          requirements: reqBlock,
          regulatory: regBlock,
        });

        // Derive a display name for the project tab. Falls back to
        // "Untitled brief" when there's nothing distinctive to use.
        const city = typeof regBlock.city === "string" ? regBlock.city : "";
        const themeLabel =
          typeof themeBlock.theme === "string"
            ? (themeBlock.theme as string).replace(/_/g, " ")
            : "";
        const typeLabel = typeof projectTypeBlock.type === "string" ? projectTypeBlock.type as string : "";
        const namePieces = [themeLabel, typeLabel, city ? `in ${city}` : ""]
          .filter(Boolean)
          .join(" ");
        const projectName = namePieces ? cap(namePieces) : "Untitled brief";

        set((state) => ({
          prompt,
          projectType: projectType ?? state.projectType,
          projectSubType: subType,
          projectScale: scale,
          theme: theme ?? state.theme,
          // Don't carry the previous project's gallery into the new
          // brief — a fresh handoff is conceptually a new project.
          generations: [],
          activeProjectId: null,
          activeProjectVersion: null,
          activeProjectName: projectName,
          seededFromBriefId: briefId,
        }));
      },

      clearBriefSeed: () => set({ seededFromBriefId: null }),
    }),
    {
      name: "katha-image-gen",
      partialize: (state) => ({
        projectType: state.projectType,
        projectSubType: state.projectSubType,
        projectScale: state.projectScale,
        region: state.region,
        theme: state.theme,
        drawingType: state.drawingType,
        ratio: state.ratio,
        quality: state.quality,
        styleEnhance: state.styleEnhance,
        camera: state.camera,
        lighting: state.lighting,
        generations: state.generations,
        rightSidebarOpen: state.rightSidebarOpen,
        viewMode: state.viewMode,
        activeProjectId: state.activeProjectId,
        activeProjectVersion: state.activeProjectVersion,
        activeProjectName: state.activeProjectName,
        seededFromBriefId: state.seededFromBriefId,
      }),
    },
  ),
);

// ── Config Store (dynamic themes + project types from backend) ─────────────
//
// Fetched once per session by any component that needs the lists. The
// store owns the in-flight promise so concurrent consumers share one
// network request. Status flags let the UI render skeletons / fall back
// to a safe empty state when the backend is unreachable.

interface ConfigState {
  projectTypeDefs: ProjectTypeDef[];
  themes: ThemeDef[];
  loadingProjectTypes: boolean;
  loadingThemes: boolean;
  errorProjectTypes: string | null;
  errorThemes: string | null;
  loadProjectTypes: () => Promise<void>;
  loadThemes: () => Promise<void>;
  loadAll: () => Promise<void>;
}

let _projectTypesInflight: Promise<void> | null = null;
let _themesInflight: Promise<void> | null = null;

export const useConfigStore = create<ConfigState>((set, get) => ({
  projectTypeDefs: [],
  themes: [],
  loadingProjectTypes: false,
  loadingThemes: false,
  errorProjectTypes: null,
  errorThemes: null,

  loadProjectTypes: async () => {
    if (_projectTypesInflight) return _projectTypesInflight;
    if (get().projectTypeDefs.length > 0) return;
    set({ loadingProjectTypes: true, errorProjectTypes: null });
    _projectTypesInflight = (async () => {
      try {
        const res = await projectTypesApi.list();
        set({
          projectTypeDefs: res.project_types,
          loadingProjectTypes: false,
        });
      } catch (e) {
        set({
          loadingProjectTypes: false,
          errorProjectTypes:
            e instanceof Error ? e.message : "failed to load project types",
        });
      } finally {
        _projectTypesInflight = null;
      }
    })();
    return _projectTypesInflight;
  },

  loadThemes: async () => {
    if (_themesInflight) return _themesInflight;
    if (get().themes.length > 0) return;
    set({ loadingThemes: true, errorThemes: null });
    _themesInflight = (async () => {
      try {
        const res = await themesApi.list();
        set({ themes: res.themes, loadingThemes: false });
      } catch (e) {
        set({
          loadingThemes: false,
          errorThemes:
            e instanceof Error ? e.message : "failed to load themes",
        });
      } finally {
        _themesInflight = null;
      }
    })();
    return _themesInflight;
  },

  loadAll: async () => {
    await Promise.all([get().loadProjectTypes(), get().loadThemes()]);
  },
}));

// ── Design Store ──────────────────────────────────────────────────────────

interface LayerVisibility {
  furniture: boolean;
  dimensions: boolean;
  grid: boolean;
  wireframe: boolean;
  materials: boolean;
  lighting: boolean;
}

export interface BackendEstimate {
  status?: string;
  currency?: string;
  estimate?: Record<string, { total_cost: number; currency: string }>;
  breakdown?: Array<{ category: string; item: string; total: number; unit?: string; quantity?: number; unit_cost?: number }>;
  area?: { total_sqft: number; cost_per_sqft: number };
  region?: { city: string; price_index: number };
  pricing_adjustments?: { tax: number; tax_amount: number; discount: number; discount_amount: number; final_total: number };
  // Region-aware display block stamped by the generation pipeline.
  // Carries the project's currency + the converted total so non-Indian
  // markets render €/AED/$ instead of ₹.
  display?: {
    currency: string;
    currency_symbol: string;
    region: string;
    locale: string;
    final_total: number;
    cost_per_sqft: number;
  };
  confidence?: { score: number; level: string; factors?: string[] };
  line_items?: Array<{ item: string; total: number; total_low?: number; total_high?: number; category?: string }>;
  total_low?: number;
  total_high?: number;
  scenarios?: Array<{ name: string; total: number; currency?: string }>;
  assumptions?: string[];
  [k: string]: unknown;
}

interface DesignState {
  activeGraph: DesignGraph | null;
  activeProjectId: string;
  estimate: BackendEstimate | null;
  selectedObjectId: string | null;
  hoveredObjectId: string | null;
  isDragging: boolean;
  dragObjectId: string | null;
  undoStack: DesignGraph[];
  layerVisibility: LayerVisibility;
  isLoading: boolean;
  showDimensions: boolean;
  showGrid: boolean;
  snapToGrid: boolean;
  gridUnit: number;
  zoom: number;
  panOffset: { x: number; y: number };

  setActiveGraph: (g: DesignGraph) => void;
  setActiveProjectId: (id: string) => void;
  setEstimate: (e: BackendEstimate | null) => void;
  selectObject: (id: string | null) => void;
  hoverObject: (id: string | null) => void;
  updateObjectPosition: (id: string, pos: Vec3) => void;
  updateObjectDimensions: (id: string, dims: { length: number; width: number; height: number }) => void;
  updateObjectMaterial: (id: string, materialId: string, color: string) => void;
  setDragging: (dragging: boolean, objectId?: string | null) => void;
  pushUndo: () => void;
  undo: () => void;
  setLayerVisibility: (layer: keyof LayerVisibility, visible: boolean) => void;
  setLoading: (v: boolean) => void;
  setShowDimensions: (v: boolean) => void;
  setShowGrid: (v: boolean) => void;
  setSnapToGrid: (v: boolean) => void;
  setZoom: (v: number) => void;
  setPanOffset: (offset: { x: number; y: number }) => void;
}

export const useDesignStore = create<DesignState>()((set, get) => ({
  activeGraph: null,
  activeProjectId: "demo",
  estimate: null,
  selectedObjectId: null,
  hoveredObjectId: null,
  isDragging: false,
  dragObjectId: null,
  undoStack: [],
  layerVisibility: {
    furniture: true,
    dimensions: true,
    grid: true,
    wireframe: false,
    materials: true,
    lighting: true,
  },
  isLoading: false,
  showDimensions: true,
  showGrid: true,
  snapToGrid: true,
  gridUnit: 0.5,
  zoom: 1,
  panOffset: { x: 0, y: 0 },

  setActiveGraph: (g) => set({ activeGraph: g, selectedObjectId: null, undoStack: [] }),

  setActiveProjectId: (id) => set({ activeProjectId: id }),

  setEstimate: (e) => set({ estimate: e }),

  selectObject: (id) => set({ selectedObjectId: id }),

  hoverObject: (id) => set({ hoveredObjectId: id }),

  updateObjectPosition: (id, pos) =>
    set((state) => {
      if (!state.activeGraph) return state;
      const objects = state.activeGraph.objects.map((obj) =>
        obj.id === id ? { ...obj, position: pos } : obj,
      );
      return { activeGraph: { ...state.activeGraph, objects } };
    }),

  updateObjectDimensions: (id, dims) =>
    set((state) => {
      if (!state.activeGraph) return state;
      const objects = state.activeGraph.objects.map((obj) =>
        obj.id === id ? { ...obj, dimensions: dims } : obj,
      );
      return { activeGraph: { ...state.activeGraph, objects } };
    }),

  updateObjectMaterial: (id, materialId, color) =>
    set((state) => {
      if (!state.activeGraph) return state;
      const objects = state.activeGraph.objects.map((obj) =>
        obj.id === id ? { ...obj, material: materialId, color } : obj,
      );
      return { activeGraph: { ...state.activeGraph, objects } };
    }),

  setDragging: (dragging, objectId) =>
    set({ isDragging: dragging, dragObjectId: objectId ?? null }),

  pushUndo: () =>
    set((state) => {
      if (!state.activeGraph) return state;
      return { undoStack: [...state.undoStack.slice(-19), state.activeGraph] };
    }),

  undo: () =>
    set((state) => {
      if (state.undoStack.length === 0) return state;
      const prev = state.undoStack[state.undoStack.length - 1];
      return {
        activeGraph: prev,
        undoStack: state.undoStack.slice(0, -1),
      };
    }),

  setLayerVisibility: (layer, visible) =>
    set((state) => ({
      layerVisibility: { ...state.layerVisibility, [layer]: visible },
    })),

  setLoading: (v) => set({ isLoading: v }),
  setShowDimensions: (v) => set({ showDimensions: v }),
  setShowGrid: (v) => set({ showGrid: v }),
  setSnapToGrid: (v) => set({ snapToGrid: v }),
  setZoom: (v) => set({ zoom: Math.max(0.25, Math.min(4, v)) }),
  setPanOffset: (offset) => set({ panOffset: offset }),
}));

// ── Notes Store ───────────────────────────────────────────────────────────
//
// Phase 1 redesign: per-conversation notebooks.
//
// Each chat conversation owns its own notebook. The single source of
// truth is ``notebooksByConversation`` — a map keyed by
// conversationId. There is no longer a global ``notebook`` field;
// consumers use the ``useActiveNotebookSections()`` helper to read
// the *current* conversation's notes.
//
// Sync bookkeeping (consumed by ``useNotesPersist``):
// - ``dirtySectionIds`` — sections whose local content has changed
//   since the last successful PUT. Drained by the debounced sync.
// - ``pendingDeletions`` — sections deleted locally but not yet
//   confirmed deleted on the server. Drained the same way.
// - ``hydratedConversations`` — conversations whose server-side
//   notebook has been GET-fetched at least once this browser session.
//   Lets the persist hook avoid hammering the API on every render.
// - ``migratedToServer`` — set true once the one-time
//   localStorage → server import has succeeded.

interface NotesState {
  // Single source of truth.
  notebooksByConversation: Record<string, NoteSection[]>;

  // Sync bookkeeping.
  dirtySectionIds: string[];
  pendingDeletions: string[];
  hydratedConversations: string[];
  migratedToServer: boolean;

  // UI state.
  notesPanelOpen: boolean;
  activeBlockId: string | null;
  searchQuery: string;
  // Phase 3 — active tag filters in the sidebar. OR semantics: a
  // section matches if any of its tags appears in this list. When
  // empty, no filter is applied. Kept in the store (vs. component-
  // local) so the filter survives panel close/reopen and so tag
  // chips can advertise their active state from anywhere.
  activeTagFilters: string[];

  // UI actions.
  toggleNotesPanel: () => void;
  setNotesPanelOpen: (v: boolean) => void;
  setActiveBlock: (blockId: string | null) => void;
  setSearchQuery: (q: string) => void;
  toggleTagFilter: (tag: string) => void;
  clearTagFilters: () => void;

  // Section ops. ``addSection`` routes by ``section.sourceConversationId``.
  addSection: (section: NoteSection) => void;
  deleteSection: (sectionId: string) => void;

  // Block ops. The store finds which notebook owns ``sectionId``.
  updateBlock: (sectionId: string, blockId: string, updates: Partial<NoteBlock>) => void;
  addBlock: (sectionId: string, afterBlockId: string | null, block: NoteBlock) => void;
  deleteBlock: (sectionId: string, blockId: string) => void;
  moveBlock: (sectionId: string, fromIndex: number, toIndex: number) => void;

  // Tag ops (Phase 3). Tag matching is case-insensitive but the
  // displayed casing is whatever the user typed first. The store
  // enforces this — backend then re-canonicalises on save.
  addTagToSection: (sectionId: string, tag: string) => void;
  removeTagFromSection: (sectionId: string, tag: string) => void;

  // Image ops (Phase 4). ``setSectionImage(id, null)`` clears the
  // image. Both flavors mark the section dirty so the change syncs
  // to the server on the next debounce.
  setSectionImage: (sectionId: string, imageUrl: string | null) => void;

  // Sync helpers — called by ``useNotesPersist``.
  hydrateConversation: (conversationId: string, sections: NoteSection[]) => void;
  markSectionSynced: (sectionId: string) => void;
  markDeletionSynced: (sectionId: string) => void;
  markMigrated: () => void;

  // Snapshot helpers — used by the sync hook to read pending work
  // without subscribing to every store change.
  getDirtySections: () => NoteSection[];
  getPendingDeletions: () => string[];
  getAllSectionsFlat: () => NoteSection[];
}

// ── Internal helpers ──────────────────────────────────────────────────────

/** Add an id to an array, deduped. */
function addUnique(list: string[], id: string): string[] {
  return list.includes(id) ? list : [...list, id];
}

/** Remove an id from an array. */
function removeId(list: string[], id: string): string[] {
  return list.filter((x) => x !== id);
}

/** Find the conversationId that owns a section, or null if missing. */
function findOwningConversation(
  notebooks: Record<string, NoteSection[]>,
  sectionId: string,
): string | null {
  for (const [cid, sections] of Object.entries(notebooks)) {
    if (sections.some((s) => s.id === sectionId)) return cid;
  }
  return null;
}

/** Apply a transform to the section with ``sectionId`` in place,
 *  returning a new ``notebooksByConversation`` map. No-op if the
 *  section can't be found. */
function withUpdatedSection(
  notebooks: Record<string, NoteSection[]>,
  sectionId: string,
  transform: (s: NoteSection) => NoteSection,
): { notebooks: Record<string, NoteSection[]>; ownerCid: string | null } {
  const ownerCid = findOwningConversation(notebooks, sectionId);
  if (!ownerCid) return { notebooks, ownerCid: null };
  return {
    notebooks: {
      ...notebooks,
      [ownerCid]: notebooks[ownerCid].map((s) =>
        s.id === sectionId ? transform(s) : s,
      ),
    },
    ownerCid,
  };
}

export const useNotesStore = create<NotesState>()(
  persist(
    (set, get) => ({
      notebooksByConversation: {},
      dirtySectionIds: [],
      pendingDeletions: [],
      hydratedConversations: [],
      migratedToServer: false,

      notesPanelOpen: false,
      activeBlockId: null,
      searchQuery: "",
      activeTagFilters: [],

      toggleNotesPanel: () => set((s) => ({ notesPanelOpen: !s.notesPanelOpen })),
      setNotesPanelOpen: (v) => set({ notesPanelOpen: v }),
      setActiveBlock: (blockId) => set({ activeBlockId: blockId }),
      setSearchQuery: (q) => set({ searchQuery: q }),
      toggleTagFilter: (tag) =>
        set((s) => {
          const lowered = tag.toLowerCase();
          const has = s.activeTagFilters.some((t) => t.toLowerCase() === lowered);
          return {
            activeTagFilters: has
              ? s.activeTagFilters.filter((t) => t.toLowerCase() !== lowered)
              : [...s.activeTagFilters, tag],
          };
        }),
      clearTagFilters: () => set({ activeTagFilters: [] }),

      addSection: (section) =>
        set((s) => {
          const cid = section.sourceConversationId;
          const existing = s.notebooksByConversation[cid] ?? [];
          // Newest-first ordering; cap is enforced server-side.
          return {
            notebooksByConversation: {
              ...s.notebooksByConversation,
              [cid]: [section, ...existing.filter((x) => x.id !== section.id)],
            },
            dirtySectionIds: addUnique(s.dirtySectionIds, section.id),
          };
        }),

      deleteSection: (sectionId) =>
        set((s) => {
          const cid = findOwningConversation(s.notebooksByConversation, sectionId);
          if (!cid) return s;
          return {
            notebooksByConversation: {
              ...s.notebooksByConversation,
              [cid]: s.notebooksByConversation[cid].filter((x) => x.id !== sectionId),
            },
            // If it was dirty (never synced), drop it from dirty —
            // we don't need to PUT something we're about to DELETE.
            dirtySectionIds: removeId(s.dirtySectionIds, sectionId),
            pendingDeletions: addUnique(s.pendingDeletions, sectionId),
          };
        }),

      updateBlock: (sectionId, blockId, updates) =>
        set((s) => {
          const { notebooks, ownerCid } = withUpdatedSection(
            s.notebooksByConversation,
            sectionId,
            (sec) => ({
              ...sec,
              blocks: sec.blocks.map((b) =>
                b.id !== blockId ? b : { ...b, ...updates },
              ),
            }),
          );
          if (!ownerCid) return s;
          return {
            notebooksByConversation: notebooks,
            dirtySectionIds: addUnique(s.dirtySectionIds, sectionId),
          };
        }),

      addBlock: (sectionId, afterBlockId, block) =>
        set((s) => {
          const { notebooks, ownerCid } = withUpdatedSection(
            s.notebooksByConversation,
            sectionId,
            (sec) => {
              if (!afterBlockId) {
                return { ...sec, blocks: [block, ...sec.blocks] };
              }
              const idx = sec.blocks.findIndex((b) => b.id === afterBlockId);
              const blocks = [...sec.blocks];
              blocks.splice(idx + 1, 0, block);
              return { ...sec, blocks };
            },
          );
          if (!ownerCid) return s;
          return {
            notebooksByConversation: notebooks,
            dirtySectionIds: addUnique(s.dirtySectionIds, sectionId),
          };
        }),

      deleteBlock: (sectionId, blockId) =>
        set((s) => {
          const { notebooks, ownerCid } = withUpdatedSection(
            s.notebooksByConversation,
            sectionId,
            (sec) => ({ ...sec, blocks: sec.blocks.filter((b) => b.id !== blockId) }),
          );
          if (!ownerCid) return s;
          return {
            notebooksByConversation: notebooks,
            dirtySectionIds: addUnique(s.dirtySectionIds, sectionId),
          };
        }),

      moveBlock: (sectionId, fromIndex, toIndex) =>
        set((s) => {
          const { notebooks, ownerCid } = withUpdatedSection(
            s.notebooksByConversation,
            sectionId,
            (sec) => {
              const blocks = [...sec.blocks];
              const [moved] = blocks.splice(fromIndex, 1);
              blocks.splice(toIndex, 0, moved);
              return { ...sec, blocks };
            },
          );
          if (!ownerCid) return s;
          return {
            notebooksByConversation: notebooks,
            dirtySectionIds: addUnique(s.dirtySectionIds, sectionId),
          };
        }),

      // ── Tag ops ────────────────────────────────────────────────

      addTagToSection: (sectionId, tag) =>
        set((s) => {
          const trimmed = tag.trim().slice(0, 40);
          if (!trimmed) return s;
          const { notebooks, ownerCid } = withUpdatedSection(
            s.notebooksByConversation,
            sectionId,
            (sec) => {
              const existing = sec.tags ?? [];
              // Case-insensitive dedupe; preserve first occurrence's
              // casing. Cap at 20 client-side too so we never PUT
              // payloads the server will reject anyway.
              const lowered = new Set(existing.map((t) => t.toLowerCase()));
              if (lowered.has(trimmed.toLowerCase())) return sec;
              if (existing.length >= 20) return sec;
              return { ...sec, tags: [...existing, trimmed] };
            },
          );
          if (!ownerCid) return s;
          return {
            notebooksByConversation: notebooks,
            dirtySectionIds: addUnique(s.dirtySectionIds, sectionId),
          };
        }),

      removeTagFromSection: (sectionId, tag) =>
        set((s) => {
          const lowered = tag.toLowerCase();
          const { notebooks, ownerCid } = withUpdatedSection(
            s.notebooksByConversation,
            sectionId,
            (sec) => ({
              ...sec,
              tags: (sec.tags ?? []).filter((t) => t.toLowerCase() !== lowered),
            }),
          );
          if (!ownerCid) return s;
          return {
            notebooksByConversation: notebooks,
            dirtySectionIds: addUnique(s.dirtySectionIds, sectionId),
          };
        }),

      // ── Image ops (Phase 4) ─────────────────────────────────────

      setSectionImage: (sectionId, imageUrl) =>
        set((s) => {
          const { notebooks, ownerCid } = withUpdatedSection(
            s.notebooksByConversation,
            sectionId,
            (sec) => ({ ...sec, imageUrl }),
          );
          if (!ownerCid) return s;
          return {
            notebooksByConversation: notebooks,
            dirtySectionIds: addUnique(s.dirtySectionIds, sectionId),
          };
        }),

      // ── Sync helpers ────────────────────────────────────────────

      hydrateConversation: (conversationId, sections) =>
        set((s) => {
          // Server is canonical. Replace the conversation's sections
          // wholesale, but DON'T touch sections that are still dirty
          // locally (those are pending writes that should not be
          // clobbered by a stale GET).
          const dirtySet = new Set(s.dirtySectionIds);
          const local = s.notebooksByConversation[conversationId] ?? [];
          const dirtyLocalsForCid = local.filter((sec) => dirtySet.has(sec.id));
          const serverIds = new Set(sections.map((s) => s.id));
          const merged = [
            ...sections,
            // Append any locally-dirty sections that the server doesn't
            // know about yet (never PUT successfully).
            ...dirtyLocalsForCid.filter((sec) => !serverIds.has(sec.id)),
          ];
          return {
            notebooksByConversation: {
              ...s.notebooksByConversation,
              [conversationId]: merged,
            },
            hydratedConversations: addUnique(s.hydratedConversations, conversationId),
          };
        }),

      markSectionSynced: (sectionId) =>
        set((s) => ({ dirtySectionIds: removeId(s.dirtySectionIds, sectionId) })),

      markDeletionSynced: (sectionId) =>
        set((s) => ({ pendingDeletions: removeId(s.pendingDeletions, sectionId) })),

      markMigrated: () => set({ migratedToServer: true }),

      // ── Snapshot helpers ────────────────────────────────────────

      getDirtySections: () => {
        const { notebooksByConversation, dirtySectionIds } = get();
        const flat: NoteSection[] = [];
        for (const sections of Object.values(notebooksByConversation)) {
          for (const sec of sections) {
            if (dirtySectionIds.includes(sec.id)) flat.push(sec);
          }
        }
        return flat;
      },

      getPendingDeletions: () => get().pendingDeletions,

      getAllSectionsFlat: () => {
        const flat: NoteSection[] = [];
        for (const sections of Object.values(get().notebooksByConversation)) {
          flat.push(...sections);
        }
        return flat;
      },
    }),
    {
      name: "katha-notes",
      version: 3,
      migrate: (persisted, fromVersion) => {
        // ``backfillSectionFields`` brings any pre-Phase-3/4 section
        // up to the current shape: ``tags`` array (Phase 3) and
        // ``imageUrl`` (Phase 4). Both default to safe empties so
        // the type contract holds across the codebase.
        const backfillSectionFields = (sections: NoteSection[]): NoteSection[] =>
          sections.map((s) => ({
            ...s,
            tags: s.tags ?? [],
            imageUrl: s.imageUrl ?? null,
          }));

        // v0 → v3: flatten the single ``notebook`` into per-conversation
        // notebooks AND backfill tags + imageUrl. Mark every old
        // section as dirty so the persist hook pushes them on first
        // online sync, and leave ``migratedToServer=false`` so the
        // dedicated import endpoint runs once.
        if (fromVersion === 0 && persisted && typeof persisted === "object") {
          const old = persisted as {
            notebook?: Notebook;
            notesPanelOpen?: boolean;
          };
          const oldSections = old.notebook?.sections ?? [];
          const grouped: Record<string, NoteSection[]> = {};
          for (const sec of oldSections) {
            const cid = sec.sourceConversationId;
            if (!cid) continue;
            if (!grouped[cid]) grouped[cid] = [];
            grouped[cid].push({
              ...sec,
              tags: sec.tags ?? [],
              imageUrl: sec.imageUrl ?? null,
            });
          }
          return {
            notebooksByConversation: grouped,
            dirtySectionIds: oldSections.map((s) => s.id),
            pendingDeletions: [],
            hydratedConversations: [],
            migratedToServer: false,
            notesPanelOpen: old.notesPanelOpen ?? false,
            activeBlockId: null,
            searchQuery: "",
          } as Partial<NotesState> as NotesState;
        }

        // v1 or v2 → v3: shape is already correct; just backfill
        // any missing ``tags`` (v1) and ``imageUrl`` (v1 + v2)
        // fields. Sections that gained a backfill are marked dirty
        // so the freshly-defaulted values get pushed to the server
        // on the next sync — keeps client and server consistent
        // without a dedicated one-shot migration endpoint.
        if (
          (fromVersion === 1 || fromVersion === 2) &&
          persisted &&
          typeof persisted === "object"
        ) {
          const prev = persisted as Partial<NotesState> & {
            notebooksByConversation?: Record<string, NoteSection[]>;
          };
          const updated: Record<string, NoteSection[]> = {};
          const newDirty = new Set(prev.dirtySectionIds ?? []);
          for (const [cid, sections] of Object.entries(
            prev.notebooksByConversation ?? {},
          )) {
            updated[cid] = backfillSectionFields(sections);
            for (const s of sections) {
              if (!Array.isArray(s.tags) || s.imageUrl === undefined) {
                newDirty.add(s.id);
              }
            }
          }
          return {
            ...prev,
            notebooksByConversation: updated,
            dirtySectionIds: [...newDirty],
          } as NotesState;
        }
        return persisted as NotesState;
      },
      partialize: (s) => ({
        notebooksByConversation: s.notebooksByConversation,
        dirtySectionIds: s.dirtySectionIds,
        pendingDeletions: s.pendingDeletions,
        hydratedConversations: s.hydratedConversations,
        migratedToServer: s.migratedToServer,
        notesPanelOpen: s.notesPanelOpen,
      }),
    },
  ),
);

// ── Notes selectors (use these from components) ──────────────────────────
//
// Keep these *outside* the store so they can read from multiple stores
// (``useChatStore`` + ``useNotesStore``) without weird dependency
// chains. Components stay simple: one hook call, one list back.

/** Sections of the *currently active* conversation's notebook. */
export function useActiveNotebookSections(): NoteSection[] {
  const activeConversationId = useChatStore((s) => s.activeConversationId);
  const notebooks = useNotesStore((s) => s.notebooksByConversation);
  if (!activeConversationId) return [];
  return notebooks[activeConversationId] ?? [];
}
