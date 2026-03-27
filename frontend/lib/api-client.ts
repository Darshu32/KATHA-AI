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

  me: (token?: string) => request<UserResponse>("/auth/me", "GET", undefined, token),
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
  list: (token?: string, offset = 0, limit = 50) =>
    request<ProjectListResponse>(
      `/projects?offset=${offset}&limit=${limit}`,
      "GET",
      undefined,
      token,
    ),

  get: (token: string | undefined, projectId: string) =>
    request<ProjectResponse>(`/projects/${projectId}`, "GET", undefined, token),

  create: (
    token: string | undefined,
    data: { name: string; description?: string; prompt: string; room_type?: string; style?: string },
  ) => request<ProjectResponse>("/projects", "POST", data, token),

  update: (token: string | undefined, projectId: string, data: Record<string, unknown>) =>
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
    token: string | undefined,
    projectId: string,
    data: { prompt: string; room_type?: string; style?: string },
  ) => request<GenerationResult>(`/projects/${projectId}/generate`, "POST", data, token),

  edit: (
    token: string | undefined,
    projectId: string,
    data: { object_id: string; prompt: string },
  ) => request<GenerationResult>(`/projects/${projectId}/edit`, "POST", data, token),

  switchTheme: (
    token: string | undefined,
    projectId: string,
    data: { new_style: string; preserve_layout?: boolean },
  ) => request<GenerationResult>(`/projects/${projectId}/theme`, "POST", data, token),

  getLatest: (token: string | undefined, projectId: string) =>
    request<Record<string, unknown>>(`/projects/${projectId}/latest`, "GET", undefined, token),

  listVersions: (token: string | undefined, projectId: string) =>
    request<Record<string, unknown>>(`/projects/${projectId}/versions`, "GET", undefined, token),

  getVersion: (token: string | undefined, projectId: string, version: number) =>
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
  getLatest: (token: string | undefined, projectId: string) =>
    request<EstimateResult>(`/projects/${projectId}/estimates`, "GET", undefined, token),

  getForVersion: (token: string | undefined, projectId: string, version: number) =>
    request<EstimateResult>(
      `/projects/${projectId}/estimates/version/${version}`,
      "GET",
      undefined,
      token,
    ),
};

export interface ArchitectureSummaryResponse {
  status: string;
  snapshot: {
    id: string;
    repo_name: string;
    commit_hash: string;
    created_at: string;
  };
  freshness: {
    status: string;
    current_commit_hash: string;
    indexed_commit_hash: string;
  };
  overview: {
    modules: string[];
    file_count: number;
    node_count: number;
    top_node_types: Record<string, number>;
  };
  drift: {
    has_drift: boolean;
    commit_changed: boolean;
    changed_file_count: number;
    new_file_count: number;
    deleted_file_count: number;
    changed_files: string[];
    new_files: string[];
    deleted_files: string[];
  };
  quality: {
    score: number;
    issue_count: number;
    issues: Array<{
      type: string;
      severity: string;
      message: string;
      file_path: string;
    }>;
    recommendations: string[];
  };
  files: Array<{
    file_path: string;
    summary: string;
    file_type: string;
  }>;
}

export interface ArchitectureFeatureFlowResponse {
  status: string;
  feature: string;
  snapshot_id: string;
  steps: Array<{
    step: number;
    title: string;
    description: string;
    file_path: string;
    file_summary: string;
  }>;
  available_features?: string[];
}

export interface ArchitectureDependencyResponse {
  status: string;
  query: string;
  message?: string;
  focus?: {
    id: string;
    name: string;
    node_type: string;
    file_path: string;
    symbol_path: string;
  };
  incoming?: Array<{
    edge_type: string;
    id: string;
    name: string;
    node_type: string;
    file_path: string;
    symbol_path: string;
  }>;
  outgoing?: Array<{
    edge_type: string;
    id: string;
    name: string;
    node_type: string;
    file_path: string;
    symbol_path: string;
  }>;
}

export interface ArchitectureAskResponse {
  status: string;
  question: string;
  answer: string;
  citations: string[];
  mode: string;
}

export interface ArchitectureStatusResponse {
  status: string;
  snapshot_id: string;
  repo_name: string;
  indexed_commit_hash: string;
  current_commit_hash: string;
  freshness: string;
  drift: ArchitectureSummaryResponse["drift"];
  quality: ArchitectureSummaryResponse["quality"];
}

export interface ArchitectureQualityResponse {
  status: string;
  snapshot_id: string;
  freshness: string;
  score: number;
  issue_count: number;
  issues: Array<{
    type: string;
    severity: string;
    message: string;
    file_path: string;
  }>;
  recommendations: string[];
}

export interface ArchitectureRefreshResponse {
  status: string;
  mode: string;
  task_id?: string;
  snapshot_id?: string;
}

export const architecture = {
  index: (token?: string) =>
    request<Record<string, unknown>>("/architecture/index", "POST", undefined, token),

  summary: (token?: string) =>
    request<ArchitectureSummaryResponse>("/architecture/summary", "GET", undefined, token),

  status: (token?: string) =>
    request<ArchitectureStatusResponse>("/architecture/status", "GET", undefined, token),

  quality: (token?: string) =>
    request<ArchitectureQualityResponse>("/architecture/quality", "GET", undefined, token),

  featureFlow: (token: string | undefined, featureName: string) =>
    request<ArchitectureFeatureFlowResponse>(
      `/architecture/feature-flow/${featureName}`,
      "GET",
      undefined,
      token,
    ),

  dependencies: (token: string | undefined, query: string) =>
    request<ArchitectureDependencyResponse>(
      `/architecture/dependencies?query=${encodeURIComponent(query)}`,
      "GET",
      undefined,
      token,
    ),

  ask: (token: string | undefined, question: string) =>
    request<ArchitectureAskResponse>("/architecture/ask", "POST", { question }, token),

  refresh: (token: string | undefined, force = false) =>
    request<ArchitectureRefreshResponse>("/architecture/refresh", "POST", { force }, token),
};

const api = { auth, projects, generation, estimates, architecture };
export default api;
