"use client";

/* Editable 2D plan — the architect-native editing surface. A top-down view of
 * the spec: each object is a draggable footprint (length × width at its x/z).
 * Dragging updates the object's position on the spec via the same proven
 * PATCH .../objects/{id}/position endpoint the 3D viewport uses — so the plan,
 * the 3D model, and the render all stay views of one source of truth.
 *
 * Pure SVG + pointer math (no WebGL), so it renders anywhere. Screen→world
 * mapping goes through the SVG CTM, which stays correct under letterboxing. */

import { useEffect, useMemo, useRef, useState } from "react";

import { design as designApi } from "@/lib/api-client";
import { type GcsConstraint, preloadSolver, solveLayout } from "@/lib/gcs-solver";
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
  const [snap, setSnap] = useState(true);
  const [undoStack, setUndoStack] = useState<{ id: string; from: Vec; to: Vec }[]>([]);
  const [redoStack, setRedoStack] = useState<{ id: string; from: Vec; to: Vec }[]>([]);
  const SNAP = 0.1; // metres — 10 cm grid
  const [guides, setGuides] = useState<{ x: number | null; z: number | null }>({ x: null, z: null });
  const [constraints, setConstraints] = useState<GcsConstraint[]>([]);

  // Warm the planegcs wasm up front so the first constrained drag isn't blocked.
  useEffect(() => {
    preloadSolver();
  }, []);

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
    // Shift-click a second piece links it to the selected one (no drag).
    if (e.shiftKey && selectedObjectId && selectedObjectId !== f.id) {
      linkObjects(selectedObjectId, f.id);
      return;
    }
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
    let nx = ox + (w.x - lx);
    let nz = oz + (w.z - lz);
    if (snap) {
      nx = Math.round(nx / SNAP) * SNAP;
      nz = Math.round(nz / SNAP) * SNAP;
    }
    // Smart alignment: snap this piece's edges/centre to another piece's
    // edges/centre when within threshold (overrides the grid) + show a guide.
    const me = foot.find((f) => f.id === id);
    let gx: number | null = null;
    let gz: number | null = null;
    if (me) {
      const T = Math.max(vbW, vbH) * 0.012;
      const xs: number[] = [];
      const zs: number[] = [];
      for (const o of foot) {
        if (o.id === id) continue;
        xs.push(o.x - o.l / 2, o.x, o.x + o.l / 2);
        zs.push(o.z - o.w / 2, o.z, o.z + o.w / 2);
      }
      const best = (n: number, half: number, es: number[]) => {
        const mine = [n - half, n, n + half];
        let b: { d: number; g: number } | null = null;
        for (const e of es)
          for (const m of mine) {
            const d = e - m;
            if (Math.abs(d) < T && (!b || Math.abs(d) < Math.abs(b.d))) b = { d, g: e };
          }
        return b;
      };
      const bx = best(nx, me.l / 2, xs);
      if (bx) { nx += bx.d; gx = bx.g; }
      const bz = best(nz, me.w / 2, zs);
      if (bz) { nz += bz.d; gz = bz.g; }
    }
    setGuides({ x: gx, z: gz });
    drag.current.cx = nx;
    drag.current.cz = nz;
    setLive((p) => ({ ...p, [id]: { x: nx, z: nz } }));
  };
  const persist = (id: string, to: Vec) => {
    setLive((p) => ({ ...p, [id]: { x: to.x, z: to.z } }));
    designApi.updatePosition(token as string, projectId, id, to).catch(() => {});
  };
  const onUp = () => {
    const d = drag.current;
    drag.current = null;
    setGuides({ x: null, z: null });
    if (!d || d.cx === undefined || d.cz === undefined) return; // no actual move
    const y = objects.find((o) => o.id === d.id)?.position?.y ?? 0;
    const to: Vec = { x: d.cx, y, z: d.cz };
    const from: Vec = { x: d.ox, y, z: d.oz };
    if (Math.abs(to.x - from.x) < 1e-4 && Math.abs(to.z - from.z) < 1e-4) return;
    setUndoStack((s) => [...s, { id: d.id, from, to }]);
    setRedoStack([]);
    designApi.updatePosition(token as string, projectId, d.id, to).catch(() => {});
    // Enforce any constraints on the dragged piece — linked pieces follow.
    void solveAndApply(constraints, d.id, { x: to.x, z: to.z });
  };
  const undo = () => {
    if (!undoStack.length) return;
    const m = undoStack[undoStack.length - 1];
    setUndoStack((s) => s.slice(0, -1));
    setRedoStack((r) => [...r, m]);
    persist(m.id, m.from);
  };
  const redo = () => {
    if (!redoStack.length) return;
    const m = redoStack[redoStack.length - 1];
    setRedoStack((r) => r.slice(0, -1));
    setUndoStack((s) => [...s, m]);
    persist(m.id, m.to);
  };

  // planegcs: pin `fixedId` at `fixedPos`, solve, and move the pieces the solver
  // adjusted so the constraints hold.
  const solveAndApply = async (cons: GcsConstraint[], fixedId: string, fixedPos: { x: number; z: number }) => {
    if (!cons.some((c) => c.refs.includes(fixedId))) return;
    const objs = foot.filter((f) => !f.structural).map((f) => ({ id: f.id, x: f.x, z: f.z }));
    const solved = await solveLayout(objs, cons, fixedId, fixedPos);
    if (!solved) return;
    for (const o of objs) {
      if (o.id === fixedId) continue;
      const s = solved[o.id];
      if (s && (Math.abs(s.x - o.x) > 1e-3 || Math.abs(s.z - o.z) > 1e-3)) {
        const y = objects.find((x) => x.id === o.id)?.position?.y ?? 0;
        persist(o.id, { x: s.x, y, z: s.z });
      }
    }
  };

  // Shift-click a second piece → link it to the selected one on the nearest
  // axis (align X or align Z), then solve so they line up immediately.
  const linkObjects = (aId: string, bId: string) => {
    const a = foot.find((f) => f.id === aId);
    const b = foot.find((f) => f.id === bId);
    if (!a || !b) return;
    const kind = Math.abs(a.x - b.x) <= Math.abs(a.z - b.z) ? "align_x" : "align_z";
    const next: GcsConstraint[] = [...constraints, { kind, refs: [aId, bId] }];
    setConstraints(next);
    void solveAndApply(next, aId, { x: a.x, z: a.z });
  };

  // Cmd/Ctrl+Z to undo, +Shift to redo — ignored while typing in a field.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undoStack, redoStack]); // eslint-disable-line react-hooks/exhaustive-deps

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
        {constraints.map((c, i) => {
          const a = foot.find((f) => f.id === c.refs[0]);
          const b = foot.find((f) => f.id === c.refs[1]);
          if (!a || !b) return null;
          return (
            <line
              key={`k${i}`}
              x1={a.x} y1={a.z} x2={b.x} y2={b.z}
              stroke="#9a9a95" strokeWidth={1} strokeDasharray="2 3"
              vectorEffect="non-scaling-stroke" style={{ pointerEvents: "none" }}
            />
          );
        })}
        {guides.x !== null ? (
          <line
            x1={guides.x} y1={minZ} x2={guides.x} y2={maxZ}
            stroke="#C8362D" strokeWidth={1} strokeDasharray="4 3"
            vectorEffect="non-scaling-stroke" style={{ pointerEvents: "none" }}
          />
        ) : null}
        {guides.z !== null ? (
          <line
            x1={minX} y1={guides.z} x2={maxX} y2={guides.z}
            stroke="#C8362D" strokeWidth={1} strokeDasharray="4 3"
            vectorEffect="non-scaling-stroke" style={{ pointerEvents: "none" }}
          />
        ) : null}
      </svg>
      <div className="absolute bottom-2 left-2 flex items-center gap-1.5">
        <button
          type="button"
          onClick={undo}
          disabled={!undoStack.length}
          className="rounded border border-hairline bg-paper/85 backdrop-blur-sm px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.12em] text-ink-soft hover:text-ink disabled:opacity-40 transition-colors"
        >
          ↩ Undo
        </button>
        <button
          type="button"
          onClick={redo}
          disabled={!redoStack.length}
          className="rounded border border-hairline bg-paper/85 backdrop-blur-sm px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.12em] text-ink-soft hover:text-ink disabled:opacity-40 transition-colors"
        >
          ↪ Redo
        </button>
        <button
          type="button"
          onClick={() => setSnap((s) => !s)}
          aria-pressed={snap}
          className={`rounded border border-hairline backdrop-blur-sm px-2 py-0.5 font-mono text-[9px] uppercase tracking-[0.12em] transition-colors ${
            snap ? "bg-ink text-paper" : "bg-paper/85 text-ink-soft hover:text-ink"
          }`}
        >
          {snap ? "Snap 10cm" : "Free"}
        </button>
        <span className="pointer-events-none font-mono text-[9px] uppercase tracking-[0.12em] text-ink-mute/70">
          drag · shift-click to link
        </span>
      </div>
    </div>
  );
}
