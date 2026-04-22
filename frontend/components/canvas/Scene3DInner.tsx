"use client";

import { Suspense, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Grid, Text } from "@react-three/drei";
import * as THREE from "three";
import type { CameraMode, DesignGraph, DesignObject, LightingMode } from "@/lib/types";
import { useDesignStore, useImageGenStore } from "@/lib/store";

function cameraPosition(mode: CameraMode, rL: number, rW: number, rH: number): [number, number, number] {
  switch (mode) {
    case "aerial":
      return [rL / 2, Math.max(rL, rW) * 1.6, rW / 2 + 0.01];
    case "interior":
      return [rL * 0.55, rH * 0.55, rW * 0.35];
    case "eye-level":
      return [rL * 0.3, 1.65, -rW * 0.4];
    case "front":
    default:
      return [rL * 0.8, rH * 1.5, rW * 1.5];
  }
}

function lightingProfile(mode: LightingMode) {
  switch (mode) {
    case "golden-hour":
      return {
        ambient: { intensity: 0.45, color: "#ffd29a" },
        key: { intensity: 1.4, color: "#ff9c4a" },
        fill: { intensity: 0.35, color: "#a35f2a" },
        rim: { intensity: 0.6, color: "#ffe0b3" },
        bg: "#f6cf94",
        wall: "#f5dcb8",
        floor: "#e2b97a",
        keyDir: [1, 0.35, 1] as [number, number, number],
        fog: { color: "#f6cf94", near: 30, far: 120 },
      };
    case "night":
      return {
        ambient: { intensity: 0.18, color: "#1a2240" },
        key: { intensity: 0.45, color: "#5774b5" },
        fill: { intensity: 0.12, color: "#1d2545" },
        rim: { intensity: 0.4, color: "#6e8cd9" },
        bg: "#070b1a",
        wall: "#1c2640",
        floor: "#0e1428",
        keyDir: [0.6, 1, -0.4] as [number, number, number],
        fog: { color: "#070b1a", near: 12, far: 70 },
      };
    case "overcast":
      return {
        ambient: { intensity: 0.95, color: "#e3e8ee" },
        key: { intensity: 0.35, color: "#bcc4cd" },
        fill: { intensity: 0.5, color: "#cdd4dc" },
        rim: { intensity: 0, color: "#ffffff" },
        bg: "#cfd5dc",
        wall: "#e6e8ec",
        floor: "#d4d8dc",
        keyDir: [0.4, 1, 0.4] as [number, number, number],
        fog: { color: "#cfd5dc", near: 25, far: 90 },
      };
    case "daylight":
    default:
      return {
        ambient: { intensity: 0.6, color: "#fff8f0" },
        key: { intensity: 1.0, color: "#ffffff" },
        fill: { intensity: 0.35, color: "#b8cbe0" },
        rim: { intensity: 0.5, color: "#cfe1f4" },
        bg: "#eef3f8",
        wall: "#f2eee8",
        floor: "#e8e0d4",
        keyDir: [1, 1.2, 1] as [number, number, number],
        fog: { color: "#eef3f8", near: 40, far: 160 },
      };
  }
}

function FurnitureBox({ object, wireframe }: { object: DesignObject; wireframe: boolean }) {
  const {
    selectedObjectId,
    selectObject,
    hoverObject,
    updateObjectPosition,
    pushUndo,
    setDragging,
    snapToGrid,
    gridUnit,
    activeGraph,
  } = useDesignStore();
  const isSelected = selectedObjectId === object.id;
  const meshRef = useRef<THREE.Mesh>(null);
  const [isDrag, setIsDrag] = useState(false);
  const dragStart = useRef<{ x: number; z: number; ox: number; oz: number } | null>(null);

  const snap = (v: number) => (snapToGrid ? Math.round(v / gridUnit) * gridUnit : v);
  const rL = activeGraph?.room.dimensions.length ?? 30;
  const rW = activeGraph?.room.dimensions.width ?? 20;

  return (
    <mesh
      ref={meshRef}
      position={[object.position.x, object.dimensions.height / 2 + object.position.y, object.position.z]}
      rotation={[0, object.rotation.y, 0]}
      onClick={(e) => {
        e.stopPropagation();
        selectObject(object.id);
      }}
      onPointerEnter={() => hoverObject(object.id)}
      onPointerLeave={() => hoverObject(null)}
      onPointerDown={(e) => {
        e.stopPropagation();
        (e.target as any).setPointerCapture?.(e.pointerId);
        pushUndo();
        selectObject(object.id);
        setDragging(true, object.id);
        setIsDrag(true);
        const point = e.point;
        dragStart.current = { x: point.x, z: point.z, ox: object.position.x, oz: object.position.z };
      }}
      onPointerMove={(e) => {
        if (!isDrag || !dragStart.current) return;
        e.stopPropagation();
        const point = e.point;
        const dx = point.x - dragStart.current.x;
        const dz = point.z - dragStart.current.z;
        const nx = snap(Math.max(object.dimensions.width / 2, Math.min(rL - object.dimensions.width / 2, dragStart.current.ox + dx)));
        const nz = snap(Math.max(object.dimensions.length / 2, Math.min(rW - object.dimensions.length / 2, dragStart.current.oz + dz)));
        updateObjectPosition(object.id, { x: nx, y: object.position.y, z: nz });
      }}
      onPointerUp={() => {
        setIsDrag(false);
        setDragging(false);
        dragStart.current = null;
      }}
    >
      <boxGeometry args={[object.dimensions.width, object.dimensions.height, object.dimensions.length]} />
      <meshStandardMaterial
        color={object.color}
        transparent
        opacity={wireframe ? 0.05 : isSelected ? 1 : 0.85}
        wireframe={wireframe}
      />
      {isSelected && (
        <lineSegments>
          <edgesGeometry args={[new THREE.BoxGeometry(object.dimensions.width, object.dimensions.height, object.dimensions.length)]} />
          <lineBasicMaterial color="#3b82f6" />
        </lineSegments>
      )}
    </mesh>
  );
}

function RoomShell({
  length,
  width,
  height,
  wallColor,
  floorColor,
}: {
  length: number;
  width: number;
  height: number;
  wallColor: string;
  floorColor: string;
}) {
  const t = 0.3;
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[length / 2, 0, width / 2]} receiveShadow>
        <planeGeometry args={[length, width]} />
        <meshStandardMaterial color={floorColor} />
      </mesh>
      <mesh position={[length / 2, height / 2, -t / 2]}>
        <boxGeometry args={[length + t * 2, height, t]} />
        <meshStandardMaterial color={wallColor} transparent opacity={0.5} side={THREE.DoubleSide} />
      </mesh>
      <mesh position={[length / 2, height / 2, width + t / 2]}>
        <boxGeometry args={[length + t * 2, height, t]} />
        <meshStandardMaterial color={wallColor} transparent opacity={0.3} side={THREE.DoubleSide} />
      </mesh>
      <mesh position={[-t / 2, height / 2, width / 2]}>
        <boxGeometry args={[t, height, width]} />
        <meshStandardMaterial color={wallColor} transparent opacity={0.5} side={THREE.DoubleSide} />
      </mesh>
      <mesh position={[length + t / 2, height / 2, width / 2]}>
        <boxGeometry args={[t, height, width]} />
        <meshStandardMaterial color={wallColor} transparent opacity={0.3} side={THREE.DoubleSide} />
      </mesh>
    </group>
  );
}

function Scene({ graph }: { graph: DesignGraph }) {
  const { selectObject, layerVisibility } = useDesignStore();
  const { lighting } = useImageGenStore();
  const rL = graph.room.dimensions.length;
  const rW = graph.room.dimensions.width;
  const rH = graph.room.dimensions.height;
  const floorObjects = graph.objects.filter((o) => o.type !== "wall_art");
  const lp = lightingProfile(lighting);
  const showFurniture = layerVisibility.furniture;
  const showDimensions = layerVisibility.dimensions;
  const showGrid = layerVisibility.grid;
  const wireframe = layerVisibility.wireframe;

  return (
    <>
      <color attach="background" args={[lp.bg]} />
      <fog attach="fog" args={[lp.fog.color, lp.fog.near, lp.fog.far]} />
      <ambientLight intensity={lp.ambient.intensity} color={lp.ambient.color} />
      <directionalLight
        position={[rL * lp.keyDir[0], rH * lp.keyDir[1], rW * lp.keyDir[2]]}
        intensity={lp.key.intensity}
        color={lp.key.color}
        castShadow
      />
      <directionalLight position={[-5, rH, -5]} intensity={lp.fill.intensity} color={lp.fill.color} />
      {lp.rim.intensity > 0 && (
        <directionalLight position={[-rL * 0.6, rH * 1.2, -rW * 0.6]} intensity={lp.rim.intensity} color={lp.rim.color} />
      )}

      <RoomShell length={rL} width={rW} height={rH} wallColor={lp.wall} floorColor={lp.floor} />

      {showFurniture && floorObjects.map((obj) => (
        <group key={obj.id}>
          <FurnitureBox object={obj} wireframe={wireframe} />
          {showDimensions && (
            <Text
              position={[obj.position.x, obj.dimensions.height + 0.5 + obj.position.y, obj.position.z]}
              fontSize={0.4}
              color="#374151"
              anchorX="center"
              anchorY="bottom"
            >
              {obj.name} · {obj.dimensions.width.toFixed(1)}'×{obj.dimensions.length.toFixed(1)}'
            </Text>
          )}
        </group>
      ))}

      {showGrid && (
        <Grid
          position={[rL / 2, 0.01, rW / 2]}
          args={[rL, rW]}
          cellSize={1}
          cellThickness={0.5}
          cellColor="#d1d5db"
          sectionSize={5}
          sectionThickness={1}
          sectionColor="#9ca3af"
          fadeDistance={80}
          infiniteGrid={false}
        />
      )}

      <OrbitControls
        makeDefault
        target={[rL / 2, rH * 0.2, rW / 2]}
        maxPolarAngle={Math.PI / 2.1}
        minDistance={5}
        maxDistance={80}
      />

      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[rL / 2, -0.01, rW / 2]} onClick={() => selectObject(null)}>
        <planeGeometry args={[rL * 3, rW * 3]} />
        <meshBasicMaterial visible={false} />
      </mesh>
    </>
  );
}

export default function Scene3DInner({ graph }: { graph: DesignGraph }) {
  const camera = useImageGenStore((s) => s.camera);
  const rL = graph.room.dimensions.length;
  const rW = graph.room.dimensions.width;
  const rH = graph.room.dimensions.height;

  return (
    <Canvas
      key={camera}
      camera={{
        position: cameraPosition(camera, rL, rW, rH),
        fov: camera === "interior" ? 70 : 50,
        near: 0.1,
        far: 200,
      }}
      shadows
      style={{ width: "100%", height: "100%" }}
    >
      <Suspense fallback={null}>
        <Scene graph={graph} />
      </Suspense>
    </Canvas>
  );
}
