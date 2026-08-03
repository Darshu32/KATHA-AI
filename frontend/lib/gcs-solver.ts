"use client";

/* planegcs constraint solver (2D geometric constraint solver, wasm).
 *
 * Objects are modelled as points (world x → gcs x, world z → gcs y). When one
 * object is dragged we FIX it at the drag position and let the solver move the
 * others so the constraints still hold — e.g. two pieces linked "align X" keep
 * the same X when either is moved. Verified headless in Node before wiring here.
 *
 * The wasm is served from /planegcs.wasm (public/) so no bundler config is
 * needed; the module + its glue are imported lazily on first solve (client
 * only) and cached. */

type Vec = { x: number; z: number };
type Obj = { id: string; x: number; z: number };
export type GcsConstraint = { kind: string; refs: string[]; value?: number | null };
type Prim = Record<string, unknown>;

// KATHA constraint kind → planegcs constraint type.
const KIND: Record<string, string> = {
  align_x: "vertical_pp", // same world x  → same gcs x
  align_z: "horizontal_pp", // same world z → same gcs y
  coincident: "p2p_coincident",
};

interface Loaded {
  wasm: { GcsSystem: new () => unknown };
  GcsWrapper: new (sys: unknown) => {
    push_primitives_and_params: (p: Prim[]) => void;
    solve: () => number;
    apply_solution: () => void;
    sketch_index: { get_primitives: () => Prim[] };
    destroy_gcs_module: () => void;
  };
}

let _mod: Promise<Loaded> | null = null;
function getModule(): Promise<Loaded> {
  if (!_mod) {
    _mod = import("@salusoft89/planegcs").then(async (m) => ({
      wasm: (await m.init_planegcs_module({ locateFile: () => "/planegcs.wasm" })) as Loaded["wasm"],
      GcsWrapper: m.GcsWrapper as unknown as Loaded["GcsWrapper"],
    }));
  }
  return _mod;
}

/** Warm the wasm up front (e.g. when the plan editor mounts) so the first drag
 *  isn't blocked on loading. Safe to call repeatedly. */
export function preloadSolver(): void {
  void getModule().catch(() => {});
}

/** Fix `fixedId` at `fixedPos`, adjust the others to satisfy `constraints`, and
 *  return every object's resolved position. Returns null on any failure so the
 *  caller falls back to a plain move. */
export async function solveLayout(
  objects: Obj[],
  constraints: GcsConstraint[],
  fixedId: string,
  fixedPos: Vec,
): Promise<Record<string, Vec> | null> {
  let loaded: Loaded;
  try {
    loaded = await getModule();
  } catch {
    return null;
  }
  const wrapper = new loaded.GcsWrapper(new loaded.wasm.GcsSystem());
  try {
    const prims: Prim[] = [];
    for (const o of objects) {
      const fixed = o.id === fixedId;
      const p = fixed ? fixedPos : { x: o.x, z: o.z };
      prims.push({ id: o.id, type: "point", x: p.x, y: p.z, fixed });
    }
    let k = 100000;
    for (const c of constraints) {
      const [a, b] = c.refs;
      if (!a || !b) continue;
      if (c.kind === "distance" && c.value != null) {
        prims.push({ id: `k${k++}`, type: "p2p_distance", p1_id: a, p2_id: b, distance: c.value });
      } else if (KIND[c.kind]) {
        prims.push({ id: `k${k++}`, type: KIND[c.kind], p1_id: a, p2_id: b });
      }
    }
    wrapper.push_primitives_and_params(prims);
    wrapper.solve();
    wrapper.apply_solution();
    const out: Record<string, Vec> = {};
    for (const p of wrapper.sketch_index.get_primitives()) {
      if (p.type === "point") out[String(p.id)] = { x: Number(p.x), z: Number(p.y) };
    }
    return out;
  } catch {
    return null;
  } finally {
    wrapper.destroy_gcs_module();
  }
}
