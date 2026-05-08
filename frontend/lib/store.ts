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
        const conversation: Conversation = {
          id,
          title: "New conversation",
          messages: [],
          createdAt: now,
          updatedAt: now,
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

interface ImageGenState {
  prompt: string;
  negativePrompt: string;
  projectType: ProjectType;
  projectSubType: string;
  projectScale: string;
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
  activeProjectId: string | null;
  activeProjectVersion: number | null;

  setPrompt: (v: string) => void;
  setNegativePrompt: (v: string) => void;
  setProjectType: (v: ProjectType) => void;
  setProjectSubType: (v: string) => void;
  setProjectScale: (v: string) => void;
  setTheme: (v: ArchTheme) => void;
  setDrawingType: (v: DrawingType) => void;
  setRatio: (v: ImageRatio) => void;
  setQuality: (v: ImageQuality) => void;
  setStyleEnhance: (v: boolean) => void;
  setCamera: (v: CameraMode) => void;
  setLighting: (v: LightingMode) => void;
  setIsGenerating: (v: boolean) => void;
  addGeneration: (gen: ImageGeneration) => void;
  setRightSidebarOpen: (v: boolean) => void;
  toggleTerminal: () => void;
  setViewMode: (v: "2d" | "3d") => void;
  setActiveProject: (projectId: string | null, version?: number | null) => void;
}

export const useImageGenStore = create<ImageGenState>()(
  persist(
    (set) => ({
      prompt: "",
      negativePrompt: "",
      projectType: "residential",
      projectSubType: "",
      projectScale: "",
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

      setPrompt: (v) => set({ prompt: v }),
      setNegativePrompt: (v) => set({ negativePrompt: v }),
      setProjectType: (v) => set({ projectType: v }),
      setProjectSubType: (v) => set({ projectSubType: v }),
      setProjectScale: (v) => set({ projectScale: v }),
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
      setRightSidebarOpen: (v) => set({ rightSidebarOpen: v }),
      toggleTerminal: () => set((state) => ({ terminalOpen: !state.terminalOpen })),
      setViewMode: (v) => set({ viewMode: v }),
      setActiveProject: (projectId, version = null) =>
        set({ activeProjectId: projectId, activeProjectVersion: version }),
    }),
    {
      name: "katha-image-gen",
      partialize: (state) => ({
        projectType: state.projectType,
        projectSubType: state.projectSubType,
        projectScale: state.projectScale,
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
