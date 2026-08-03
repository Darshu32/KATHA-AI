"use client";

/* Editable 2D plan — the architect-native editing surface. A top-down view of
 * the spec: each object is a draggable footprint (length × width at its x/z).
 * Dragging updates the object's position on the spec via the same proven
 * PATCH .../objects/{id}/position endpoint the 3D viewport uses — so the plan,
 * the 3D model, and the render all stay views of one source of truth.
 *
 * Pure SVG + pointer math (no WebGL), so it renders anywhere. Screen→world
 * mapping goes through the SVG CTM, which stays correct under letterboxing. */

import { useMemo, useRef, useState } from "react";

import { design as designApi } from "@/lib/api-client";
import { useAuthStore } from "@/lib/store";

type Vec = { x: number; y: number; z: number };
type Dim = { length?: number; width?: number; height?: number; unit?: string };
type Obj = { id?: string; type?: string; position?: Partial<Vec>; dimensions?: Dim };
type Graph = { objects?: Obj[] } | null | undefined;

const UNIT: Record<string, number> = { mm: 1e-3, cm: 1e-2, m: 1, metre: 1, meter: 1, ft: 0.3048, feet: 0.3048 };
function toM(v: unknown, unit?: string): number {
  const n = typeof v === "number" ? v : parseFloat(String(v));
  if (!isFinite(n)) return 0;
  return unit ? n * (UNIT[unit.toLowerCase()] ?? 1) : Math.abs(n) > 30 ? n / 1000 : n;
}

// Structural elements aren't draggable furniture — show them faintly as context.
const STRUCTURAL = new Set(["building", "wall", "floor", "slab", "ground", "atrium", "driveway"]);

export default function DesignPlanEditor({
  projectId,
  graph,
  selectedObjectId = null,
  onSelectObject,
}: {
  projectId: string;
  graph?: unknown;
  selectedObjectId?: string | null;
  onSelectObject?: (id: string | null) => void;
}) {
  const token = useAuthStore((s) => s.token);
  const svgRef = useRef<SVGSVGElement>(null);
  // Live drag state lives in a ref (not React state) so pointerup reads the
  // final position synchronously — state updates are batched and would be stale.
  const drag = useRef<{ id: string; ox: number; oz: number; lx: number; lz: number; cx?: number; cz?: number } | null>(null);
  const [live, setLive] = useState<Record<string, { x: number; z: number }>>({});

  const objects = useMemo(
    () => ((graph as Graph)?.objects ?? []).filter((o) => o?.id && o.position),
    [graph],
  );

  const foot = objects.map((o) => {
    const d = o.dimensions ?? {};
    const l = toM(d.length, d.unit) || 0.5;
    const w = toM(d.width, d.unit) || 0.5;
    const p = live[o.id!] ?? { x: o.position!.x ?? 0, z: o.position!.z ?? 0 };
    return { id: o.id!, type: String(o.type ?? ""), l, w, x: p.x, z: p.z, structural: STRUCTURAL.has(String(o.type ?? "").toLowerCase()) };
  });

  // World bounds → viewBox (1 SVG unit = 1 metre).
  const xs = foot.flatMap((f) => [f.x - f.l / 2, f.x + f.l / 2]);
  const zs = foot.flatMap((f) => [f.z - f.w / 2, f.z + f.w / 2]);
  const pad = 1.5;
  const minX = (xs.length ? Math.min(...xs) : 0) - pad;
  const maxX = (xs.length ? Math.max(...xs) : 10) + pad;
  const minZ = (zs.length ? Math.min(...zs) : 0) - pad;
  const maxZ = (zs.length ? Math.max(...zs) : 10) + pad;
  const vbW = maxX - minX;
  const vbH = maxZ - minZ;
  const font = Math.max(vbW, vbH) * 0.022;

  const toWorld = (clientX: number, clientY: number) => {
    const svg = svgRef.current;
    const m = svg?.getScreenCTM();
    if (!svg || !m) return null;
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const p = pt.matrixTransform(m.inverse());
    return { x: p.x, z: p.y }; // SVG x→world x, SVG y→world z
  };

  const onDown = (e: React.PointerEvent, f: (typeof foot)[number]) => {
    if (f.structural) return;
    e.stopPropagation();
    try {
      (e.target as Element).setPointerCapture?.(e.pointerId);
    } catch {
      /* pointer capture is best-effort */
    }
    onSelectObject?.(f.id);
    const w = toWorld(e.clientX, e.clientY);
    if (w) drag.current = { id: f.id, ox: f.x, oz: f.z, lx: w.x, lz: w.z };
  };
  const onMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    const w = toWorld(e.clientX, e.clientY);
    if (!w) return;
    const { id, ox, oz, lx, lz } = drag.current;
    const nx = ox + (w.x - lx);
    const nz = oz + (w.z - lz);
    drag.current.cx = nx;
    drag.current.cz = nz;
    setLive((p) => ({ ...p, [id]: { x: nx, z: nz } }));
  };
  const onUp = () => {
    const d = drag.current;
    drag.current = null;
    if (!d || d.cx === undefined || d.cz === undefined) return; // no actual move
    const base = objects.find((o) => o.id === d.id)?.position;
    designApi
      .updatePosition(token as string, projectId, d.id, { x: d.cx, y: base?.y ?? 0, z: d.cz })
      .catch(() => {});
  };

  return (
    <div className="absolute inset-0 bg-paper grid-paper">
      <svg
        ref={svgRef}
        viewBox={`${minX} ${minZ} ${vbW} ${vbH}`}
        preserveAspectRatio="xMidYMid meet"
        className="w-full h-full touch-none"
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerLeave={onUp}
        onClick={() => onSelectObject?.(null)}
      >
        {foot.map((f) => {
          const sel = f.id === selectedObjectId;
          const fill = f.structural
            ? "rgba(26,26,26,0.035)"
            : sel
              ? "rgba(200,54,45,0.14)"
              : "rgba(26,26,26,0.07)";
          const stroke = sel ? "#C8362D" : f.structural ? "#9a9a95" : "#1A1A1A";
          return (
            <g
              key={f.id}
              onPointerDown={(e) => onDown(e, f)}
              onClick={(e) => e.stopPropagation()}
              style={{ cursor: f.structural ? "default" : "move" }}
            >
              <rect
                x={f.x - f.l / 2}
                y={f.z - f.w / 2}
                width={f.l}
                height={f.w}
                fill={fill}
                stroke={stroke}
                strokeWidth={sel ? 2 : 1}
                vectorEffect="non-scaling-stroke"
              />
              {!f.structural ? (
                <text
                  x={f.x}
                  y={f.z}
                  fontSize={font}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fill="#1A1A1A"
                  style={{ pointerEvents: "none", userSelect: "none" }}
                >
                  {f.type}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
      <div className="absolute bottom-2 left-2 pointer-events-none font-mono text-[9px] uppercase tracking-[0.12em] text-ink-mute/80">
        plan · drag a piece to move · click empty to deselect
      </div>
    </div>
  );
}
