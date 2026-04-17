"use client";

import dynamic from "next/dynamic";
import { ImageIcon, RefreshCw } from "lucide-react";
import { useImageGenStore, useDesignStore } from "@/lib/store";

const FloorPlanCanvas2D = dynamic(
  () => import("@/components/canvas/FloorPlanCanvas2D"),
  { ssr: false },
);
const Scene3DCanvas = dynamic(
  () => import("@/components/canvas/Scene3DCanvas"),
  { ssr: false },
);

export default function OutputCanvas() {
  const { viewMode, isGenerating } = useImageGenStore();
  const { activeGraph, isLoading } = useDesignStore();

  if (isLoading || isGenerating) {
    return (
      <div className="flex-1 flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <RefreshCw size={28} className="text-gray-400 animate-spin mx-auto mb-3" />
          <p className="text-sm text-gray-500">Generating design...</p>
        </div>
      </div>
    );
  }

  if (!activeGraph) {
    return (
      <div className="flex-1 flex items-center justify-center bg-gray-50">
        <div className="text-center max-w-sm">
          <div className="w-16 h-16 rounded-2xl bg-gray-50 border border-gray-100 flex items-center justify-center mx-auto mb-4">
            <ImageIcon size={28} className="text-gray-300" />
          </div>
          <h3 className="text-lg font-semibold text-gray-800 mb-2">
            Architecture Design Studio
          </h3>
          <p className="text-sm text-gray-500 leading-relaxed">
            Enter a prompt above to generate an interactive floor plan.
            You can drag furniture, change materials, and switch between 2D and 3D views.
          </p>
          <div className="grid grid-cols-2 gap-3 mt-6">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="aspect-video bg-gradient-to-br from-gray-50 to-gray-100 rounded-xl border border-gray-200"
              />
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-0">
      {viewMode === "2d" ? (
        <FloorPlanCanvas2D graph={activeGraph} />
      ) : (
        <Scene3DCanvas graph={activeGraph} />
      )}
    </div>
  );
}
