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
import { useDesignRoom } from "@/lib/use-design-room";

type Vec = { x: number; y: number; z: number };
type Dim = { length?: number; width?: number; height?: number; unit?: string };
type Obj = { id?: string; type?: string; position?: Partial<Vec>; dimensions?: Dim };
type Space = { id?: string; name?: string; type?: string; position?: Partial<Vec>; dimensions?: Dim };
type Adj = { a?: string; b?: string };
type Graph = { objects?: Obj[]; spaces?: Space[]; adjacencies?: Adj[] } | null | undefined;
// A room to draw: corner (x,z) + size (l,w) in metres, matching the kernel's
// `_placed_rooms` convention — the same world coords the furniture uses, so
// pieces land inside their rooms with no extra transform.
type Room = { id: string; name: string; x: number; z: number; l: number; w: number; area: number };
// An opening drawn ON a wall: centre (cx,cz), the axis it RUNS along, its clear
// width, and a point on its interior side so a door swings the right way.
type Opening = { id: string; kind: "door" | "window"; axis: "x" | "z"; cx: number; cz: number; size: number; inx: number; inz: number };

const UNIT: Record<string, number> = { mm: 1e-3, cm: 1e-2, m: 1, metre: 1, meter: 1, ft: 0.3048, feet: 0.3048 };
function toM(v: unknown, unit?: string): number {
  const n = typeof v === "number" ? v : parseFloat(String(v));
  if (!isFinite(n)) return 0;
  return unit ? n * (UNIT[unit.toLowerCase()] ?? 1) : Math.abs(n) > 30 ? n / 1000 : n;
}

// Structural elements aren't draggable furniture — show them faintly as context.
const STRUCTURAL = new Set(["building", "wall", "floor", "slab", "ground", "atrium", "driveway"]);
// Openings are drawn as architectural symbols on the walls, not furniture boxes.
const OPENING_TYPES = new Set(["door", "window", "opening", "doorway"]);

/* One opening on a wall — a door (leaf + swing arc) or a window (glazing line),
 * with a paper-filled gap so the wall reads as broken there. */
function OpeningGlyph({ op }: { op: Opening }) {
  const { kind, axis, cx, cz, size } = op;
  const half = size / 2;
  const maskT = 0.18; // metres — wide enough to cover the wall stroke
  const gap =
    axis === "x" ? (
      <rect x={cx - half} y={cz - maskT / 2} width={size} height={maskT} fill="var(--paper)" />
    ) : (
      <rect x={cx - maskT / 2} y={cz - half} width={maskT} height={size} fill="var(--paper)" />
    );
  if (kind === "window") {
    const line =
      axis === "x" ? (
        <line x1={cx - half} y1={cz} x2={cx + half} y2={cz} stroke="#1A1A1A" strokeWidth={1} vectorEffect="non-scaling-stroke" />
      ) : (
        <line x1={cx} y1={cz - half} x2={cx} y2={cz + half} stroke="#1A1A1A" strokeWidth={1} vectorEffect="non-scaling-stroke" />
      );
    return (
      <g style={{ pointerEvents: "none" }}>
        {gap}
        {line}
      </g>
    );
  }
  // Door: hinge at one jamb, leaf perpendicular into the interior, swing arc back.
  const perp = axis === "x" ? Math.sign(op.inz - cz) || 1 : Math.sign(op.inx - cx) || 1;
  const hinge = axis === "x" ? { x: cx - half, z: cz } : { x: cx, z: cz - half };
  const jamb2 = axis === "x" ? { x: cx + half, z: cz } : { x: cx, z: cz + half };
  const tip = axis === "x" ? { x: hinge.x, z: hinge.z + perp * size } : { x: hinge.x + perp * size, z: hinge.z };
  const sweep = axis === "x" ? (perp > 0 ? 0 : 1) : perp > 0 ? 1 : 0;
  return (
    <g style={{ pointerEvents: "none" }}>
      {gap}
      <line x1={hinge.x} y1={hinge.z} x2={tip.x} y2={tip.z} stroke="#9a9a95" strokeWidth={1} vectorEffect="non-scaling-stroke" />
      <path
        d={`M ${tip.x} ${tip.z} A ${size} ${size} 0 0 ${sweep} ${jamb2.x} ${jamb2.z}`}
        fill="none"
        stroke="#c4c4bf"
        strokeWidth={1}
        vectorEffect="non-scaling-stroke"
      />
    </g>
  );
}

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
  // Real-time collaboration: shared positions + peer presence for this project.
  const room = useDesignRoom(projectId, (token as string) ?? "", Boolean(projectId));
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

  const objects = useMemo(() => {
    // De-dupe by id: a graph that accumulated a duplicate object (e.g. over many
    // edit rounds) would otherwise draw the same footprint + label twice, which
    // reads as "garbled" doubled text. One draw per id.
    const seen = new Set<string>();
    return ((graph as Graph)?.objects ?? []).filter((o) => {
      if (!o?.id || !o.position) return false;
      if (seen.has(o.id)) return false;
      seen.add(o.id);
      return true;
    });
  }, [graph]);

  // Rooms from the spec's spaces — walls + name + area. A solved multi-room plan
  // carries an explicit corner position per space; a single room defaults to the
  // origin shell (0,0)→(L,W), matching the kernel. Same world metres as objects.
  const rooms: Room[] = useMemo(() => {
    const sp = (graph as Graph)?.spaces;
    if (!Array.isArray(sp)) return [];
    const withDims = sp.filter((s) => {
      const d = s?.dimensions ?? {};
      return toM(d.length, d.unit) > 0 && toM(d.width, d.unit) > 0;
    });
    if (withDims.length === 0) return [];
    const positioned = withDims.filter((s) => s?.position?.x != null && s?.position?.z != null);
    // A *solved* plan → draw every placed room at its position. Otherwise draw
    // only the primary space as the single room shell at the origin — never
    // stack multiple position-less spaces on top of each other (which would
    // pile their walls + labels into an unreadable blob).
    const src = positioned.length > 0 ? positioned : [withDims[0]];
    return src.map((s, i) => {
      const d = s?.dimensions ?? {};
      const L = toM(d.length, d.unit);
      const W = toM(d.width, d.unit);
      const pos = s?.position;
      const x = pos && pos.x != null ? toM(pos.x, d.unit) : 0;
      const z = pos && pos.z != null ? toM(pos.z, d.unit) : 0;
      return {
        id: String(s?.id ?? s?.name ?? `room_${i + 1}`),
        name: String(s?.name ?? s?.type ?? `Room ${i + 1}`),
        x, z, l: L, w: W, area: L * W,
      };
    });
  }, [graph]);

  const foot = objects
    .filter((o) => !OPENING_TYPES.has(String(o.type ?? "").toLowerCase()))
    .map((o) => {
      const d = o.dimensions ?? {};
      const l = toM(d.length, d.unit) || 0.5;
      const w = toM(d.width, d.unit) || 0.5;
      // Position priority: my in-flight drag → shared-room value (local + remote
      // edits) → the graph's saved position. So peers' drags appear live.
      const rp = room.positions[o.id!];
      const p = live[o.id!] ?? (rp ? { x: rp.x, z: rp.z } : { x: o.position!.x ?? 0, z: o.position!.z ?? 0 });
      return { id: o.id!, type: String(o.type ?? ""), l, w, x: p.x, z: p.z, structural: STRUCTURAL.has(String(o.type ?? "").toLowerCase()) };
    });

  // Openings drawn as wall SYMBOLS (not furniture boxes): doors from adjacencies
  // (a door on the wall two connected rooms share) + any explicit door/window
  // objects, snapped onto the nearest room wall.
  const openings: Opening[] = (() => {
    const out: Opening[] = [];
    const roomById = new Map(rooms.map((r) => [r.id, r] as const));
    const EPS = 0.35;
    const adj = (graph as Graph)?.adjacencies ?? [];
    adj.forEach((pair, i) => {
      const a = roomById.get(String(pair?.a));
      const b = roomById.get(String(pair?.b));
      if (!a || !b) return;
      const inx = a.x + a.l / 2, inz = a.z + a.w / 2; // swing into room a
      const vert = (wallX: number) => {
        const z0 = Math.max(a.z, b.z), z1 = Math.min(a.z + a.w, b.z + b.w);
        if (z1 - z0 > 0.6)
          out.push({ id: `door_adj_${i}`, kind: "door", axis: "z", cx: wallX, cz: (z0 + z1) / 2, size: Math.min(0.9, z1 - z0 - 0.2), inx, inz });
      };
      const horz = (wallZ: number) => {
        const x0 = Math.max(a.x, b.x), x1 = Math.min(a.x + a.l, b.x + b.l);
        if (x1 - x0 > 0.6)
          out.push({ id: `door_adj_${i}`, kind: "door", axis: "x", cx: (x0 + x1) / 2, cz: wallZ, size: Math.min(0.9, x1 - x0 - 0.2), inx, inz });
      };
      if (Math.abs(a.x + a.l - b.x) < EPS) vert(a.x + a.l);
      else if (Math.abs(b.x + b.l - a.x) < EPS) vert(a.x);
      else if (Math.abs(a.z + a.w - b.z) < EPS) horz(a.z + a.w);
      else if (Math.abs(b.z + b.w - a.z) < EPS) horz(a.z);
    });
    objects
      .filter((o) => OPENING_TYPES.has(String(o.type ?? "").toLowerCase()))
      .forEach((o, i) => {
        const d = o.dimensions ?? {};
        const size = Math.max(toM(d.length, d.unit), toM(d.width, d.unit)) || 0.9;
        const px = toM(o.position?.x, d.unit), pz = toM(o.position?.z, d.unit);
        const kind: "door" | "window" = String(o.type).toLowerCase().startsWith("window") ? "window" : "door";
        let r = rooms.find((rm) => px >= rm.x - 0.5 && px <= rm.x + rm.l + 0.5 && pz >= rm.z - 0.5 && pz <= rm.z + rm.w + 0.5);
        if (!r && rooms.length) {
          const d2 = (rm: Room) => (px - (rm.x + rm.l / 2)) ** 2 + (pz - (rm.z + rm.w / 2)) ** 2;
          r = rooms.reduce((best, rm) => (d2(rm) < d2(best) ? rm : best));
        }
        if (!r) {
          out.push({ id: o.id ?? `op_${i}`, kind, axis: "x", cx: px, cz: pz, size, inx: px, inz: pz + 1 });
          return;
        }
        const inx = r.x + r.l / 2, inz = r.z + r.w / 2;
        const dLeft = Math.abs(px - r.x), dRight = Math.abs(px - (r.x + r.l));
        const dTop = Math.abs(pz - r.z), dBottom = Math.abs(pz - (r.z + r.w));
        if (Math.min(dLeft, dRight) <= Math.min(dTop, dBottom)) {
          out.push({ id: o.id ?? `op_${i}`, kind, axis: "z", cx: dLeft <= dRight ? r.x : r.x + r.l, cz: pz, size, inx, inz: pz });
        } else {
          out.push({ id: o.id ?? `op_${i}`, kind, axis: "x", cx: px, cz: dTop <= dBottom ? r.z : r.z + r.w, size, inx: px, inz });
        }
      });
    return out;
  })();

  // World bounds → viewBox (1 SVG unit = 1 metre). Frame the ROOMS (+ any
  // furniture that spills past them), so the plan reads as a floor plan.
  const xs = [
    ...foot.flatMap((f) => [f.x - f.l / 2, f.x + f.l / 2]),
    ...rooms.flatMap((r) => [r.x, r.x + r.l]),
  ];
  const zs = [
    ...foot.flatMap((f) => [f.z - f.w / 2, f.z + f.w / 2]),
    ...rooms.flatMap((r) => [r.z, r.z + r.w]),
  ];
  const pad = 1.2;
  const minX = (xs.length ? Math.min(...xs) : 0) - pad;
  const maxX = (xs.length ? Math.max(...xs) : 10) + pad;
  const minZ = (zs.length ? Math.min(...zs) : 0) - pad;
  const maxZ = (zs.length ? Math.max(...zs) : 10) + pad;
  const vbW = maxX - minX;
  const vbH = maxZ - minZ;
  // Capped so labels stay legible whether the plan is a 3 m nook or a 20 m floor.
  const font = Math.min(Math.max(vbW, vbH) * 0.02, 0.3);
  const roomFont = Math.min(Math.max(vbW, vbH) * 0.028, 0.44);

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
    room.setPosition(id, to); // broadcast to collaborators
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
    room.setPosition(d.id, to); // broadcast to collaborators
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
        {/* Rooms — perimeter walls + name + area, from the spec's spaces. Drawn
            first, so the furniture footprints sit on top, inside their rooms. */}
        {rooms.map((r) => {
          // Fit the name to the room width so a long name ("open-plan living and
          // dining") shrinks to fit instead of overflowing/cramping the label.
          const nameFont = Math.max(
            0.12,
            Math.min(roomFont, (r.l * 0.92) / Math.max(r.name.length * 0.5, 1)),
          );
          return (
            <g key={`room-${r.id}`} style={{ pointerEvents: "none" }}>
              <rect
                x={r.x}
                y={r.z}
                width={r.l}
                height={r.w}
                fill="rgba(26,26,26,0.015)"
                stroke="#1A1A1A"
                strokeWidth={2.5}
                vectorEffect="non-scaling-stroke"
              />
              <text
                x={r.x + r.l / 2}
                y={r.z + nameFont * 1.3}
                fontSize={nameFont}
                textAnchor="middle"
                fill="#1A1A1A"
                fontWeight={600}
                style={{ userSelect: "none" }}
              >
                {r.name}
              </text>
              <text
                x={r.x + r.l / 2}
                y={r.z + nameFont * 2.55}
                fontSize={nameFont * 0.78}
                textAnchor="middle"
                fill="#6b7280"
                style={{ userSelect: "none" }}
              >
                {r.area.toFixed(1)} m²
              </text>
            </g>
          );
        })}
        {foot.map((f) => {
          const sel = f.id === selectedObjectId;
          const fill = f.structural
            ? "rgba(26,26,26,0.035)"
            : sel
              ? "rgba(200,54,45,0.14)"
              : "rgba(26,26,26,0.06)";
          // Furniture reads lighter than the room walls above, so the plan's
          // structure dominates and the pieces are clearly secondary.
          const stroke = sel ? "#C8362D" : f.structural ? "#c9c9c4" : "#6f6f6a";
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
              {!f.structural ? (() => {
                const label = f.type.replace(/_/g, " ");
                // Shrink the label to fit inside its own footprint so it never
                // overflows the box or collides with the neighbour — the real
                // cause of the unreadable doubled-up text. Too small → drop it
                // (the room context still identifies the piece).
                const fit = Math.max(
                  0.05,
                  Math.min(font, (f.l * 0.9) / Math.max(label.length * 0.55, 1), f.w * 0.62),
                );
                return fit >= 0.09 ? (
                  <text
                    x={f.x}
                    y={f.z}
                    fontSize={fit}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fill="#3f3f46"
                    style={{ pointerEvents: "none", userSelect: "none" }}
                  >
                    {label}
                  </text>
                ) : null;
              })() : null}
            </g>
          );
        })}
        {/* Doors + windows drawn as wall symbols, on top of the walls. */}
        {openings.map((op) => (
          <OpeningGlyph key={op.id} op={op} />
        ))}
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
        {room.connected ? (
          <span
            className="pointer-events-none flex items-center gap-1 font-mono text-[9px] uppercase tracking-[0.12em] text-ink-soft"
            title={`${room.peers} collaborator${room.peers === 1 ? "" : "s"} in this project`}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-[#2f7d4f]" />
            {room.peers > 1 ? `${room.peers} editing` : "live"}
          </span>
        ) : null}
      </div>
    </div>
  );
}
