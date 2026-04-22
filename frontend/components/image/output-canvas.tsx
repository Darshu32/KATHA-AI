"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { ImageIcon, RefreshCw, Eye, X } from "lucide-react";
import { useImageGenStore, useDesignStore } from "@/lib/store";
import { chat as chatApi } from "@/lib/api-client";

const FloorPlanCanvas2D = dynamic(
  () => import("@/components/canvas/FloorPlanCanvas2D"),
  { ssr: false },
);
const Scene3DCanvas = dynamic(
  () => import("@/components/canvas/Scene3DCanvas"),
  { ssr: false },
);

export default function OutputCanvas() {
  const { viewMode, isGenerating, camera, lighting } = useImageGenStore();
  const { activeGraph, isLoading } = useDesignStore();
  const [renderUrl, setRenderUrl] = useState<string | null>(null);
  const [rendering, setRendering] = useState(false);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [renderVisible, setRenderVisible] = useState(false);

  // Reset the photoreal overlay whenever the graph changes.
  useEffect(() => {
    setRenderUrl(null);
    setRenderError(null);
    setRenderVisible(false);
  }, [activeGraph]);

  const renderPrompt = activeGraph
    ? (viewMode === "3d" ? activeGraph.render_prompt_3d : activeGraph.render_prompt_2d) ||
      [
        activeGraph.render_prompt_2d,
        activeGraph.render_prompt_3d,
      ].find(Boolean)
    : undefined;

  const handleRenderPhoto = async () => {
    if (!renderPrompt || rendering) return;
    setRendering(true);
    setRenderError(null);
    try {
      const fullPrompt = `${renderPrompt}. Camera: ${camera}. Lighting: ${lighting}. View: ${viewMode.toUpperCase()}.`;
      const res = await chatApi.generateImage(fullPrompt);
      if (res?.image?.url) {
        setRenderUrl(res.image.url);
        setRenderVisible(true);
      } else {
        setRenderError("No image returned — check OPENAI_API_KEY / NANO_BANANA config.");
      }
    } catch (err) {
      setRenderError(err instanceof Error ? err.message : "Render failed");
    } finally {
      setRendering(false);
    }
  };

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
    <div className="flex-1 min-h-0 relative">
      {viewMode === "2d" ? (
        <FloorPlanCanvas2D graph={activeGraph} />
      ) : (
        <Scene3DCanvas graph={activeGraph} />
      )}

      {renderPrompt && (
        <button
          onClick={handleRenderPhoto}
          disabled={rendering}
          className="absolute top-3 right-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[12px] font-medium disabled:opacity-50"
          style={{
            backgroundColor: "var(--ink)",
            color: "var(--paper)",
            boxShadow: "0 1px 2px rgba(17,17,16,0.1)",
          }}
          title={rendering ? "Rendering…" : "Generate a photoreal render from this view's prompt"}
        >
          {rendering ? <RefreshCw size={13} className="animate-spin" /> : <Eye size={13} />}
          {rendering ? "Rendering…" : "Photoreal"}
        </button>
      )}

      {renderError && (
        <div
          className="absolute top-14 right-3 max-w-xs px-3 py-2 rounded-md text-[11px]"
          style={{ backgroundColor: "var(--paper-2)", border: "1px solid var(--rule)", color: "var(--ink-2)" }}
        >
          {renderError}
        </div>
      )}

      {renderUrl && renderVisible && (
        <div className="absolute inset-0 bg-black/40 flex items-center justify-center p-8 z-10">
          <div className="relative max-w-4xl max-h-full">
            <button
              onClick={() => setRenderVisible(false)}
              className="absolute -top-10 right-0 inline-flex items-center gap-1.5 text-white text-[12px]"
            >
              <X size={14} /> Close
            </button>
            <img
              src={renderUrl}
              alt="Photoreal render"
              className="max-w-full max-h-[80vh] rounded-lg shadow-2xl"
            />
            <p className="mt-2 text-[11px] text-white/80 font-mono">
              {viewMode.toUpperCase()} · {camera} · {lighting}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
