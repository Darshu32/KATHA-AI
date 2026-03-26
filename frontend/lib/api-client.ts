/**
 * API client — typed fetch wrapper for the KATHA AI backend.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

type Method = "GET" | "POST" | "PATCH" | "DELETE";

class ApiError extends Error {
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

  me: (token: string) => request<UserResponse>("/auth/me", "GET", undefined, token),
};

// ── Projects ────────────────────────────────────────────────────────────────

export interface ProjectResponse {
  id: string;
  name: string;
  description: string;
  status: string;
  latest_version: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectListResponse {
  projects: ProjectResponse[];
  total: number;
}

export const projects = {
  list: (token: string, offset = 0, limit = 50) =>
    request<ProjectListResponse>(
      `/projects?offset=${offset}&limit=${limit}`,
      "GET",
      undefined,
      token,
    ),

  get: (token: string, projectId: string) =>
    request<ProjectResponse>(`/projects/${projectId}`, "GET", undefined, token),

  create: (
    token: string,
    data: { name: string; description?: string; prompt: string; room_type?: string; style?: string },
  ) => request<ProjectResponse>("/projects", "POST", data, token),

  update: (token: string, projectId: string, data: Record<string, unknown>) =>
    request<ProjectResponse>(`/projects/${projectId}`, "PATCH", data, token),
};

// ── Generation ──────────────────────────────────────────────────────────────

export interface GenerationResult {
  project_id: string;
  version: number;
  version_id: string;
  graph_data: Record<string, unknown>;
  estimate: Record<string, unknown>;
  status: string;
}

export const generation = {
  generate: (
    token: string,
    projectId: string,
    data: { prompt: string; room_type?: string; style?: string },
  ) => request<GenerationResult>(`/projects/${projectId}/generate`, "POST", data, token),

  edit: (
    token: string,
    projectId: string,
    data: { object_id: string; prompt: string },
  ) => request<GenerationResult>(`/projects/${projectId}/edit`, "POST", data, token),

  switchTheme: (
    token: string,
    projectId: string,
    data: { new_style: string; preserve_layout?: boolean },
  ) => request<GenerationResult>(`/projects/${projectId}/theme`, "POST", data, token),

  getLatest: (token: string, projectId: string) =>
    request<Record<string, unknown>>(`/projects/${projectId}/latest`, "GET", undefined, token),

  listVersions: (token: string, projectId: string) =>
    request<Record<string, unknown>>(`/projects/${projectId}/versions`, "GET", undefined, token),

  getVersion: (token: string, projectId: string, version: number) =>
    request<Record<string, unknown>>(
      `/projects/${projectId}/versions/${version}`,
      "GET",
      undefined,
      token,
    ),
};

// ── Estimates ───────────────────────────────────────────────────────────────

export interface EstimateResult {
  project_id: string;
  version: number;
  status: string;
  line_items: Array<{
    category: string;
    item_name: string;
    material: string;
    quantity: number;
    unit: string;
    unit_rate_low: number;
    unit_rate_high: number;
    total_low: number;
    total_high: number;
  }>;
  total_low: number;
  total_high: number;
  currency: string;
  assumptions: string[];
}

export const estimates = {
  getLatest: (token: string, projectId: string) =>
    request<EstimateResult>(`/projects/${projectId}/estimates`, "GET", undefined, token),

  getForVersion: (token: string, projectId: string, version: number) =>
    request<EstimateResult>(
      `/projects/${projectId}/estimates/version/${version}`,
      "GET",
      undefined,
      token,
    ),
};

const api = { auth, projects, generation, estimates };
export default api;
