"use client";

import dynamic from "next/dynamic";
import type { DesignGraph } from "@/lib/types";
import { useImageGenStore } from "@/lib/store";

const Scene3DInner = dynamic(() => import("./Scene3DInner"), { ssr: false });

interface Props {
  graph: DesignGraph;
}

const CAMERA_LABELS: Record<string, string> = {
  front: "Front",
  aerial: "Aerial",
  interior: "Interior",
  "eye-level": "Eye-level",
};

const LIGHTING_LABELS: Record<string, string> = {
  daylight: "Daylight",
  "golden-hour": "Golden hour",
  night: "Night",
  overcast: "Overcast",
};

export default function Scene3DCanvas({ graph }: Props) {
  const { camera, lighting } = useImageGenStore();

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }} className="bg-gray-100">
      <div style={{ position: "absolute", inset: 0 }}>
        <Scene3DInner graph={graph} />
      </div>

      {/* Camera + lighting badge so demo viewers can see the active view-matrix */}
      <div
        className="absolute top-3 left-3 inline-flex items-center gap-2 px-2.5 py-1 rounded-full pointer-events-none"
        style={{
          backgroundColor: "rgba(17,17,16,0.78)",
          color: "#fafafa",
          fontFamily: "var(--mono)",
          fontSize: 10.5,
          letterSpacing: "0.04em",
          backdropFilter: "blur(4px)",
        }}
      >
        <span>CAM · {CAMERA_LABELS[camera] ?? camera}</span>
        <span style={{ opacity: 0.5 }}>|</span>
        <span>LIGHT · {LIGHTING_LABELS[lighting] ?? lighting}</span>
      </div>
    </div>
  );
}
