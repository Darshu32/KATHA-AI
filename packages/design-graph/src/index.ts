// ── Core Types ──────────────────────────────────────────────────────────────

export type DesignType = "interior" | "architecture";
export type UnitSystem = "metric" | "imperial";
export type ProjectStatus = "draft" | "generating" | "ready" | "archived";
export type ChangeType = "initial" | "prompt_edit" | "manual_edit" | "theme_switch" | "material_change";
export type GenerationStatus = "queued" | "processing" | "completed" | "failed";

// ── Geometry Primitives ─────────────────────────────────────────────────────

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

export interface Dimensions {
  length: number;
  width: number;
  height: number;
}

// ── Style ───────────────────────────────────────────────────────────────────

export interface StyleProfile {
  primary: string;
  secondary: string[];
  colorPalette?: string[];
  materials?: string[];
}

export interface SiteInfo {
  unit: UnitSystem;
  location?: string;
  climateZone?: string;
}

// ── Design Objects ──────────────────────────────────────────────────────────

export interface DesignObject {
  id: string;
  type: string;
  name: string;
  position: Vec3;
  rotation: Vec3;
  dimensions: Dimensions;
  material: string;
  color: string;
  style?: string;
  parentId?: string;
  metadata?: Record<string, unknown>;
}

export interface MaterialDef {
  id: string;
  name: string;
  category: string;
  color: string;
  textureUrl?: string;
  unitRate?: number;
  unit?: string;
}

export interface LightingDef {
  id: string;
  type: "ambient" | "point" | "spot" | "directional" | "area";
  position: Vec3;
  intensity: number;
  color: string;
  targetId?: string;
}

export interface SpaceDef {
  id: string;
  name: string;
  roomType: string;
  dimensions: Dimensions;
  objects: string[]; // object IDs
}

// ── Asset Bundle ────────────────────────────────────────────────────────────

export interface AssetBundle {
  render2d: string[];
  scene3d: string[];
  masks: string[];
  renderPrompt2d?: string;
  renderPrompt3d?: string;
}

// ── Design Graph (the canonical model) ──────────────────────────────────────

export interface DesignGraph {
  projectId: string;
  version: number;
  designType: DesignType;
  style: StyleProfile;
  site: SiteInfo;
  spaces: SpaceDef[];
  objects: DesignObject[];
  materials: MaterialDef[];
  lighting: LightingDef[];
  constraints: Record<string, unknown>[];
  estimation: EstimationSummary;
  assets: AssetBundle;
}

// ── Estimation ──────────────────────────────────────────────────────────────

export interface EstimateLineItem {
  category: string;
  itemName: string;
  material: string;
  quantity: number;
  unit: string;
  unitRateLow: number;
  unitRateHigh: number;
  totalLow: number;
  totalHigh: number;
}

export interface EstimationSummary {
  status: "pending" | "computed" | "error";
  lineItems?: EstimateLineItem[];
  totalLow?: number;
  totalHigh?: number;
  currency?: string;
  assumptions?: string[];
}

// ── Project ─────────────────────────────────────────────────────────────────

export interface Project {
  id: string;
  name: string;
  description: string;
  status: ProjectStatus;
  latestVersion: number;
  createdAt: string;
  updatedAt: string;
}

export interface DesignVersion {
  id: string;
  version: number;
  changeType: ChangeType;
  changeSummary: string;
  graphData: DesignGraph;
  createdAt: string;
}

// ── 3D Scene (Three.js compatible) ──────────────────────────────────────────

export interface SceneGeometry {
  type: "box" | "plane" | "sphere" | "cylinder";
  args: number[];
}

export interface SceneMaterial {
  color: string;
  type: "standard" | "phong" | "lambert";
  opacity?: number;
  transparent?: boolean;
}

export interface SceneObject {
  id: string;
  type: string;
  name: string;
  geometry: SceneGeometry;
  position: [number, number, number];
  rotation: [number, number, number];
  material: SceneMaterial;
}

export interface SceneLight {
  id: string;
  type: string;
  position: [number, number, number];
  intensity: number;
  color: string;
}

export interface Scene3D {
  objects: SceneObject[];
  lights: SceneLight[];
}

// ── API Request/Response Types ──────────────────────────────────────────────

export interface PromptRequest {
  prompt: string;
  roomType?: string;
  style?: string;
  dimensions?: Dimensions;
}

export interface LocalEditRequest {
  objectId: string;
  prompt: string;
}

export interface ThemeSwitchRequest {
  newStyle: string;
  preserveLayout?: boolean;
}

export interface GenerationResponse {
  projectId: string;
  version: number;
  versionId: string;
  graphData: DesignGraph;
  estimate: EstimationSummary;
  status: GenerationStatus;
}
