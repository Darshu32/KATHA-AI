"use client";

import { Canvas } from "@react-three/fiber";
import { OrbitControls, Grid, Environment } from "@react-three/drei";
import { useDesignGraphStore } from "../lib/store";
import * as THREE from "three";

// ── Individual scene object ─────────────────────────────────────────────────

interface DesignObj {
  id: string;
  type: string;
  name: string;
  position: { x: number; y: number; z: number };
  rotation: { x: number; y: number; z: number };
  dimensions: { length: number; width: number; height: number };
  color: string;
}

function ObjectMesh({
  obj,
  isSelected,
  onSelect,
}: {
  obj: DesignObj;
  isSelected: boolean;
  onSelect: (id: string) => void;
}) {
  const pos = obj.position ?? { x: 0, y: 0, z: 0 };
  const dims = obj.dimensions ?? { length: 1, width: 1, height: 1 };
  const w = dims.width || 1;
  const h = dims.height || 1;
  const d = dims.length || 1;
  const color = obj.color || "#cccccc";

  return (
    <group
      position={[pos.x, (pos.y ?? 0) + h / 2, pos.z]}
      rotation={[obj.rotation?.x ?? 0, obj.rotation?.y ?? 0, obj.rotation?.z ?? 0]}
      onClick={(e) => {
        e.stopPropagation();
        onSelect(obj.id);
      }}
    >
      <mesh castShadow receiveShadow>
        <boxGeometry args={[w, h, d]} />
        <meshStandardMaterial
          color={isSelected ? "#f59e0b" : color}
          transparent={isSelected}
          opacity={isSelected ? 0.85 : 1}
        />
      </mesh>
      {isSelected && (
        <lineSegments>
          <edgesGeometry args={[new THREE.BoxGeometry(w, h, d)]} />
          <lineBasicMaterial color="#f59e0b" />
        </lineSegments>
      )}
    </group>
  );
}

// ── Room floor plane ────────────────────────────────────────────────────────

function RoomFloor({ length, width }: { length: number; width: number }) {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[length / 2, 0, width / 2]} receiveShadow>
      <planeGeometry args={[length, width]} />
      <meshStandardMaterial color="#e8e0d4" />
    </mesh>
  );
}

// ── Main 3D viewer ──────────────────────────────────────────────────────────

interface SceneViewer3DProps {
  className?: string;
}

export default function SceneViewer3D({ className = "" }: SceneViewer3DProps) {
  const graphData = useDesignGraphStore((s) => s.graphData);
  const selectedObjectId = useDesignGraphStore((s) => s.selectedObjectId);
  const selectObject = useDesignGraphStore((s) => s.selectObject);

  const objects = (graphData?.objects as DesignObj[]) ?? [];
  const spaces = (graphData?.spaces as Array<{ dimensions?: { length?: number; width?: number } }>) ?? [];
  const roomDims = spaces[0]?.dimensions;

  if (!graphData) {
    return (
      <div
        className={`flex items-center justify-center rounded-2xl border border-black/10 bg-mist/50 ${className}`}
      >
        <p className="text-ink/40">Generate a design to see the 3D view</p>
      </div>
    );
  }

  return (
    <div className={`overflow-hidden rounded-2xl border border-black/10 ${className}`}>
      <Canvas
        shadows
        camera={{ position: [15, 12, 15], fov: 50 }}
        onClick={() => selectObject(null)}
      >
        <ambientLight intensity={0.4} />
        <directionalLight
          position={[10, 15, 10]}
          intensity={1}
          castShadow
          shadow-mapSize-width={2048}
          shadow-mapSize-height={2048}
        />
        <pointLight position={[0, 10, 0]} intensity={0.3} />

        {/* Floor */}
        {roomDims ? (
          <RoomFloor length={roomDims.length ?? 15} width={roomDims.width ?? 12} />
        ) : (
          <Grid
            args={[30, 30]}
            cellSize={1}
            cellThickness={0.5}
            cellColor="#d4d0c8"
            sectionSize={5}
            sectionThickness={1}
            sectionColor="#b0a898"
            fadeDistance={50}
            fadeStrength={1}
            position={[0, 0, 0]}
          />
        )}

        {/* Objects */}
        {objects.map((obj) => (
          <ObjectMesh
            key={obj.id}
            obj={obj}
            isSelected={obj.id === selectedObjectId}
            onSelect={selectObject}
          />
        ))}

        <OrbitControls
          makeDefault
          enableDamping
          dampingFactor={0.1}
          maxPolarAngle={Math.PI / 2.1}
        />
        <Environment preset="apartment" />
      </Canvas>
    </div>
  );
}
