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
      rightSidebarOpen: true,
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
