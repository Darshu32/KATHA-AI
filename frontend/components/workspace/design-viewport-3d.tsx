"use client";

/* Live, EDITABLE 3D viewport — orbits the real kernel geometry (served by
 * GET /projects/{id}/scene.gltf) and lets the architect directly manipulate it:
 * click an object to select, drag it on the floor plane to move. The new
 * position is written back to the spec (PATCH .../objects/{id}/position), which
 * is the single source of truth — the 2D render and drawings re-derive from it.
 *
 * The kernel emits world coordinates, so on load we recenter the model to the
 * origin and frame the camera from its real size (deterministic, no auto-fit
 * race). A drag moves a node relative to that recentred scene, so the node's
 * local offset is exactly the metres to add to the object's spec position. */

import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, TransformControls } from "@react-three/drei";
import { GLTFLoader } from "three-stdlib";
import { Box3, Vector3, type Group, type Mesh, type Object3D } from "three";

import { design as designApi, resolveAssetUrl } from "@/lib/api-client";
import { useAuthStore } from "@/lib/store";

type Status = "loading" | "ready" | "error";
type Loaded = { scene: Group; center: [number, number, number]; radius: number };
type Vec = { x: number; y: number; z: number };
type GraphObj = { id?: string; position?: Partial<Vec> };
type Graph = { objects?: GraphObj[] } | null | undefined;

function disposeScene(scene: Group | null) {
  scene?.traverse((o) => {
    const m = o as Mesh;
    if (m.isMesh) {
      m.geometry?.dispose?.();
      const mat = m.material;
      if (Array.isArray(mat)) mat.forEach((x) => x?.dispose?.());
      else mat?.dispose?.();
    }
  });
}

function useSceneGltf(url: string) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  useEffect(() => {
    let alive = true;
    let current: Group | null = null;
    setStatus("loading");
    setLoaded(null);
    new GLTFLoader().load(
      url,
      (gltf) => {
        const scene = gltf.scene as unknown as Group;
        if (!alive) return disposeScene(scene);
        scene.updateMatrixWorld(true);
        const box = new Box3().setFromObject(scene);
        const c = box.getCenter(new Vector3());
        const size = box.getSize(new Vector3());
        // Geometry is placed via node translations (real world coords), so DON'T
        // move the scene — frame the camera on the world centre instead. This
        // keeps each node's origin = the object's position, which the transform
        // gizmo and the drag readback depend on.
        current = scene;
        setLoaded({ scene, center: [c.x, c.y, c.z], radius: Math.max(size.length() / 2, 0.5) });
        setStatus("ready");
      },
      undefined,
      () => alive && setStatus("error"),
    );
    return () => {
      alive = false;
      disposeScene(current);
    };
  }, [url]);
  return { loaded, status };
}

function EditableModel({
  scene,
  graph,
  projectId,
  selectedObjectId,
  onSelectObject,
}: {
  scene: Group;
  graph: Graph;
  projectId: string;
  selectedObjectId: string | null;
  onSelectObject?: (id: string | null) => void;
}) {
  const token = useAuthStore((s) => s.token);
  const idSet = useMemo(
    () => new Set((graph?.objects ?? []).map((o) => o.id).filter(Boolean) as string[]),
    [graph],
  );
  const selectedObj: Object3D | null =
    selectedObjectId ? scene.getObjectByName(selectedObjectId) ?? null : null;

  // Click the nearest named ancestor (a glTF node named by its object id).
  const handleClick = (e: { stopPropagation: () => void; object: Object3D }) => {
    e.stopPropagation();
    let o: Object3D | null = e.object;
    while (o) {
      if (o.name && idSet.has(o.name)) return onSelectObject?.(o.name);
      o = o.parent;
    }
  };

  // On drag end, the node's local offset (recentred scene ⇒ no rotation) is the
  // world-space, metres delta to add to the object's spec position.
  const persistMove = () => {
    if (!selectedObj || !selectedObjectId) return;
    const base = (graph?.objects ?? []).find((o) => o.id === selectedObjectId)?.position;
    if (!base) return;
    // Geometry uses node translations, so after a drag the node's position IS
    // the object's absolute centre — and the kernel centres boxes in x/z, so
    // that equals the spec x/z. y is left untouched (floor-plane drag only).
    const next: Vec = {
      x: selectedObj.position.x,
      y: base.y ?? 0,
      z: selectedObj.position.z,
    };
    designApi
      .updatePosition(token as string, projectId, selectedObjectId, next)
      .catch(() => {});
  };

  return (
    <>
      <primitive object={scene} onClick={handleClick} onPointerMissed={() => onSelectObject?.(null)} />
      {selectedObj ? (
        <TransformControls
          object={selectedObj}
          mode="translate"
          showY={false}
          size={0.8}
          onMouseUp={persistMove}
        />
      ) : null}
    </>
  );
}

function Fallback({ title, note }: { title: string; note: string }) {
  return (
    <div className="absolute inset-0 flex items-center justify-center grid-paper">
      <div className="text-center px-6">
        <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute">{title}</div>
        <div className="mt-2 text-[12px] text-ink-soft">{note}</div>
      </div>
    </div>
  );
}

export default function DesignViewport3D({
  projectId,
  version,
  graph,
  selectedObjectId = null,
  onSelectObject,
}: {
  projectId: string;
  version?: number | null;
  graph?: unknown;
  selectedObjectId?: string | null;
  onSelectObject?: (id: string | null) => void;
}) {
  const base = resolveAssetUrl(`/api/v1/projects/${projectId}/scene.gltf`) ?? "";
  // Cache-bust per version — the endpoint is no-store and content changes on
  // every edit/theme, so a stable URL would show a stale model.
  const { loaded, status } = useSceneGltf(`${base}?v=${version ?? 0}`);

  if (status === "error") {
    return (
      <Fallback
        title="3D model unavailable"
        note="No geometry for this design yet — generate or edit to build the model."
      />
    );
  }
  if (!loaded) {
    return (
      <div className="absolute inset-0 flex items-center justify-center grid-paper">
        <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-mute animate-pulse">
          building model…
        </span>
      </div>
    );
  }

  const [cx, cy, cz] = loaded.center;
  const d = loaded.radius * 2.4; // camera distance from the model's real size

  return (
    <>
      <Canvas
        camera={{
          position: [cx + d * 0.85, cy + d * 0.72, cz + d * 1.05],
          fov: 45,
          near: Math.max(loaded.radius * 0.01, 0.01),
          far: loaded.radius * 200,
        }}
        dpr={[1, 2]}
        gl={{ antialias: true }}
      >
        <color attach="background" args={["#f4f3f1"]} />
        <hemisphereLight args={["#ffffff", "#b6b2aa", 0.95]} />
        <directionalLight position={[10, 16, 8]} intensity={1.15} />
        <directionalLight position={[-8, 6, -10]} intensity={0.4} />
        <EditableModel
          scene={loaded.scene}
          graph={graph as Graph}
          projectId={projectId}
          selectedObjectId={selectedObjectId}
          onSelectObject={onSelectObject}
        />
        <OrbitControls makeDefault enableDamping dampingFactor={0.08} target={[cx, cy, cz]} />
      </Canvas>
      <div className="absolute bottom-2 left-2 pointer-events-none font-mono text-[9px] uppercase tracking-[0.12em] text-ink-mute/80">
        click to select · drag to move · scroll to zoom
      </div>
    </>
  );
}
