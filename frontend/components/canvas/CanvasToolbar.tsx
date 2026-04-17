"use client";

import {
  ZoomIn,
  ZoomOut,
  Maximize,
  Grid3x3,
  Ruler,
  Magnet,
  Undo2,
} from "lucide-react";
import { useDesignStore } from "@/lib/store";

export default function CanvasToolbar() {
  const {
    zoom,
    showGrid,
    showDimensions,
    snapToGrid,
    undoStack,
    setZoom,
    setShowGrid,
    setShowDimensions,
    setSnapToGrid,
    undo,
  } = useDesignStore();

  const buttons = [
    { icon: ZoomIn, label: "Zoom In", onClick: () => setZoom(zoom + 0.15), active: false },
    { icon: ZoomOut, label: "Zoom Out", onClick: () => setZoom(zoom - 0.15), active: false },
    { icon: Maximize, label: "Fit", onClick: () => setZoom(1), active: false },
    { icon: Grid3x3, label: "Grid", onClick: () => setShowGrid(!showGrid), active: showGrid },
    { icon: Ruler, label: "Dims", onClick: () => setShowDimensions(!showDimensions), active: showDimensions },
    { icon: Magnet, label: "Snap", onClick: () => setSnapToGrid(!snapToGrid), active: snapToGrid },
    { icon: Undo2, label: "Undo", onClick: undo, active: false, disabled: undoStack.length === 0 },
  ];

  return (
    <div className="absolute top-3 left-3 flex items-center gap-1 bg-white/95 backdrop-blur border border-gray-200 rounded-xl px-2 py-1.5 shadow-sm z-10">
      {buttons.map((btn, i) => (
        <button
          key={btn.label}
          onClick={btn.onClick}
          disabled={btn.disabled}
          title={btn.label}
          className={`p-1.5 rounded-lg transition-colors ${
            btn.active
              ? "bg-slate-900 text-white"
              : "text-gray-500 hover:text-gray-800 hover:bg-gray-100"
          } ${btn.disabled ? "opacity-30 cursor-not-allowed" : ""}`}
        >
          <btn.icon size={14} />
        </button>
      ))}
      <span className="text-[10px] text-gray-400 ml-1 tabular-nums">{Math.round(zoom * 100)}%</span>
    </div>
  );
}
