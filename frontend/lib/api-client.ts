/**
 * API client — typed fetch wrapper for the KATHA AI backend.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

/**
 * Resolve a backend-issued asset URL against the API host.
 *
 * The render-storage path on the backend (`POST /projects/{id}/generate`
 * etc.) returns `image_url` as a relative path like
 * `/api/v1/assets/renders/abc/v01.png`. If we set that directly as an
 * `<img src>` the browser resolves it against the Next dev server
 * (`localhost:3001`) and 404s — assets live on the API host
 * (`localhost:8000` in dev). This helper normalises:
 *
 *   - `data:` and `http(s)://` URLs pass through (legacy renders,
 *     future CDN URLs).
 *   - `/api/v1/...` paths get prefixed with the API origin.
 *   - `null`/`undefined` returns `undefined`.
 */
export function resolveAssetUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  if (/^(data:|https?:|blob:)/i.test(url)) return url;
  if (url.startsWith("/")) {
    // Strip the /api/v1 suffix from API_BASE to get the bare origin,
    // then re-attach whatever absolute path the backend returned.
    const origin = API_BASE.replace(/\/api\/v\d+\/?$/, "");
    return `${origin}${url}`;
  }
  return url;
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

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

  // 204 No Content (and any other body-less success) — return undefined
  // cast to T. Endpoints that actually need a typed body should not
  // return 204; this branch keeps DELETE-style calls from crashing
  // on res.json() of an empty body.
  if (res.status === 204) {
    return undefined as unknown as T;
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

// ── Project types (public, dynamic config) ────────────────────────────────

export interface ProjectTypeDef {
  slug: string;
  label: string;
  description: string;
  starter_prompts: string[];
  visual_hint: string;
  is_primary: boolean;
  sort_order: number;
}

export const projectTypes = {
  list: () =>
    request<{ project_types: ProjectTypeDef[]; count: number }>(
      "/project-types",
    ),
};

// ── Themes (public, DB-backed) ────────────────────────────────────────────

export interface ThemeDef {
  slug: string;
  display_name: string;
  description: string;
  era: string | null;
  preview_image_keys: string[];
  aliases: string[];
}

export const themes = {
  list: () =>
    request<{ themes: ThemeDef[]; count: number }>("/themes"),
};

// ── Building Standards (BRD §1B catalogue, public read-only) ──────────────

export interface StandardRow {
  slug: string;
  category: string;
  subcategory: string | null;
  jurisdiction: string;
  display_name: string;
  notes: string | null;
  data: Record<string, unknown>;
  source_section: string | null;
  source_doc: string | null;
}

export const standards = {
  /** List authoritative standards. `category` defaults to `space`. */
  list: (params: { category?: string; segment?: string; jurisdiction?: string } = {}) => {
    const qs = new URLSearchParams();
    qs.set("category", params.category ?? "space");
    if (params.segment) qs.set("segment", params.segment);
    if (params.jurisdiction) qs.set("jurisdiction", params.jurisdiction);
    return request<{
      standards: StandardRow[];
      count: number;
      filter: { category: string; segment: string | null; jurisdiction: string };
    }>(`/standards?${qs.toString()}`);
  },
};

// ── Design Brief (BRD §1A) ────────────────────────────────────────────────

export interface BriefIntakePayload {
  project_type?: Record<string, unknown>;
  theme?: Record<string, unknown>;
  space?: Record<string, unknown>;
  requirements?: Record<string, unknown>;
  regulatory?: Record<string, unknown>;
  notes?: string;
}

export interface BriefIntakeResponse {
  brief_id: string;
  status: string;
  project_type: Record<string, unknown>;
  theme: Record<string, unknown>;
  space: Record<string, unknown>;
  requirements: Record<string, unknown>;
  regulatory: Record<string, unknown>;
  warnings: string[];
}

export const brief = {
  /** Validate + normalise a 5-section brief (BRD §1A). */
  intake: (payload: BriefIntakePayload) =>
    request<BriefIntakeResponse>("/brief/intake", "POST", payload),
};

// ── Image generation (Nano Banana / Gemini) ───────────────────────────────

export interface ImageGenerateResponse {
  status: "ok" | "provider_unconfigured";
  image: {
    url: string;
    title?: string;
    source?: string;
    type?: string;
  } | null;
  prompt_assembled?: string | null;
  project_type: string;
  theme: string;
}

export const images = {
  generate: (
    token: string | undefined,
    body: {
      prompt: string;
      project_type: string;
      theme: string;
      ratio?: string;
    },
  ) =>
    request<ImageGenerateResponse>("/images/generate", "POST", body, token),
};

// ── Chat (Streaming) ──────────────────────────────────────────────────────

// BRD §1A — 5-section design brief progressively captured during Deep-mode chat.
// The backend prompt fills only what the user has actually said; missing fields
// remain absent. Status maps each section to "pending" / "partial" / "confirmed".
export type BriefSectionStatus = "pending" | "partial" | "confirmed";

export interface BriefPayload {
  project_type?: Record<string, unknown>;
  theme?: Record<string, unknown>;
  space?: Record<string, unknown>;
  requirements?: Record<string, unknown>;
  regulatory?: Record<string, unknown>;
  notes?: string;
}

export interface BriefStatus {
  project_type?: BriefSectionStatus;
  theme?: BriefSectionStatus;
  space?: BriefSectionStatus;
  requirements?: BriefSectionStatus;
  regulatory?: BriefSectionStatus;
}

export interface ChatStreamEvent {
  type: "token" | "done" | "error";
  content?: string;
  suggestions?: string[];
  image_prompt?: string | null;
  video_query?: string | null;
  youtube_query?: string | null;
  research_query?: string | null;
  reference_links?: Array<{ title: string; url: string; type: string }>;
  brief?: BriefPayload | null;
  brief_status?: BriefStatus | null;
  brief_missing?: string[];
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
  brief: BriefPayload | null;
  brief_status: BriefStatus | null;
  brief_missing: string[];
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
                brief: event.brief ?? null,
                brief_status: event.brief_status ?? null,
                brief_missing: event.brief_missing ?? [],
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

// ── Imports (BRD Layer 5B — file upload + parse) ────────────────────────
//
// Two-stage flow on the backend:
//   POST /imports/parse    — deterministic parser returns one payload
//                            per file (text, dimensions, geometry…).
//   POST /imports/advisor  — optional LLM stage that turns parsed
//                            payloads into a project-merge manifest.
//
// `parse` is multipart, so it bypasses the JSON `request<T>` helper
// and assembles a FormData body manually.

export interface ImportedFilePayload {
  format: string;
  filename: string;
  size_bytes: number;
  summary: string;
  extracted: Record<string, unknown>;
  warnings: string[];
}

export interface ImportParseResponse {
  count: number;
  imports: ImportedFilePayload[];
}

export const imports = {
  /** List the file extensions the deterministic parsers support. */
  formats: () =>
    request<{ extensions: string[] }>("/imports/formats"),

  /** Upload one or more files; backend runs each through its
   *  importer and returns the structured payload. Multipart-only;
   *  bypasses the JSON request helper. */
  parse: async (
    token: string | undefined,
    files: File[],
  ): Promise<ImportParseResponse> => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f, f.name);
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`${API_BASE}/imports/parse`, {
      method: "POST",
      headers,
      body: fd,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(res.status, body);
    }
    return res.json() as Promise<ImportParseResponse>;
  },

  /** Run the LLM advisor over already-parsed payloads to produce a
   *  project-merge manifest. Currently unused from the UI; kept for
   *  the eventual "Apply to current project" flow. */
  advisor: (
    token: string | undefined,
    body: { imports: ImportedFilePayload[] },
  ) =>
    request<{ status: string; manifest: unknown }>(
      "/imports/advisor",
      "POST",
      body,
      token,
    ),
};

// ── Projects (CRUD) ──────────────────────────────────────────────────────
//
// A project is the unit that owns a design graph + its version history.
// Every generation/edit/theme-switch is scoped to a project so the
// architect can iterate on a single design instead of starting over.

export interface ProjectOut {
  id: string;
  name: string;
  description: string | null;
  status: string;
  project_type: string;
  project_sub_type: string | null;
  project_scale: string | null;
  created_at: string;
  updated_at: string;
}

export const projects = {
  /* All project endpoints accept an optional token. The backend
     middleware short-circuits to a shared dev user when the header
     is absent (prototype mode). When auth is reintroduced, callers
     can start passing tokens again without changing call sites. */
  create: (
    token: string | undefined,
    body: {
      name: string;
      description?: string | null;
      project_type: string;
      project_sub_type?: string | null;
      project_scale?: string | null;
    },
  ) => request<ProjectOut>("/projects", "POST", body, token),

  list: (token?: string) =>
    request<{ projects: ProjectOut[]; total: number }>(
      "/projects",
      "GET",
      undefined,
      token,
    ),

  get: (token: string | undefined, projectId: string) =>
    request<ProjectOut>(`/projects/${projectId}`, "GET", undefined, token),

  /* PATCH a project's mutable fields. Any subset of these may be
     passed; the server preserves anything omitted. Used by the
     project picker to rename + archive. */
  update: (
    token: string | undefined,
    projectId: string,
    body: {
      name?: string;
      description?: string | null;
      status?: "draft" | "ready" | "archived" | string;
      project_type?: string;
      project_sub_type?: string | null;
      project_scale?: string | null;
    },
  ) => request<ProjectOut>(`/projects/${projectId}`, "PATCH", body, token),
};

// ── Design (Generation & Editing) ────────────────────────────────────────
//
// Like `projects`, every design endpoint now accepts an optional token.
// The backend middleware attributes anonymous traffic to a shared dev
// user (prototype mode). When auth comes back, callers thread real
// tokens in without touching call signatures.

export const design = {
  generate: (
    token: string | undefined,
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
    request<{
      project_id: string;
      version: number;
      graph_data: unknown;
      estimate: unknown;
      image_url: string | null;
      objects_bbox: Array<{ id: string; name: string; type: string; x: number; y: number; w: number; h: number }>;
      // BRD §1B / §9.1 — validation report runs inline with the
      // generation pipeline so the Problems terminal tab has real
      // content from the very first render.
      validation?: import("./types").ValidationReport;
      // BRD §1B MEP — system-cost rollup (HVAC + electrical + plumbing
      // + fire-fighting). null when the graph has no usable room area.
      mep_cost_estimate?: import("./types").MepCostEstimate | null;
      // BRD §1B Building Code Integration — pre-rolled compliance
      // summary (fail / warn / info) for the right sidebar.
      code_compliance_summary?: import("./types").CodeComplianceEntry[];
      status: string;
    }>(
      `/projects/${projectId}/generate`, "POST", body, token,
    ),

  editObject: (token: string | undefined, projectId: string, body: { object_id: string; prompt: string }) =>
    request<{
      project_id: string;
      version: number;
      graph_data: unknown;
      estimate: unknown;
      image_url: string | null;
      objects_bbox: Array<{ id: string; name: string; type: string; x: number; y: number; w: number; h: number }>;
      validation?: import("./types").ValidationReport;
      mep_cost_estimate?: import("./types").MepCostEstimate | null;
      code_compliance_summary?: import("./types").CodeComplianceEntry[];
      status: string;
    }>(
      `/projects/${projectId}/edit`, "POST", body, token,
    ),

  switchTheme: (token: string | undefined, projectId: string, body: { new_style: string; preserve_layout: boolean }) =>
    request<{
      project_id: string;
      version: number;
      graph_data: unknown;
      estimate: unknown;
      image_url: string | null;
      objects_bbox: Array<{ id: string; name: string; type: string; x: number; y: number; w: number; h: number }>;
      validation?: import("./types").ValidationReport;
      mep_cost_estimate?: import("./types").MepCostEstimate | null;
      code_compliance_summary?: import("./types").CodeComplianceEntry[];
      status: string;
    }>(
      `/projects/${projectId}/theme`, "POST", body, token,
    ),

  getFloorPlan: (token: string | undefined, projectId: string, version?: number) =>
    request<{ drawing_type: string; floor_plan: unknown; drawing: unknown; preview_svg: string; summary: string }>(
      `/projects/${projectId}/drawings/floor-plan${version ? `?version=${version}` : ""}`, "GET", undefined, token,
    ),

  getLatest: (token: string | undefined, projectId: string) =>
    request<{
      id: string;
      version: number;
      graph_data: unknown;
      prompt: string | null;
      image_url: string | null;
      objects_bbox: Array<{ id: string; name: string; type: string; x: number; y: number; w: number; h: number }>;
    }>(
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

// ── Notes (Phase 1 — per-conversation server-side notebooks) ───────────────
//
// Wire shape mirrors the backend ``app.models.schemas`` notes section.
// Block payloads are passed through as ``unknown[]`` because their
// structure evolves on the frontend; the source of truth for block
// shape is ``./types.ts``.

export interface NoteSectionWire {
  id: string;
  conversation_id: string;
  source_message_id: string | null;
  title: string;
  blocks: unknown[];
  // Phase 3 — server canonicalises these (trimmed, deduped). The
  // server may return a server-default empty list for older rows
  // that pre-date the column.
  tags: string[];
  // Phase 4 — auto-generated image (base64 data URI today).
  image_url: string | null;
  client_created_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface NoteSectionUpsertBody {
  conversation_id: string;
  source_message_id?: string | null;
  title: string;
  blocks: unknown[];
  tags?: string[];
  image_url?: string | null;
  client_created_at?: string | null;
}

export interface NoteImportItem {
  id: string;
  conversation_id: string;
  source_message_id?: string | null;
  title: string;
  blocks: unknown[];
  tags?: string[];
  image_url?: string | null;
  client_created_at?: string | null;
}

export interface NoteImportResult {
  imported: number;
  skipped: number;
}

export const notes = {
  /** All sections in one conversation's notebook, newest-first. */
  list: (conversationId: string, token?: string) =>
    request<{ sections: NoteSectionWire[] }>(
      `/notes/sections?conversation_id=${encodeURIComponent(conversationId)}`,
      "GET",
      undefined,
      token,
    ),

  /** Create-or-update a section by client-supplied ID. */
  upsert: (sectionId: string, body: NoteSectionUpsertBody, token?: string) =>
    request<NoteSectionWire>(
      `/notes/sections/${encodeURIComponent(sectionId)}`,
      "PUT",
      body,
      token,
    ),

  /** Delete a section. Resolves on 204; throws ApiError on 404. */
  delete: (sectionId: string, token?: string) =>
    request<void>(
      `/notes/sections/${encodeURIComponent(sectionId)}`,
      "DELETE",
      undefined,
      token,
    ),

  /**
   * One-time bulk push of localStorage notes to the server.
   * Already-existing IDs are skipped on the server side, not
   * overwritten — see backend route for rationale.
   */
  import: (sections: NoteImportItem[], token?: string) =>
    request<NoteImportResult>(
      `/notes/import`,
      "POST",
      { sections },
      token,
    ),
};

// ── Default export ─────────────────────────────────────────────────────────

const api = { auth, architecture, chat, projects, design, imports, notes };
export default api;
