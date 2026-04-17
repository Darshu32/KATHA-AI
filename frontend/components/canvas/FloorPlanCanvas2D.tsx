"use client";

import { useRef, useCallback, useEffect } from "react";
import type { DesignGraph } from "@/lib/types";
import { useDesignStore } from "@/lib/store";
import DraggableObject2D from "./DraggableObject2D";
import DimensionLines2D from "./DimensionLines2D";
import CanvasToolbar from "./CanvasToolbar";

interface Props {
  graph: DesignGraph;
}

const PADDING = 40;
const BASE_SCALE = 32;

export default function FloorPlanCanvas2D({ graph }: Props) {
  const { zoom, showGrid, selectObject, setZoom } = useDesignStore();
  const svgRef = useRef<SVGSVGElement>(null);

  const rL = graph.room.dimensions.length;
  const rW = graph.room.dimensions.width;
  const scale = BASE_SCALE * zoom;

  const svgW = rL * scale + PADDING * 2;
  const svgH = rW * scale + PADDING * 2;

  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.08 : 0.08;
      setZoom(zoom + delta);
    },
    [zoom, setZoom],
  );

  const handleBgClick = useCallback(() => {
    selectObject(null);
  }, [selectObject]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "z") {
        e.preventDefault();
        useDesignStore.getState().undo();
      }
      if (e.key === "Escape") {
        selectObject(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectObject]);

  const floorObjects = graph.objects.filter((o) => o.position.y < 1);

  return (
    <div className="relative w-full h-full flex items-center justify-center bg-gray-50 overflow-hidden">
      <CanvasToolbar />

      <svg
        ref={svgRef}
        viewBox={`${-PADDING} ${-PADDING} ${svgW} ${svgH}`}
        className="max-w-full max-h-full"
        style={{ width: "100%", height: "100%" }}
        onWheel={handleWheel}
      >
        {/* Background click area */}
        <rect
          x={-PADDING}
          y={-PADDING}
          width={svgW}
          height={svgH}
          fill="#f9fafb"
          onClick={handleBgClick}
        />

        {/* Grid */}
        {showGrid && (
          <g opacity={0.15}>
            {Array.from({ length: Math.ceil(rL / 1) + 1 }, (_, i) => (
              <line
                key={`gv${i}`}
                x1={i * scale}
                y1={0}
                x2={i * scale}
                y2={rW * scale}
                stroke="#9ca3af"
                strokeWidth={i % 5 === 0 ? 0.8 : 0.3}
              />
            ))}
            {Array.from({ length: Math.ceil(rW / 1) + 1 }, (_, i) => (
              <line
                key={`gh${i}`}
                x1={0}
                y1={i * scale}
                x2={rL * scale}
                y2={i * scale}
                stroke="#9ca3af"
                strokeWidth={i % 5 === 0 ? 0.8 : 0.3}
              />
            ))}
          </g>
        )}

        {/* Floor fill */}
        <rect
          x={0}
          y={0}
          width={rL * scale}
          height={rW * scale}
          fill="#faf8f5"
          stroke="none"
          onClick={handleBgClick}
        />

        {/* Walls */}
        <rect
          x={0}
          y={0}
          width={rL * scale}
          height={rW * scale}
          fill="none"
          stroke="#1f2937"
          strokeWidth={3}
        />

        {/* Wall hatch marks at corners */}
        {[
          [0, 0],
          [rL * scale, 0],
          [0, rW * scale],
          [rL * scale, rW * scale],
        ].map(([cx, cy], i) => (
          <circle key={i} cx={cx} cy={cy} r={3} fill="#1f2937" />
        ))}

        {/* Furniture objects */}
        {floorObjects.map((obj) => (
          <DraggableObject2D
            key={obj.id}
            object={obj}
            scale={scale}
            roomLength={rL}
            roomWidth={rW}
          />
        ))}

        {/* Dimension lines */}
        <DimensionLines2D room={graph.room} objects={floorObjects} scale={scale} />

        {/* Scale indicator */}
        <g transform={`translate(${rL * scale - 60}, ${rW * scale + 14})`}>
          <line x1={0} y1={0} x2={scale} y2={0} stroke="#6b7280" strokeWidth={1} />
          <line x1={0} y1={-3} x2={0} y2={3} stroke="#6b7280" strokeWidth={1} />
          <line x1={scale} y1={-3} x2={scale} y2={3} stroke="#6b7280" strokeWidth={1} />
          <text x={scale / 2} y={10} textAnchor="middle" fontSize={8} fill="#6b7280">
            1 ft
          </text>
        </g>

        {/* Room label */}
        <text x={rL * scale / 2} y={-6} textAnchor="middle" fontSize={10} fill="#9ca3af" fontWeight={500}>
          {graph.room.type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())} — {rL}' x {rW}'
        </text>
      </svg>
    </div>
  );
}
