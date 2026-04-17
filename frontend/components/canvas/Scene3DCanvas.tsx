"use client";

import dynamic from "next/dynamic";
import type { DesignGraph } from "@/lib/types";

const Scene3DInner = dynamic(() => import("./Scene3DInner"), { ssr: false });

interface Props {
  graph: DesignGraph;
}

export default function Scene3DCanvas({ graph }: Props) {
  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }} className="bg-gray-100">
      <div style={{ position: "absolute", inset: 0 }}>
        <Scene3DInner graph={graph} />
      </div>
    </div>
  );
}
