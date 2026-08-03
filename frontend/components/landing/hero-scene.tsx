"use client";

/* Landing hero — a weightless architectural massing model.
 *
 * The signature: KATHA's product turns a brief into a spatial design, so the
 * hero is an architect's massing study lifted off the drafting table — soft
 * white volumes with crisp ink wireframe edges, one pencil-red accent core,
 * drifting slowly (antigravity) over a soft contact shadow. Pure R3F, no
 * external assets (works under the app's CSP). Honours reduced-motion. */

import { useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Float, Edges, Bounds, Center } from "@react-three/drei";
import { useReducedMotion } from "framer-motion";
import type { Group } from "three";

const INK = "#1A1A1A";
const FACE = "#F6F5F2";
const PENCIL = "#C8362D";
const PENCIL_EDGE = "#8f241c";

type Block = { pos: [number, number, number]; size: [number, number, number]; accent?: boolean };

// A stylised building massing — podium, tower, wings, a slender accent core,
// a cantilever step and one detached floating cube.
const BLOCKS: Block[] = [
  { pos: [0, -0.95, 0], size: [3.4, 0.5, 2.4] },
  { pos: [-0.7, 0.2, -0.1], size: [1.45, 2.5, 1.45] },
  { pos: [0.95, -0.18, 0.35], size: [1.35, 1.25, 1.7] },
  { pos: [-0.72, 1.8, -0.1], size: [1.05, 0.72, 1.05] },
  { pos: [1.2, 0.75, -0.55], size: [0.5, 2.0, 0.5], accent: true },
  { pos: [0.25, -0.4, 1.2], size: [1.15, 0.36, 0.72] },
  { pos: [-1.85, -0.2, 0.6], size: [0.72, 0.92, 0.72] },
];

function Massing() {
  const g = useRef<Group>(null);
  const reduce = useReducedMotion();
  useFrame((_, dt) => {
    if (g.current && !reduce) g.current.rotation.y += dt * 0.09;
  });
  return (
    <group ref={g} rotation={[0, -0.5, 0]}>
      {BLOCKS.map((b, i) => (
        <mesh key={i} position={b.pos}>
          <boxGeometry args={b.size} />
          <meshStandardMaterial
            color={b.accent ? PENCIL : FACE}
            roughness={0.82}
            metalness={0}
          />
          <Edges threshold={12} color={b.accent ? PENCIL_EDGE : INK} />
        </mesh>
      ))}
    </group>
  );
}

export default function HeroScene() {
  const reduce = useReducedMotion();
  return (
    <Canvas
      dpr={[1, 2]}
      camera={{ position: [5.2, 3.3, 6.4], fov: 38 }}
      gl={{ antialias: true, alpha: true }}
      style={{ width: "100%", height: "100%" }}
      aria-hidden="true"
    >
      <ambientLight intensity={0.75} />
      <directionalLight position={[5, 9, 4]} intensity={1.15} />
      <directionalLight position={[-6, 3, -2]} intensity={0.35} />
      {/* Bounds auto-frames the model to the canvas at any aspect (fixes the
          narrow-mobile crop); Center balances it for the slow rotation. */}
      <Bounds fit clip observe margin={1.2}>
        <Center>
          <Float
            speed={reduce ? 0 : 1.1}
            rotationIntensity={reduce ? 0 : 0.22}
            floatIntensity={reduce ? 0 : 0.7}
            floatingRange={[-0.12, 0.12]}
          >
            <Massing />
          </Float>
        </Center>
      </Bounds>
    </Canvas>
  );
}
