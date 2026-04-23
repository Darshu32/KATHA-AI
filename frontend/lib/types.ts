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

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  createdAt: string;
  updatedAt: string;
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

export interface ImageGeneration {
  id: string;
  prompt: string;
  negativePrompt: string;
  theme: ArchTheme;
  drawingType: DrawingType;
  ratio: ImageRatio;
  quality: ImageQuality;
  images: GeneratedImage[];
  createdAt: string;
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
  | "pdf" | "docx" | "xlsx"
  | "dxf" | "obj" | "gltf"
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
}

export interface Notebook {
  id: string;
  sections: NoteSection[];
  updatedAt: string;
}
