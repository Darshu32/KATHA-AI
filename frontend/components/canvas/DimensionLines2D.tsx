"use client";

import { useMemo } from "react";
import type { DesignObject, DesignRoom } from "@/lib/types";
import { useDesignStore } from "@/lib/store";

interface Props {
  room: DesignRoom;
  objects: DesignObject[];
  scale: number;
}

function DimLine({
  x1, y1, x2, y2, label, color = "#ef4444",
}: {
  x1: number; y1: number; x2: number; y2: number; label: string; color?: string;
}) {
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  return (
    <g>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={0.8} strokeDasharray="3 2" opacity={0.7} />
      <circle cx={x1} cy={y1} r={1.5} fill={color} opacity={0.7} />
      <circle cx={x2} cy={y2} r={1.5} fill={color} opacity={0.7} />
      <rect x={mx - 16} y={my - 7} width={32} height={14} rx={3} fill="white" stroke={color} strokeWidth={0.5} opacity={0.9} />
      <text x={mx} y={my + 1} textAnchor="middle" dominantBaseline="central" fontSize={7} fill={color} fontWeight={500} style={{ pointerEvents: "none" }}>
        {label}
      </text>
    </g>
  );
}

export default function DimensionLines2D({ room, objects, scale }: Props) {
  const { selectedObjectId, showDimensions } = useDesignStore();
  const rL = room.dimensions.length;
  const rW = room.dimensions.width;

  const roomDims = useMemo(() => {
    const rLs = rL * scale;
    const rWs = rW * scale;
    return (
      <g>
        {/* Top */}
        <DimLine x1={0} y1={-12} x2={rLs} y2={-12} label={`${rL}'`} color="#6366f1" />
        {/* Left */}
        <DimLine x1={-12} y1={0} x2={-12} y2={rWs} label={`${rW}'`} color="#6366f1" />
      </g>
    );
  }, [rL, rW, scale]);

  const selectedDims = useMemo(() => {
    if (!selectedObjectId) return null;
    const obj = objects.find((o) => o.id === selectedObjectId);
    if (!obj) return null;

    const cx = obj.position.x * scale;
    const cy = obj.position.z * scale;
    const hw = (obj.dimensions.width / 2) * scale;
    const hh = (obj.dimensions.length / 2) * scale;

    const leftDist = obj.position.x - obj.dimensions.width / 2;
    const rightDist = rL - (obj.position.x + obj.dimensions.width / 2);
    const topDist = obj.position.z - obj.dimensions.length / 2;
    const bottomDist = rW - (obj.position.z + obj.dimensions.length / 2);

    return (
      <g>
        {leftDist > 0.3 && (
          <DimLine x1={0} y1={cy} x2={cx - hw} y2={cy} label={`${leftDist.toFixed(1)}'`} />
        )}
        {rightDist > 0.3 && (
          <DimLine x1={cx + hw} y1={cy} x2={rL * scale} y2={cy} label={`${rightDist.toFixed(1)}'`} />
        )}
        {topDist > 0.3 && (
          <DimLine x1={cx} y1={0} x2={cx} y2={cy - hh} label={`${topDist.toFixed(1)}'`} />
        )}
        {bottomDist > 0.3 && (
          <DimLine x1={cx} y1={cy + hh} x2={cx} y2={rW * scale} label={`${bottomDist.toFixed(1)}'`} />
        )}
      </g>
    );
  }, [selectedObjectId, objects, rL, rW, scale]);

  if (!showDimensions) return null;

  return (
    <g>
      {roomDims}
      {selectedDims}
    </g>
  );
}
