"use client";

import { Suspense, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Grid, Text } from "@react-three/drei";
import * as THREE from "three";
import type { DesignGraph, DesignObject } from "@/lib/types";
import { useDesignStore } from "@/lib/store";

function FurnitureBox({ object }: { object: DesignObject }) {
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
        opacity={isSelected ? 1 : 0.85}
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

function RoomShell({ length, width, height }: { length: number; width: number; height: number }) {
  const t = 0.3;
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[length / 2, 0, width / 2]}>
        <planeGeometry args={[length, width]} />
        <meshStandardMaterial color="#e8e0d4" />
      </mesh>
      <mesh position={[length / 2, height / 2, -t / 2]}>
        <boxGeometry args={[length + t * 2, height, t]} />
        <meshStandardMaterial color="#f2eee8" transparent opacity={0.5} side={THREE.DoubleSide} />
      </mesh>
      <mesh position={[length / 2, height / 2, width + t / 2]}>
        <boxGeometry args={[length + t * 2, height, t]} />
        <meshStandardMaterial color="#f2eee8" transparent opacity={0.3} side={THREE.DoubleSide} />
      </mesh>
      <mesh position={[-t / 2, height / 2, width / 2]}>
        <boxGeometry args={[t, height, width]} />
        <meshStandardMaterial color="#ede8e0" transparent opacity={0.5} side={THREE.DoubleSide} />
      </mesh>
      <mesh position={[length + t / 2, height / 2, width / 2]}>
        <boxGeometry args={[t, height, width]} />
        <meshStandardMaterial color="#ede8e0" transparent opacity={0.3} side={THREE.DoubleSide} />
      </mesh>
    </group>
  );
}

function Scene({ graph }: { graph: DesignGraph }) {
  const { selectObject } = useDesignStore();
  const rL = graph.room.dimensions.length;
  const rW = graph.room.dimensions.width;
  const rH = graph.room.dimensions.height;
  const floorObjects = graph.objects.filter((o) => o.type !== "wall_art");

  return (
    <>
      <ambientLight intensity={0.6} color="#fff8f0" />
      <directionalLight position={[rL, rH * 1.5, rW]} intensity={0.8} castShadow />
      <directionalLight position={[-5, rH, -5]} intensity={0.3} />

      <RoomShell length={rL} width={rW} height={rH} />

      {floorObjects.map((obj) => (
        <group key={obj.id}>
          <FurnitureBox object={obj} />
          <Text
            position={[obj.position.x, obj.dimensions.height + 0.5 + obj.position.y, obj.position.z]}
            fontSize={0.4}
            color="#374151"
            anchorX="center"
            anchorY="bottom"
          >
            {obj.name}
          </Text>
        </group>
      ))}

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
  const rL = graph.room.dimensions.length;
  const rW = graph.room.dimensions.width;
  const rH = graph.room.dimensions.height;

  return (
    <Canvas
      camera={{
        position: [rL * 0.8, rH * 1.5, rW * 1.5],
        fov: 50,
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
