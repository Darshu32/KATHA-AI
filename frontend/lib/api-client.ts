/**
 * API client — typed fetch wrapper for the KATHA AI backend.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

type Method = "GET" | "POST" | "PATCH" | "DELETE";

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
  ) {
    super(`API error ${status}`);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  method: Method = "GET",
  body?: unknown,
  token?: string,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    const errorBody = await res.json().catch(() => null);
    throw new ApiError(res.status, errorBody);
  }

  return res.json() as Promise<T>;
}

// ── Auth ────────────────────────────────────────────────────────────────────

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface UserResponse {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
}

export const auth = {
  register: (email: string, password: string, displayName = "") =>
    request<UserResponse>("/auth/register", "POST", {
      email,
      password,
      display_name: displayName,
    }),

  login: (email: string, password: string) =>
    request<TokenResponse>("/auth/login", "POST", { email, password }),

  me: (token?: string) => request<UserResponse>("/auth/me", "GET", undefined, token),
};

// ── Architecture (Knowledge Chat) ──────────────────────────────────────────

export interface ArchitectureAskResponse {
  status: string;
  question: string;
  answer: string;
  citations: string[];
  mode: string;
}

export const architecture = {
  ask: (token: string | undefined, question: string) =>
    request<ArchitectureAskResponse>("/architecture/ask", "POST", { question }, token),
};

// ── Chat (Streaming) ──────────────────────────────────────────────────────

export interface ChatStreamEvent {
  type: "token" | "done" | "error";
  content?: string;
  suggestions?: string[];
  image_prompt?: string | null;
  video_query?: string | null;
  youtube_query?: string | null;
  research_query?: string | null;
  reference_links?: Array<{ title: string; url: string; type: string }>;
  mode?: string;
}

export interface ChatHistoryMessage {
  role: string;
  content: string;
}

export interface ChatDoneData {
  content: string;
  suggestions: string[];
  image_prompt: string | null;
  video_query: string | null;
  youtube_query: string | null;
  research_query: string | null;
  reference_links: Array<{ title: string; url: string; type: string }>;
  mode: string;
}

export const chat = {
  /**
   * Stream a chat response via SSE.
   */
  stream: async (
    message: string,
    conversationHistory: ChatHistoryMessage[],
    mode: string | null,
    callbacks: {
      onToken: (token: string) => void;
      onDone: (data: ChatDoneData) => void | Promise<void>;
      onError: (error: string) => void;
    },
    signal?: AbortSignal,
  ): Promise<void> => {
    const res = await fetch(`${API_BASE}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        conversation_history: conversationHistory,
        mode,
      }),
      signal,
    });

    if (!res.ok) {
      callbacks.onError(`API error ${res.status}`);
      return;
    }

    const reader = res.body?.getReader();
    if (!reader) {
      callbacks.onError("No response stream available");
      return;
    }

    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;

          try {
            const event: ChatStreamEvent = JSON.parse(jsonStr);
            if (event.type === "token" && event.content) {
              callbacks.onToken(event.content);
            } else if (event.type === "done") {
              await callbacks.onDone({
                content: event.content ?? "",
                suggestions: event.suggestions ?? [],
                image_prompt: event.image_prompt ?? null,
                video_query: event.video_query ?? null,
                youtube_query: event.youtube_query ?? null,
                research_query: event.research_query ?? null,
                reference_links: event.reference_links ?? [],
                mode: event.mode ?? "quick",
              });
            } else if (event.type === "error") {
              callbacks.onError(event.content ?? "Unknown error");
            }
          } catch {
            // Skip malformed JSON lines
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  },

  /** Generate an AI architecture image (Nano Banana). */
  generateImage: (prompt: string) =>
    request<{ image: { url: string; title: string; source: string; type: string } | null }>(
      "/chat/generate-image", "POST", { prompt },
    ),

  /** Search YouTube for architecture videos. */
  searchYoutube: (query: string, maxResults = 3, duration: "short" | "medium" | "long" | "any" = "any") =>
    request<{ videos: Array<{ video_id: string; title: string; thumbnail: string; channel: string; url: string; type: string }> }>(
      "/chat/search-youtube", "POST", { query, max_results: maxResults, duration },
    ),

  /** Search Semantic Scholar for research papers. */
  searchPapers: (query: string, maxResults = 3) =>
    request<{ papers: Array<{ title: string; url: string; year?: number; authors?: string; citations?: number; type: string }> }>(
      "/chat/search-papers", "POST", { query, max_results: maxResults },
    ),

  /** Generate a short video (Sora — when available). */
  generateVideo: (prompt: string) =>
    request<{ video: { url: string; type: string } | null }>(
      "/chat/generate-video", "POST", { prompt },
    ),
};

// ── Design (Generation & Editing) ────────────────────────────────────────

export const design = {
  generate: (
    token: string,
    projectId: string,
    body: {
      prompt: string;
      room_type: string;
      style: string;
      dimensions?: { length: number; width: number };
      camera?: string;
      lighting?: string;
      view_mode?: string;
      ratio?: string;
      quality?: string;
      drawing_type?: string;
    },
  ) =>
    request<{ project_id: string; version: number; graph_data: unknown; estimate: unknown; status: string }>(
      `/projects/${projectId}/generate`, "POST", body, token,
    ),

  editObject: (token: string, projectId: string, body: { object_id: string; prompt: string }) =>
    request<{ project_id: string; version: number; graph_data: unknown; estimate: unknown; status: string }>(
      `/projects/${projectId}/edit`, "POST", body, token,
    ),

  switchTheme: (token: string, projectId: string, body: { new_style: string; preserve_layout: boolean }) =>
    request<{ project_id: string; version: number; graph_data: unknown; estimate: unknown; status: string }>(
      `/projects/${projectId}/theme`, "POST", body, token,
    ),

  getFloorPlan: (token: string, projectId: string, version?: number) =>
    request<{ drawing_type: string; floor_plan: unknown; drawing: unknown; preview_svg: string; summary: string }>(
      `/projects/${projectId}/drawings/floor-plan${version ? `?version=${version}` : ""}`, "GET", undefined, token,
    ),

  getLatest: (token: string, projectId: string) =>
    request<{ version: number; graph_data: unknown }>(
      `/projects/${projectId}/latest`, "GET", undefined, token,
    ),

  updatePosition: (token: string, projectId: string, objectId: string, position: { x: number; y: number; z: number }) =>
    request<{ status: string }>(
      `/projects/${projectId}/objects/${objectId}/position`, "PATCH", { position }, token,
    ),

  updateMaterial: (token: string, projectId: string, objectId: string, material: string, color: string) =>
    request<{ status: string }>(
      `/projects/${projectId}/objects/${objectId}/material`, "PATCH", { material, color }, token,
    ),

  // ── Phase 1 Layer 6 — Validator + Recommendations ───────────────────────
  validate: (token: string, projectId: string, versionNum?: number, segment: string = "residential") => {
    const qs = new URLSearchParams();
    if (versionNum !== undefined) qs.set("version_num", String(versionNum));
    qs.set("segment", segment);
    return request<{
      version: number;
      validation: import("./types").ValidationReport;
      recommendations: import("./types").RecommendationItem[];
    }>(`/projects/${projectId}/validate?${qs.toString()}`, "POST", undefined, token);
  },

  // ── Phase 1 Layer 2B — Auto-diagrams ────────────────────────────────────
  listDiagramsAvailable: (token: string, projectId: string) =>
    request<{ diagrams: Array<{ id: string; name: string; status: "ready" | "planned" }> }>(
      `/projects/${projectId}/diagrams/available`, "GET", undefined, token,
    ),

  generateDiagrams: (token: string, projectId: string, versionNum?: number, diagramId?: string) => {
    const qs = new URLSearchParams();
    if (versionNum !== undefined) qs.set("version_num", String(versionNum));
    if (diagramId) qs.set("diagram_id", diagramId);
    return request<{
      version: number;
      diagrams: import("./types").DiagramPayload[];
    }>(`/projects/${projectId}/diagrams?${qs.toString()}`, "POST", undefined, token);
  },

  // ── Phase 1 Layer 3 — Specs ─────────────────────────────────────────────
  getSpecs: (token: string, projectId: string, versionNum?: number) => {
    const qs = versionNum !== undefined ? `?version_num=${versionNum}` : "";
    return request<{ version: number; spec_bundle: import("./types").SpecBundle }>(
      `/projects/${projectId}/specs${qs}`, "GET", undefined, token,
    );
  },

  // ── Phase 1 Layer 5 — Exporters ─────────────────────────────────────────
  listExportFormats: (token: string, projectId: string) =>
    request<{ formats: string[] }>(
      `/projects/${projectId}/export/formats`, "GET", undefined, token,
    ),

  /** Download an export as a Blob (pdf/docx/xlsx/dxf/obj/gltf/ifc/step/gcode). */
  exportFile: async (
    token: string,
    projectId: string,
    format: import("./types").ExportFormat,
    versionNum?: number,
  ): Promise<{ blob: Blob; filename: string; contentType: string }> => {
    const qs = new URLSearchParams({ format });
    if (versionNum !== undefined) qs.set("version_num", String(versionNum));
    const res = await fetch(`${API_BASE}/projects/${projectId}/export?${qs.toString()}`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new ApiError(res.status, body);
    }
    const contentType = res.headers.get("Content-Type") ?? "application/octet-stream";
    const disposition = res.headers.get("Content-Disposition") ?? "";
    const match = disposition.match(/filename="([^"]+)"/);
    const filename = match?.[1] ?? `${projectId}.${format}`;
    const blob = await res.blob();
    return { blob, filename, contentType };
  },
};

// ── Default export ─────────────────────────────────────────────────────────

const api = { auth, architecture, chat, design };
export default api;
