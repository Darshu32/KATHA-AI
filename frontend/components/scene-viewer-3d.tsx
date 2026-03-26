"use client";

import { Canvas } from "@react-three/fiber";
import { Environment, OrbitControls, ContactShadows } from "@react-three/drei";
import { useDesignGraphStore } from "../lib/store";
import * as THREE from "three";

interface Vec3 {
  x: number;
  y: number;
  z: number;
}

interface Dimensions {
  length: number;
  width: number;
  height: number;
}

interface DesignObj {
  id: string;
  type: string;
  name?: string;
  position?: Vec3;
  rotation?: Vec3;
  dimensions?: Dimensions;
  color?: string;
}

interface SceneViewer3DProps {
  className?: string;
}

function edgesForBox(width: number, height: number, depth: number) {
  return new THREE.EdgesGeometry(new THREE.BoxGeometry(width, height, depth));
}

function SelectionOutline({
  width,
  height,
  depth,
}: {
  width: number;
  height: number;
  depth: number;
}) {
  return (
    <lineSegments>
      <primitive object={edgesForBox(width, height, depth)} attach="geometry" />
      <lineBasicMaterial color="#d97706" />
    </lineSegments>
  );
}

function FloorMaterial() {
  return (
    <meshStandardMaterial
      color="#d7c5ac"
      roughness={0.82}
      metalness={0.02}
    />
  );
}

function WallMaterial() {
  return (
    <meshStandardMaterial
      color="#f4ede1"
      roughness={0.94}
      metalness={0}
    />
  );
}

function RoomShell({
  length,
  width,
  height,
}: {
  length: number;
  width: number;
  height: number;
}) {
  const wallThickness = 0.18;
  const ceilingY = height;
  const windowWidth = Math.min(length * 0.28, 3.8);
  const windowHeight = Math.min(height * 0.32, 3.2);
  const windowSill = height * 0.42;
  const doorWidth = Math.min(length * 0.16, 2.4);
  const doorHeight = Math.min(height * 0.72, 7.2);

  return (
    <group>
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[length / 2, 0, width / 2]}
        receiveShadow
      >
        <planeGeometry args={[length, width]} />
        <FloorMaterial />
      </mesh>

      <mesh position={[length / 2, ceilingY, width / 2]} receiveShadow>
        <boxGeometry args={[length, 0.08, width]} />
        <meshStandardMaterial color="#fbf7f0" roughness={1} />
      </mesh>

      <mesh position={[length / 2, height / 2, wallThickness / 2]} receiveShadow>
        <boxGeometry args={[length, height, wallThickness]} />
        <WallMaterial />
      </mesh>
      <mesh position={[wallThickness / 2, height / 2, width / 2]} receiveShadow>
        <boxGeometry args={[wallThickness, height, width]} />
        <WallMaterial />
      </mesh>
      <mesh position={[length - wallThickness / 2, height / 2, width / 2]} receiveShadow>
        <boxGeometry args={[wallThickness, height, width]} />
        <WallMaterial />
      </mesh>

      <mesh position={[length / 2, 0.02, width / 2]} receiveShadow>
        <boxGeometry args={[length + 0.5, 0.02, width + 0.5]} />
        <meshStandardMaterial color="#c8baa5" transparent opacity={0.35} />
      </mesh>

      <group position={[length * 0.72, windowSill + windowHeight / 2, wallThickness + 0.01]}>
        <mesh>
          <boxGeometry args={[windowWidth, windowHeight, 0.05]} />
          <meshStandardMaterial
            color="#cfe3ef"
            transparent
            opacity={0.45}
            roughness={0.05}
            metalness={0.15}
          />
        </mesh>
        <mesh position={[0, 0, -0.01]}>
          <boxGeometry args={[windowWidth + 0.14, windowHeight + 0.14, 0.04]} />
          <meshStandardMaterial color="#d2c5b6" roughness={0.8} />
        </mesh>
      </group>

      <group position={[length * 0.12, doorHeight / 2, wallThickness + 0.02]}>
        <mesh>
          <boxGeometry args={[doorWidth, doorHeight, 0.08]} />
          <meshStandardMaterial color="#8f5f37" roughness={0.74} />
        </mesh>
        <mesh position={[doorWidth * 0.34, 0, 0.06]}>
          <sphereGeometry args={[0.06, 18, 18]} />
          <meshStandardMaterial color="#caa56a" metalness={0.35} roughness={0.3} />
        </mesh>
      </group>
    </group>
  );
}

function FurnitureWrapper({
  obj,
  children,
  onSelect,
}: {
  obj: DesignObj;
  children: React.ReactNode;
  onSelect: (id: string) => void;
}) {
  const pos = obj.position ?? { x: 0, y: 0, z: 0 };
  const rot = obj.rotation ?? { x: 0, y: 0, z: 0 };

  return (
    <group
      position={[pos.x, pos.y ?? 0, pos.z]}
      rotation={[rot.x ?? 0, rot.y ?? 0, rot.z ?? 0]}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(obj.id);
      }}
    >
      {children}
    </group>
  );
}

function SofaMesh({
  obj,
  isSelected,
  onSelect,
}: {
  obj: DesignObj;
  isSelected: boolean;
  onSelect: (id: string) => void;
}) {
  const dims = obj.dimensions ?? { length: 7, width: 3, height: 3 };
  const color = obj.color ?? "#d8c5af";
  const seatHeight = dims.height * 0.45;
  const armWidth = Math.max(dims.width * 0.12, 0.18);
  const backDepth = Math.max(dims.length * 0.08, 0.18);

  return (
    <FurnitureWrapper obj={obj} onSelect={onSelect}>
      <group position={[0, seatHeight / 2, 0]}>
        <mesh castShadow receiveShadow>
          <boxGeometry args={[dims.width, seatHeight, dims.length * 0.92]} />
          <meshStandardMaterial color={color} roughness={0.88} />
        </mesh>
      </group>

      <group position={[0, seatHeight + (dims.height - seatHeight) / 2, -(dims.length / 2) + backDepth / 2]}>
        <mesh castShadow receiveShadow>
          <boxGeometry args={[dims.width, dims.height - seatHeight, backDepth]} />
          <meshStandardMaterial color={color} roughness={0.9} />
        </mesh>
      </group>

      {[-1, 1].map((side) => (
        <group
          key={side}
          position={[
            side * (dims.width / 2 - armWidth / 2),
            dims.height / 2,
            0,
          ]}
        >
          <mesh castShadow receiveShadow>
            <boxGeometry args={[armWidth, dims.height, dims.length * 0.78]} />
            <meshStandardMaterial color={color} roughness={0.9} />
          </mesh>
        </group>
      ))}

      {isSelected && (
        <group position={[0, dims.height / 2, 0]}>
          <SelectionOutline width={dims.width} height={dims.height} depth={dims.length} />
        </group>
      )}
    </FurnitureWrapper>
  );
}

function TableMesh({
  obj,
  isSelected,
  onSelect,
}: {
  obj: DesignObj;
  isSelected: boolean;
  onSelect: (id: string) => void;
}) {
  const dims = obj.dimensions ?? { length: 3.5, width: 2, height: 1.5 };
  const color = obj.color ?? "#9b6b3d";
  const topThickness = Math.max(dims.height * 0.14, 0.08);
  const legWidth = Math.max(Math.min(dims.width, dims.length) * 0.08, 0.08);
  const legOffsetX = dims.width / 2 - legWidth;
  const legOffsetZ = dims.length / 2 - legWidth;

  return (
    <FurnitureWrapper obj={obj} onSelect={onSelect}>
      <group position={[0, dims.height - topThickness / 2, 0]}>
        <mesh castShadow receiveShadow>
          <boxGeometry args={[dims.width, topThickness, dims.length]} />
          <meshStandardMaterial color={color} roughness={0.65} />
        </mesh>
      </group>

      {[-1, 1].flatMap((xSign) =>
        [-1, 1].map((zSign) => (
          <group
            key={`${xSign}-${zSign}`}
            position={[
              xSign * legOffsetX,
              (dims.height - topThickness) / 2,
              zSign * legOffsetZ,
            ]}
          >
            <mesh castShadow receiveShadow>
              <boxGeometry args={[legWidth, dims.height - topThickness, legWidth]} />
              <meshStandardMaterial color="#765132" roughness={0.7} />
            </mesh>
          </group>
        )),
      )}

      {isSelected && (
        <group position={[0, dims.height / 2, 0]}>
          <SelectionOutline width={dims.width} height={dims.height} depth={dims.length} />
        </group>
      )}
    </FurnitureWrapper>
  );
}

function ChairMesh({
  obj,
  isSelected,
  onSelect,
}: {
  obj: DesignObj;
  isSelected: boolean;
  onSelect: (id: string) => void;
}) {
  const dims = obj.dimensions ?? { length: 2.5, width: 2.2, height: 3 };
  const color = obj.color ?? "#d6c3af";
  const seatHeight = dims.height * 0.45;
  const backDepth = Math.max(dims.length * 0.12, 0.1);

  return (
    <FurnitureWrapper obj={obj} onSelect={onSelect}>
      <group position={[0, seatHeight / 2, 0]}>
        <mesh castShadow receiveShadow>
          <boxGeometry args={[dims.width, seatHeight, dims.length * 0.75]} />
          <meshStandardMaterial color={color} roughness={0.88} />
        </mesh>
      </group>
      <group position={[0, seatHeight + (dims.height - seatHeight) / 2, -(dims.length / 2) + backDepth / 2]}>
        <mesh castShadow receiveShadow>
          <boxGeometry args={[dims.width, dims.height - seatHeight, backDepth]} />
          <meshStandardMaterial color={color} roughness={0.9} />
        </mesh>
      </group>
      {isSelected && (
        <group position={[0, dims.height / 2, 0]}>
          <SelectionOutline width={dims.width} height={dims.height} depth={dims.length} />
        </group>
      )}
    </FurnitureWrapper>
  );
}

function GenericObjectMesh({
  obj,
  isSelected,
  onSelect,
}: {
  obj: DesignObj;
  isSelected: boolean;
  onSelect: (id: string) => void;
}) {
  const dims = obj.dimensions ?? { length: 1, width: 1, height: 1 };
  const color = obj.color ?? "#c8b8a2";

  return (
    <FurnitureWrapper obj={obj} onSelect={onSelect}>
      <group position={[0, dims.height / 2, 0]}>
        <mesh castShadow receiveShadow>
          <boxGeometry args={[dims.width, dims.height, dims.length]} />
          <meshStandardMaterial
            color={isSelected ? "#d97706" : color}
            roughness={0.82}
          />
        </mesh>
        {isSelected && (
          <SelectionOutline width={dims.width} height={dims.height} depth={dims.length} />
        )}
      </group>
    </FurnitureWrapper>
  );
}

function RugMesh({
  obj,
  isSelected,
  onSelect,
}: {
  obj: DesignObj;
  isSelected: boolean;
  onSelect: (id: string) => void;
}) {
  const dims = obj.dimensions ?? { length: 7, width: 5, height: 0.05 };
  const color = obj.color ?? "#d8ccb9";

  return (
    <FurnitureWrapper obj={obj} onSelect={onSelect}>
      <group position={[0, dims.height / 2, 0]}>
        <mesh receiveShadow>
          <boxGeometry args={[dims.width, dims.height, dims.length]} />
          <meshStandardMaterial color={color} roughness={0.96} />
        </mesh>
        {isSelected && (
          <SelectionOutline width={dims.width} height={Math.max(dims.height, 0.08)} depth={dims.length} />
        )}
      </group>
    </FurnitureWrapper>
  );
}

function FloorLampMesh({
  obj,
  isSelected,
  onSelect,
}: {
  obj: DesignObj;
  isSelected: boolean;
  onSelect: (id: string) => void;
}) {
  const dims = obj.dimensions ?? { length: 1.2, width: 1.2, height: 5.8 };
  const color = obj.color ?? "#5f5245";

  return (
    <FurnitureWrapper obj={obj} onSelect={onSelect}>
      <mesh position={[0, 0.08, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[0.45, 0.52, 0.16, 24]} />
        <meshStandardMaterial color={color} roughness={0.55} metalness={0.25} />
      </mesh>
      <mesh position={[0, dims.height * 0.45, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[0.05, 0.05, dims.height * 0.78, 18]} />
        <meshStandardMaterial color={color} roughness={0.4} metalness={0.35} />
      </mesh>
      <mesh position={[0, dims.height * 0.85, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[0.48, 0.68, dims.height * 0.24, 28]} />
        <meshStandardMaterial color="#f0e1cb" roughness={0.92} />
      </mesh>
      {isSelected && (
        <group position={[0, dims.height / 2, 0]}>
          <SelectionOutline width={dims.width} height={dims.height} depth={dims.length} />
        </group>
      )}
    </FurnitureWrapper>
  );
}

function PlantMesh({
  obj,
  isSelected,
  onSelect,
}: {
  obj: DesignObj;
  isSelected: boolean;
  onSelect: (id: string) => void;
}) {
  const dims = obj.dimensions ?? { length: 1.4, width: 1.4, height: 4 };

  return (
    <FurnitureWrapper obj={obj} onSelect={onSelect}>
      <mesh position={[0, 0.42, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[0.36, 0.28, 0.84, 20]} />
        <meshStandardMaterial color="#b1764d" roughness={0.84} />
      </mesh>
      <mesh position={[0, dims.height * 0.55, 0]} castShadow receiveShadow>
        <sphereGeometry args={[0.95, 20, 20]} />
        <meshStandardMaterial color="#7c9560" roughness={0.96} />
      </mesh>
      {isSelected && (
        <group position={[0, dims.height / 2, 0]}>
          <SelectionOutline width={dims.width} height={dims.height} depth={dims.length} />
        </group>
      )}
    </FurnitureWrapper>
  );
}

function WallArtMesh({
  obj,
  isSelected,
  onSelect,
}: {
  obj: DesignObj;
  isSelected: boolean;
  onSelect: (id: string) => void;
}) {
  const dims = obj.dimensions ?? { length: 0.1, width: 3, height: 2 };
  const color = obj.color ?? "#d7b18f";

  return (
    <FurnitureWrapper obj={obj} onSelect={onSelect}>
      <mesh castShadow receiveShadow>
        <boxGeometry args={[dims.width, dims.height, Math.max(dims.length, 0.08)]} />
        <meshStandardMaterial color={color} roughness={0.92} />
      </mesh>
      {isSelected && (
        <SelectionOutline width={dims.width} height={dims.height} depth={Math.max(dims.length, 0.08)} />
      )}
    </FurnitureWrapper>
  );
}

function SceneObject({
  obj,
  isSelected,
  onSelect,
}: {
  obj: DesignObj;
  isSelected: boolean;
  onSelect: (id: string) => void;
}) {
  const type = obj.type.toLowerCase();

  if (type.includes("sofa")) {
    return <SofaMesh obj={obj} isSelected={isSelected} onSelect={onSelect} />;
  }

  if (type.includes("table")) {
    return <TableMesh obj={obj} isSelected={isSelected} onSelect={onSelect} />;
  }

  if (type.includes("chair")) {
    return <ChairMesh obj={obj} isSelected={isSelected} onSelect={onSelect} />;
  }

  if (type.includes("rug")) {
    return <RugMesh obj={obj} isSelected={isSelected} onSelect={onSelect} />;
  }

  if (type.includes("lamp")) {
    return <FloorLampMesh obj={obj} isSelected={isSelected} onSelect={onSelect} />;
  }

  if (type.includes("plant")) {
    return <PlantMesh obj={obj} isSelected={isSelected} onSelect={onSelect} />;
  }

  if (type.includes("art")) {
    return <WallArtMesh obj={obj} isSelected={isSelected} onSelect={onSelect} />;
  }

  return <GenericObjectMesh obj={obj} isSelected={isSelected} onSelect={onSelect} />;
}

function CameraRig({
  roomLength,
  roomWidth,
}: {
  roomLength: number;
  roomWidth: number;
}) {
  const center = new THREE.Vector3(roomWidth / 2, 1.5, roomLength / 2);

  return (
    <OrbitControls
      makeDefault
      enableDamping
      dampingFactor={0.08}
      target={center}
      minDistance={8}
      maxDistance={26}
      minPolarAngle={0.45}
      maxPolarAngle={1.35}
      maxAzimuthAngle={Math.PI / 2.4}
      minAzimuthAngle={-Math.PI / 2.4}
    />
  );
}

export default function SceneViewer3D({ className = "" }: SceneViewer3DProps) {
  const graphData = useDesignGraphStore((state) => state.graphData);
  const selectedObjectId = useDesignGraphStore((state) => state.selectedObjectId);
  const selectObject = useDesignGraphStore((state) => state.selectObject);

  const objects = (graphData?.objects as DesignObj[]) ?? [];
  const spaces = (graphData?.spaces as Array<{ dimensions?: Partial<Dimensions> }>) ?? [];
  const roomDims = spaces[0]?.dimensions;
  const roomLength = roomDims?.length ?? 15;
  const roomWidth = roomDims?.width ?? 12;
  const roomHeight = roomDims?.height ?? 10;

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
    <div className={`overflow-hidden rounded-[2rem] border border-black/10 bg-[#f4ede2] ${className}`}>
      <Canvas
        shadows
        camera={{
          position: [roomWidth * 0.95, roomHeight * 0.72, roomLength * 1.08],
          fov: 42,
        }}
        onPointerMissed={() => selectObject(null)}
      >
        <color attach="background" args={["#f4ede2"]} />
        <fog attach="fog" args={["#f4ede2", 16, 34]} />

        <ambientLight intensity={1.1} />
        <hemisphereLight
          color="#fff8ed"
          groundColor="#baa88f"
          intensity={0.9}
        />
        <directionalLight
          position={[roomWidth * 0.6, roomHeight * 1.3, roomLength * 0.3]}
          intensity={1.2}
          castShadow
          shadow-mapSize-width={2048}
          shadow-mapSize-height={2048}
        />

        <RoomShell length={roomWidth} width={roomLength} height={roomHeight} />

        {objects.map((obj) => (
          <SceneObject
            key={obj.id}
            obj={obj}
            isSelected={obj.id === selectedObjectId}
            onSelect={selectObject}
          />
        ))}

        <ContactShadows
          position={[roomWidth / 2, 0.01, roomLength / 2]}
          scale={Math.max(roomWidth, roomLength) * 1.4}
          blur={1.8}
          opacity={0.32}
          far={20}
        />

        <CameraRig roomLength={roomLength} roomWidth={roomWidth} />
        <Environment preset="apartment" />
      </Canvas>
    </div>
  );
}
