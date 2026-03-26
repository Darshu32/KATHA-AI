/**
 * Zustand stores — global state for auth, project, and design graph.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

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

// ── Project Store ───────────────────────────────────────────────────────────

interface ProjectMeta {
  id: string;
  name: string;
  description: string;
  status: string;
  latestVersion: number;
  createdAt: string;
  updatedAt: string;
}

interface ProjectState {
  projects: ProjectMeta[];
  activeProjectId: string | null;
  setProjects: (projects: ProjectMeta[]) => void;
  setActiveProject: (id: string | null) => void;
  addProject: (project: ProjectMeta) => void;
}

export const useProjectStore = create<ProjectState>()((set) => ({
  projects: [],
  activeProjectId: null,
  setProjects: (projects) => set({ projects }),
  setActiveProject: (id) => set({ activeProjectId: id }),
  addProject: (project) =>
    set((state) => ({ projects: [project, ...state.projects] })),
}));

// ── Design Graph Store ──────────────────────────────────────────────────────

interface DesignGraphState {
  graphData: Record<string, unknown> | null;
  version: number;
  selectedObjectId: string | null;
  isGenerating: boolean;

  setGraphData: (data: Record<string, unknown>, version: number) => void;
  selectObject: (id: string | null) => void;
  setGenerating: (v: boolean) => void;
  clearGraph: () => void;
}

export const useDesignGraphStore = create<DesignGraphState>()((set) => ({
  graphData: null,
  version: 0,
  selectedObjectId: null,
  isGenerating: false,

  setGraphData: (data, version) =>
    set({ graphData: data, version, isGenerating: false }),
  selectObject: (id) => set({ selectedObjectId: id }),
  setGenerating: (v) => set({ isGenerating: v }),
  clearGraph: () =>
    set({ graphData: null, version: 0, selectedObjectId: null }),
}));

// ── Estimate Store ──────────────────────────────────────────────────────────

interface EstimateState {
  estimate: Record<string, unknown> | null;
  setEstimate: (e: Record<string, unknown> | null) => void;
}

export const useEstimateStore = create<EstimateState>()((set) => ({
  estimate: null,
  setEstimate: (e) => set({ estimate: e }),
}));

// ── UI Store ────────────────────────────────────────────────────────────────

interface UIState {
  sidePanel: "3d" | "estimate" | "versions" | "materials" | null;
  theme: string;
  setSidePanel: (panel: UIState["sidePanel"]) => void;
  setTheme: (theme: string) => void;
}

export const useUIStore = create<UIState>()((set) => ({
  sidePanel: "3d",
  theme: "modern",
  setSidePanel: (panel) => set({ sidePanel: panel }),
  setTheme: (theme) => set({ theme }),
}));
