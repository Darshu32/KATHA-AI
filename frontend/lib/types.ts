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
