export type DesignType = "interior" | "architecture";
export type UnitSystem = "metric" | "imperial";

export interface StyleProfile {
  primary: string;
  secondary: string[];
}

export interface SiteInfo {
  unit: UnitSystem;
  location?: string;
  climateZone?: string;
}

export interface DesignNode {
  id: string;
  [key: string]: unknown;
}

export interface AssetBundle {
  render2d: string[];
  scene3d: string[];
  masks: string[];
}

export interface DesignGraph {
  projectId: string;
  version: number;
  designType: DesignType;
  style: StyleProfile;
  site: SiteInfo;
  spaces: DesignNode[];
  geometry: DesignNode[];
  objects: DesignNode[];
  materials: DesignNode[];
  lighting: DesignNode[];
  constraints: DesignNode[];
  estimation: Record<string, unknown>;
  assets: AssetBundle;
}

export const starterDesignGraph: DesignGraph = {
  projectId: "proj_001",
  version: 1,
  designType: "interior",
  style: {
    primary: "Warm Contemporary",
    secondary: ["traditional", "textured"]
  },
  site: {
    unit: "metric"
  },
  spaces: [
    {
      id: "space_001",
      name: "Living Area"
    }
  ],
  geometry: [],
  objects: [],
  materials: [],
  lighting: [],
  constraints: [],
  estimation: {
    status: "pending"
  },
  assets: {
    render2d: [],
    scene3d: [],
    masks: []
  }
};
