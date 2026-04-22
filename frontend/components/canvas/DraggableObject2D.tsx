"use client";

import { useRef, useCallback } from "react";
import type { DesignObject } from "@/lib/types";
import { useDesignStore } from "@/lib/store";

interface Props {
  object: DesignObject;
  scale: number;
  roomLength: number;
  roomWidth: number;
  wireframe?: boolean;
}

const TYPE_ICONS: Record<string, string> = {
  sofa: "🛋️",
  chair: "🪑",
  bed: "🛏️",
  coffee_table: "☕",
  dining_table: "🍽️",
  desk: "🖥️",
  wardrobe: "🗄️",
  bookshelf: "📚",
  media_console: "📺",
  floor_lamp: "💡",
  plant: "🌿",
  rug: "▪️",
  counter: "🔲",
  wall_art: "🖼️",
};

export default function DraggableObject2D({ object, scale, roomLength, roomWidth, wireframe }: Props) {
  const {
    selectedObjectId,
    hoveredObjectId,
    snapToGrid,
    gridUnit,
    selectObject,
    hoverObject,
    updateObjectPosition,
    setDragging,
    pushUndo,
  } = useDesignStore();

  const dragRef = useRef<{ startX: number; startY: number; objStartX: number; objStartZ: number } | null>(null);
  const isSelected = selectedObjectId === object.id;
  const isHovered = hoveredObjectId === object.id;

  const svgX = object.position.x * scale;
  const svgY = object.position.z * scale;
  const w = object.dimensions.width * scale;
  const h = object.dimensions.length * scale;

  const snap = useCallback(
    (val: number) => (snapToGrid ? Math.round(val / gridUnit) * gridUnit : val),
    [snapToGrid, gridUnit],
  );

  const clamp = useCallback(
    (val: number, dimHalf: number, maxVal: number) =>
      Math.max(dimHalf, Math.min(maxVal - dimHalf, val)),
    [],
  );

  const handlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      e.stopPropagation();
      e.preventDefault();
      const svg = (e.target as SVGElement).ownerSVGElement;
      if (!svg) return;

      const pt = svg.createSVGPoint();
      pt.x = e.clientX;
      pt.y = e.clientY;
      const svgPt = pt.matrixTransform(svg.getScreenCTM()?.inverse());

      pushUndo();
      selectObject(object.id);
      setDragging(true, object.id);
      dragRef.current = {
        startX: svgPt.x,
        startY: svgPt.y,
        objStartX: object.position.x,
        objStartZ: object.position.z,
      };

      const handlePointerMove = (me: PointerEvent) => {
        if (!dragRef.current) return;
        const mvPt = svg.createSVGPoint();
        mvPt.x = me.clientX;
        mvPt.y = me.clientY;
        const mvSvgPt = mvPt.matrixTransform(svg.getScreenCTM()?.inverse());

        const dx = (mvSvgPt.x - dragRef.current.startX) / scale;
        const dy = (mvSvgPt.y - dragRef.current.startY) / scale;

        const newX = snap(clamp(dragRef.current.objStartX + dx, object.dimensions.width / 2, roomLength));
        const newZ = snap(clamp(dragRef.current.objStartZ + dy, object.dimensions.length / 2, roomWidth));

        updateObjectPosition(object.id, { x: newX, y: object.position.y, z: newZ });
      };

      const handlePointerUp = () => {
        dragRef.current = null;
        setDragging(false);
        window.removeEventListener("pointermove", handlePointerMove);
        window.removeEventListener("pointerup", handlePointerUp);
      };

      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", handlePointerUp);
    },
    [object, scale, roomLength, roomWidth, snap, clamp, selectObject, setDragging, updateObjectPosition, pushUndo],
  );

  const icon = TYPE_ICONS[object.type] ?? "▫️";
  const fontSize = Math.max(8, Math.min(14, Math.min(w, h) * 0.35));

  return (
    <g
      onPointerDown={handlePointerDown}
      onPointerEnter={() => hoverObject(object.id)}
      onPointerLeave={() => hoverObject(null)}
      style={{ cursor: "grab" }}
    >
      <rect
        x={svgX - w / 2}
        y={svgY - h / 2}
        width={w}
        height={h}
        rx={2}
        ry={2}
        fill={wireframe ? "none" : object.color}
        fillOpacity={wireframe ? 0 : 0.6}
        stroke={isSelected ? "#3b82f6" : isHovered ? "#6b7280" : wireframe ? "#374151" : "#9ca3af"}
        strokeWidth={isSelected ? 2 : wireframe ? 1.5 : 1}
        strokeDasharray={isSelected ? "4 2" : "none"}
      />
      <text
        x={svgX}
        y={svgY - fontSize * 0.3}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={fontSize + 2}
        style={{ pointerEvents: "none", userSelect: "none" }}
      >
        {icon}
      </text>
      <text
        x={svgX}
        y={svgY + fontSize * 0.8}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={Math.max(6, fontSize * 0.65)}
        fill="#374151"
        fontWeight={isSelected ? 600 : 400}
        style={{ pointerEvents: "none", userSelect: "none" }}
      >
        {object.name}
      </text>
      {isSelected && (
        <text
          x={svgX}
          y={svgY + h / 2 + 10}
          textAnchor="middle"
          fontSize={7}
          fill="#6b7280"
          style={{ pointerEvents: "none" }}
        >
          {object.dimensions.width.toFixed(1)}' x {object.dimensions.length.toFixed(1)}'
        </text>
      )}
    </g>
  );
}
