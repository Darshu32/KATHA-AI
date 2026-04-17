/**
 * Zustand stores — global state for auth and chat.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type {
  Message,
  Conversation,
  ChatMode,
  WorkspaceId,
  ArchTheme,
  DrawingType,
  ImageRatio,
  ImageQuality,
  ImageGeneration,
  GeneratedImage,
  DesignGraph,
  DesignObject,
  Vec3,
  NoteBlock,
  NoteSection,
  Notebook,
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
  theme: ArchTheme;
  drawingType: DrawingType;
  ratio: ImageRatio;
  quality: ImageQuality;
  styleEnhance: boolean;
  generations: ImageGeneration[];
  isGenerating: boolean;
  rightSidebarOpen: boolean;
  terminalOpen: boolean;
  viewMode: "2d" | "3d";

  setPrompt: (v: string) => void;
  setNegativePrompt: (v: string) => void;
  setTheme: (v: ArchTheme) => void;
  setDrawingType: (v: DrawingType) => void;
  setRatio: (v: ImageRatio) => void;
  setQuality: (v: ImageQuality) => void;
  setStyleEnhance: (v: boolean) => void;
  setIsGenerating: (v: boolean) => void;
  addGeneration: (gen: ImageGeneration) => void;
  setRightSidebarOpen: (v: boolean) => void;
  toggleTerminal: () => void;
  setViewMode: (v: "2d" | "3d") => void;
}

export const useImageGenStore = create<ImageGenState>()(
  persist(
    (set) => ({
      prompt: "",
      negativePrompt: "",
      theme: "modern",
      drawingType: "3d-render",
      ratio: "16:9",
      quality: "standard",
      styleEnhance: true,
      generations: [],
      isGenerating: false,
      rightSidebarOpen: false,
      terminalOpen: false,
      viewMode: "2d",

      setPrompt: (v) => set({ prompt: v }),
      setNegativePrompt: (v) => set({ negativePrompt: v }),
      setTheme: (v) => set({ theme: v }),
      setDrawingType: (v) => set({ drawingType: v }),
      setRatio: (v) => set({ ratio: v }),
      setQuality: (v) => set({ quality: v }),
      setStyleEnhance: (v) => set({ styleEnhance: v }),
      setIsGenerating: (v) => set({ isGenerating: v }),
      addGeneration: (gen) =>
        set((state) => ({ generations: [gen, ...state.generations] })),
      setRightSidebarOpen: (v) => set({ rightSidebarOpen: v }),
      toggleTerminal: () => set((state) => ({ terminalOpen: !state.terminalOpen })),
      setViewMode: (v) => set({ viewMode: v }),
    }),
    {
      name: "katha-image-gen",
      partialize: (state) => ({
        theme: state.theme,
        drawingType: state.drawingType,
        ratio: state.ratio,
        quality: state.quality,
        styleEnhance: state.styleEnhance,
        generations: state.generations,
        rightSidebarOpen: state.rightSidebarOpen,
        viewMode: state.viewMode,
      }),
    },
  ),
);

// ── Design Store ──────────────────────────────────────────────────────────

interface LayerVisibility {
  furniture: boolean;
  dimensions: boolean;
  grid: boolean;
  wireframe: boolean;
  materials: boolean;
  lighting: boolean;
}

interface DesignState {
  activeGraph: DesignGraph | null;
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

interface NotesState {
  notebook: Notebook;
  notesPanelOpen: boolean;
  activeBlockId: string | null;
  searchQuery: string;

  toggleNotesPanel: () => void;
  setNotesPanelOpen: (v: boolean) => void;

  addSection: (section: NoteSection) => void;
  deleteSection: (sectionId: string) => void;

  updateBlock: (sectionId: string, blockId: string, updates: Partial<NoteBlock>) => void;
  addBlock: (sectionId: string, afterBlockId: string | null, block: NoteBlock) => void;
  deleteBlock: (sectionId: string, blockId: string) => void;
  moveBlock: (sectionId: string, fromIndex: number, toIndex: number) => void;

  setActiveBlock: (blockId: string | null) => void;
  setSearchQuery: (q: string) => void;
}

export const useNotesStore = create<NotesState>()(
  persist(
    (set) => ({
      notebook: { id: "default", sections: [], updatedAt: new Date().toISOString() },
      notesPanelOpen: false,
      activeBlockId: null,
      searchQuery: "",

      toggleNotesPanel: () => set((s) => ({ notesPanelOpen: !s.notesPanelOpen })),
      setNotesPanelOpen: (v) => set({ notesPanelOpen: v }),

      addSection: (section) =>
        set((s) => ({
          notebook: {
            ...s.notebook,
            sections: [section, ...s.notebook.sections].slice(0, 50),
            updatedAt: new Date().toISOString(),
          },
        })),

      deleteSection: (sectionId) =>
        set((s) => ({
          notebook: {
            ...s.notebook,
            sections: s.notebook.sections.filter((sec) => sec.id !== sectionId),
            updatedAt: new Date().toISOString(),
          },
        })),

      updateBlock: (sectionId, blockId, updates) =>
        set((s) => ({
          notebook: {
            ...s.notebook,
            sections: s.notebook.sections.map((sec) =>
              sec.id !== sectionId
                ? sec
                : {
                    ...sec,
                    blocks: sec.blocks.map((b) =>
                      b.id !== blockId ? b : { ...b, ...updates },
                    ),
                  },
            ),
            updatedAt: new Date().toISOString(),
          },
        })),

      addBlock: (sectionId, afterBlockId, block) =>
        set((s) => ({
          notebook: {
            ...s.notebook,
            sections: s.notebook.sections.map((sec) => {
              if (sec.id !== sectionId) return sec;
              if (!afterBlockId) return { ...sec, blocks: [block, ...sec.blocks] };
              const idx = sec.blocks.findIndex((b) => b.id === afterBlockId);
              const blocks = [...sec.blocks];
              blocks.splice(idx + 1, 0, block);
              return { ...sec, blocks };
            }),
            updatedAt: new Date().toISOString(),
          },
        })),

      deleteBlock: (sectionId, blockId) =>
        set((s) => ({
          notebook: {
            ...s.notebook,
            sections: s.notebook.sections.map((sec) =>
              sec.id !== sectionId
                ? sec
                : { ...sec, blocks: sec.blocks.filter((b) => b.id !== blockId) },
            ),
            updatedAt: new Date().toISOString(),
          },
        })),

      moveBlock: (sectionId, fromIndex, toIndex) =>
        set((s) => ({
          notebook: {
            ...s.notebook,
            sections: s.notebook.sections.map((sec) => {
              if (sec.id !== sectionId) return sec;
              const blocks = [...sec.blocks];
              const [moved] = blocks.splice(fromIndex, 1);
              blocks.splice(toIndex, 0, moved);
              return { ...sec, blocks };
            }),
            updatedAt: new Date().toISOString(),
          },
        })),

      setActiveBlock: (blockId) => set({ activeBlockId: blockId }),
      setSearchQuery: (q) => set({ searchQuery: q }),
    }),
    {
      name: "katha-notes",
      partialize: (s) => ({
        notebook: s.notebook,
        notesPanelOpen: s.notesPanelOpen,
      }),
    },
  ),
);
