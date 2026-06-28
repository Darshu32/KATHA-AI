// ── Project Type ───────────────────────────────────────────────────────────

/* Type union mirrors the backend ProjectTypeEnum (closed vocabulary).
 * Display data — labels, starter prompts, visual hints, primary/overflow
 * grouping — is fetched dynamically from the backend at app boot
 * (see lib/api-client.ts → projectTypes.list, useConfigStore in store.ts).
 * Keep the union value list in sync if you add a new type. */
export type ProjectType =
  | "residential"
  | "commercial"
  | "hospitality"
  | "office"
  | "retail"
  | "institutional"
  | "mixed_use"
  | "industrial"
  | "custom";

// ── Chat Types ─────────────────────────────────────────────────────────────

export type ChatMode = "quick" | "deep" | "auto";

export interface ChatMedia {
  url: string;
  thumbnail?: string;
  title: string;
  source: string;
  type: "ai-image" | "youtube" | "ai-video" | "image" | "gif";
  video_id?: string;
  channel?: string;
  width?: string;
  height?: string;
}

export interface ResearchPaper {
  title: string;
  url: string;
  year?: number;
  authors?: string;
  citations?: number;
  type: "paper";
}

export interface ReferenceLink {
  title: string;
  url: string;
  type: "article" | "standard" | "documentation" | "other";
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  citations?: string[];
  isStreaming?: boolean;
  images?: ChatMedia[];
  video?: ChatMedia | null;
  youtubeLinks?: ChatMedia[];
  researchPapers?: ResearchPaper[];
  referenceLinks?: ReferenceLink[];
  suggestions?: string[];
  mode?: ChatMode;
}

// BRD §1A — section status surfaced from the Deep-mode chat. Mirrors
// `BriefSectionStatus` from api-client; redeclared here so the type
// module stays self-contained (api-client imports from types, not the
// other way around).
export type ConvBriefSectionStatus = "pending" | "partial" | "confirmed";

export interface ConvBriefStatus {
  project_type?: ConvBriefSectionStatus;
  theme?: ConvBriefSectionStatus;
  space?: ConvBriefSectionStatus;
  requirements?: ConvBriefSectionStatus;
  regulatory?: ConvBriefSectionStatus;
}

export interface ConvBrief {
  // The 5 sections of the BRD §1A intake. All optional — the agent
  // populates fields turn-by-turn from the natural-language chat.
  project_type?: Record<string, unknown>;
  theme?: Record<string, unknown>;
  space?: Record<string, unknown>;
  requirements?: Record<string, unknown>;
  regulatory?: Record<string, unknown>;
  notes?: string;
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  createdAt: string;
  updatedAt: string;
  // Optional binding to the design workspace's active project at the
  // moment this conversation was created. Powers the small project
  // caption under each conversation in the sidebar so the architect
  // can see at a glance which project a chat belongs to. ``projectName``
  // is snapshotted at bind-time and may go briefly stale if the user
  // renames the project — refresh on demand later.
  projectId?: string;
  projectName?: string;
  // BRD §1A — the live design brief built from this conversation.
  // ``brief`` accumulates across Deep responses (deep-merge of section
  // dicts). ``briefStatus`` and ``briefMissing`` are replaced wholesale
  // by the latest Deep response that emitted them — they describe the
  // current state, not the union of all states.
  brief?: ConvBrief;
  briefStatus?: ConvBriefStatus;
  briefMissing?: string[];
}

export interface SuggestionChip {
  label: string;
  prompt: string;
}

// ── Workspace Types ────────────────────────────────────────────────────────

export type WorkspaceId = "knowledge-chat" | "image-generator";

// ── Image Generation Types ─────────────────────────────────────────────────

export type ArchTheme =
  | "modern"
  | "contemporary"
  | "minimalist"
  | "traditional"
  | "rustic"
  | "industrial"
  | "scandinavian"
  | "bohemian"
  | "luxury"
  | "coastal";

export type DrawingType =
  | "floor-plan"
  | "elevation"
  | "section"
  | "structural"
  | "electrical"
  | "plumbing"
  | "interior-layout"
  | "concept-moodboard"
  | "3d-render"
  | "working-drawings"
  | "structural-drawings"
  | "door-window-details"
  | "staircase-details"
  | "furniture-interior"
  | "finishing-drawings"
  | "mep-drawings"
  | "hvac-drawings";

export type ImageRatio = "1:1" | "16:9" | "4:3" | "3:4" | "9:16";
export type ImageQuality = "draft" | "standard" | "high" | "ultra";
export type CameraMode = "front" | "aerial" | "interior" | "eye-level";
export type LightingMode = "daylight" | "golden-hour" | "night" | "overcast";

export interface GeneratedImage {
  id: string;
  prompt: string;
  theme: ArchTheme;
  drawingType: DrawingType;
  ratio: ImageRatio;
  quality: ImageQuality;
  status: "generating" | "completed" | "failed";
  url?: string;
  createdAt: string;
}

/* What the design workspace stores for each generation in memory.
   Project-pipeline fields (projectId, version, graphData, estimate)
   are optional so legacy flat generations from the old image-only
   path continue to load cleanly; new generations carry them. */
export interface ImageGeneration {
  id: string;
  prompt: string;
  url?: string;
  timestamp: string;
  theme: ArchTheme;
  drawingType: DrawingType;
  ratio: ImageRatio;
  quality: ImageQuality;
  camera: CameraMode;
  lighting: LightingMode;
  width?: number;
  height?: number;

  // ── Project pipeline (Pass 1 of edit loop) ─────────────────────────
  // Present when a generation came from POST /projects/{id}/generate
  // rather than the legacy POST /images/generate. The graphData is the
  // structured design (objects + dimensions) that /edit operates on.
  projectId?: string;
  version?: number;
  versionId?: string;
  graphData?: unknown;
  estimate?: unknown;

  // ── Approximate object hotspots for click-to-edit on the image ─────
  // Each rect is normalised [0,1] over the rendered image. Computed
  // server-side from the design graph using a top-down projection —
  // honest about being approximate (Gemini's photoreal camera isn't
  // known), but stable across versions and clickable everywhere on
  // the visible canvas. Empty when the graph has no objects or no
  // resolvable room dimensions.
  objectsBbox?: Array<{
    id: string;
    name: string;
    type: string;
    x: number;
    y: number;
    w: number;
    h: number;
  }>;

  // BRD §1B / §11.3 — validation report from the post-generation pass.
  // Drives the Problems terminal tab. Optional for legacy generations
  // saved before the validator was wired into the pipeline.
  validation?: ValidationReport;

  // BRD §1B — MEP system cost rollup (HVAC + electrical + plumbing +
  // fire-fighting) sourced from ``mep_system_cost_*`` DB rows. Drives
  // the live "MEP systems" line in the Cost terminal tab. Optional —
  // legacy generations without a room area don't carry this.
  mepCostEstimate?: MepCostEstimate;

  // BRD §1B Building Code Integration — pre-rolled compliance summary
  // built server-side from the validation report + DB-backed advisory
  // rows (ECBC envelope, accessibility ramp, fire-safety). Drives the
  // right-sidebar "Code compliance" panel.
  codeCompliance?: CodeComplianceEntry[];
}

export interface MepCostSystemEntry {
  system: "hvac" | "electrical" | "plumbing" | "fire_fighting" | string;
  key: string;
  rate_inr_m2: { low?: number; high?: number };
  total_inr: { low?: number; high?: number };
}

export interface MepCostEstimate {
  area_m2: number;
  currency: string;
  currency_symbol?: string;
  jurisdiction: string;
  region?: string;
  systems: MepCostSystemEntry[];
  total_inr: { low: number; high: number };
  // Region-converted total (in `currency`) — prefer this for display.
  total?: { low: number; high: number };
}

// BRD §1B Building Code Integration — one compliance entry per code
// rule the generated design either fails or is expected to meet. Drives
// the right-sidebar "Code compliance" block. ``status``:
//   - ``fail`` — a hard NBC / code violation found by the validator
//   - ``warn`` — a softer band violation (e.g. door 700mm < 800mm min)
//   - ``info`` — advisory target the design should meet (ECBC envelope,
//                ramp slope, fire-safety req) — we don't validate inputs
//                today but surface the target so the architect knows it
export type CodeComplianceStatus = "fail" | "warn" | "info";

export interface CodeComplianceEntry {
  label: string;
  value: string;
  target: string;
  status: CodeComplianceStatus;
  code: string;
  source_section?: string | null;
  jurisdiction?: string | null;
}

// ── Design Graph Types (mirrors backend DesignObjectSchema) ───────────────

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

export interface Dimensions3D {
  length: number;
  width: number;
  height: number;
}

export interface DesignObject {
  id: string;
  type: string;
  name: string;
  position: Vec3;
  rotation: Vec3;
  dimensions: Dimensions3D;
  material: string;
  color: string;
}

export interface MaterialEntry {
  id: string;
  name: string;
  category: string;
  color: string;
}

export interface LightEntry {
  id: string;
  type: "ambient" | "point" | "directional" | "spot";
  position: Vec3;
  intensity: number;
  color: string;
}

export interface DesignRoom {
  type: string;
  dimensions: {
    length: number;
    width: number;
    height: number;
    unit?: string;
  };
}

export interface DesignStyle {
  primary: string;
  secondary: string[];
  color_palette?: string[];
  materials?: string[];
}

export interface DesignGraph {
  room: DesignRoom;
  style: DesignStyle;
  objects: DesignObject[];
  materials: MaterialEntry[];
  lighting: LightEntry[];
  render_prompt_2d?: string;
  render_prompt_3d?: string;
  constraints?: DesignConstraintEntry[];
}

// ── Constraint payloads surfaced on DesignGraph.constraints[] ───────────────

export type ValidationSeverity = "error" | "warning" | "suggestion";

export interface ValidationIssue {
  code: string;
  path: string;
  message: string;
  // BRD §1B / §9.3 citation fields. Present when the issue was raised
  // against a DB-backed standard (Stage 3B+) — earlier validators only
  // set code+path+message, so these stay optional.
  reference?: string;
  source_section?: string;
  jurisdiction?: string;
}

export interface ValidationReport {
  ok: boolean;
  summary: string;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  suggestions: ValidationIssue[];
}

export type RecommendationSeverity = "info" | "tip" | "nudge";

export interface RecommendationItem {
  id: string;
  category: string;
  severity: RecommendationSeverity;
  title: string;
  message: string;
  evidence?: Record<string, unknown>;
}

// ── Second-speed advisor (LLM-authored) — BRD §6 ──────────────────────────
//
// Returned by POST /projects/{id}/recommendations/full. Richer than the
// deterministic RecommendationItem: each entry carries confidence / impact /
// effort labels plus catalogue-grounded alternatives.

export interface FullRecAlternative {
  name: string;
  [k: string]: unknown;
}

export interface FullRecItem {
  category: string;
  title: string;
  detail: string;
  supporting?: unknown[];
  alternatives?: FullRecAlternative[];
  confidence: string;
  impact: string;
  effort: string;
}

export interface FullRecommendationsReport {
  id: string;
  name: string;
  model: string;
  recommendations: {
    header?: Record<string, unknown>;
    recommendations: FullRecItem[];
    ranking?: number[];
    assumptions?: string[];
  };
  validation?: Record<string, unknown>;
}

export interface ThemeApplierChange {
  path: string;
  rule: string;
  before: unknown;
  after: unknown;
  [k: string]: unknown;
}

export interface KnowledgeValidationConstraint extends ValidationReport {
  id: string;
  type: "knowledge_validation";
}

export interface ThemeChangesConstraint {
  id: string;
  type: "parametric_theme_changes";
  count: number;
  changes: ThemeApplierChange[];
}

export interface RecommendationsConstraint {
  id: string;
  type: "ai_recommendations";
  count: number;
  items: RecommendationItem[];
}

export type DesignConstraintEntry =
  | KnowledgeValidationConstraint
  | ThemeChangesConstraint
  | RecommendationsConstraint
  | { id?: string; type?: string; [k: string]: unknown };

// ── Diagram + Spec types ───────────────────────────────────────────────────

export interface DiagramPayload {
  id: string;
  name: string;
  format: "svg" | string;
  svg?: string;
  meta?: Record<string, unknown>;
  error?: string;
}

export interface MaterialSpecRow {
  name: string;
  grade: string;
  finish: string;
  color: string;
  supplier: string;
  lead_time_weeks: [number, number] | null;
  cost_inr: [number, number] | null;
  unit: string;
  properties?: Record<string, unknown>;
}

export interface SpecBundle {
  meta: {
    project_name: string;
    generated_at: string;
    room_type: string;
    theme: string;
    dimensions_m: { length?: number; width?: number; height?: number };
  };
  material: {
    primary_structure: MaterialSpecRow[];
    secondary_materials: MaterialSpecRow[];
    hardware: MaterialSpecRow[];
    upholstery: MaterialSpecRow[];
    finishing: MaterialSpecRow[];
    total_notes?: Record<string, unknown>;
  };
  manufacturing: Record<string, Record<string, unknown>>;
  mep: {
    hvac: Record<string, unknown>;
    electrical: Record<string, unknown>;
    plumbing: Record<string, unknown>;
  };
  cost: {
    status: string;
    currency: string;
    line_items: Array<Record<string, unknown>>;
    totals: { low?: number; high?: number; base?: number };
    assumptions: string[];
  };
  objects_count?: number;
}

export type ExportFormat =
  | "pdf" | "docx" | "xlsx" | "psd"
  | "dxf" | "obj" | "gltf" | "3dm"
  | "ifc" | "step" | "gcode";

export interface LayoutPreset {
  id: string;
  label: string;
  roomType: string;
  sqftRange: string;
  rooms: string;
  description: string;
  dims: { length: number; width: number };
}

export interface GenerationResult {
  project_id: string;
  version: number;
  graph_data: DesignGraph;
  estimate: Record<string, unknown> | null;
  status: string;
}

export interface FloorPlanResult {
  drawing_type: string;
  floor_plan: Record<string, unknown>;
  drawing: Record<string, unknown>;
  preview_svg: string;
  summary: string;
}

// ── Notes Types (Block-based Notebook) ────────────────────────────────────

export type NoteBlockType =
  | "heading-1"
  | "heading-2"
  | "heading-3"
  | "paragraph"
  | "bullet-list"
  | "numbered-list"
  | "toggle"
  | "callout"
  | "divider";

export type CalloutVariant = "info" | "tip" | "warning" | "important";

export interface NoteBlock {
  id: string;
  type: NoteBlockType;
  content: string;
  children?: NoteBlock[];
  collapsed?: boolean;
  calloutVariant?: CalloutVariant;
  indent: number;
  createdAt: string;
}

export interface NoteSection {
  id: string;
  title: string;
  date: string;
  sourceMessageId: string;
  sourceConversationId: string;
  blocks: NoteBlock[];
  // Phase 3 — user-applied tags. Always present; empty array for
  // newly auto-generated sections. Backend canonicalises (trim,
  // dedupe case-insensitive, max 20 tags / 40 chars each).
  tags: string[];
  // Phase 4 — auto-generated illustration for this section.
  // Currently a base64 data URI (Gemini); the field name is generic
  // so a future migration to a stored CDN URL is a value swap.
  // ``null`` when no image has been generated (or when the user
  // removed it). Capped at ~4MB on the wire.
  imageUrl: string | null;
}

export interface Notebook {
  id: string;
  sections: NoteSection[];
  updatedAt: string;
}
