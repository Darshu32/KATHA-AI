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
}

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
