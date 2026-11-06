import { useEffect, useMemo } from 'react';
import { Text } from '@react-three/drei';
import type { ThreeEvent } from '@react-three/fiber';
import { BufferGeometry, Color, DoubleSide, Float32BufferAttribute, FrontSide } from 'three';

import type { LandmarkPart, StageLandmark } from '../../../spatial/spatialTypes';
import { HELPER_FLAG } from '../../lib/capture';
import { SELECTION_COLOR, landmarkColor } from '../stageLook';

interface Props {
  landmark: StageLandmark;
  selected: boolean;
  labelled: boolean;
  onPick?: (event: ThreeEvent<MouseEvent>) => void;
}

// A ramp in a unit cube: full height at -Z, running down to the floor at +Z.
const WEDGE_VERTICES = [
  // slope
  -0.5, 0.5, -0.5, -0.5, -0.5, 0.5, 0.5, -0.5, 0.5, -0.5, 0.5, -0.5, 0.5, -0.5, 0.5, 0.5, 0.5, -0.5,
  // back
  -0.5, -0.5, -0.5, -0.5, 0.5, -0.5, 0.5, 0.5, -0.5, -0.5, -0.5, -0.5, 0.5, 0.5, -0.5, 0.5, -0.5, -0.5,
  // bottom
  -0.5, -0.5, -0.5, 0.5, -0.5, -0.5, 0.5, -0.5, 0.5, -0.5, -0.5, -0.5, 0.5, -0.5, 0.5, -0.5, -0.5, 0.5,
  // sides
  -0.5, -0.5, -0.5, -0.5, -0.5, 0.5, -0.5, 0.5, -0.5,
  0.5, -0.5, -0.5, 0.5, 0.5, -0.5, 0.5, -0.5, 0.5,
];

function WedgeGeometry() {
  const geometry = useMemo(() => {
    const wedge = new BufferGeometry();
    wedge.setAttribute('position', new Float32BufferAttribute(WEDGE_VERTICES, 3));
    wedge.computeVertexNormals();
    return wedge;
  }, []);
  // Built by hand, so R3F does not own it: release it with the prop.
  useEffect(() => () => geometry.dispose(), [geometry]);
  return <primitive object={geometry} attach="geometry" />;
}

function ShapeGeometry({ shape }: { shape: StageLandmark['shape'] }) {
  switch (shape) {
    case 'cylinder': return <cylinderGeometry args={[0.5, 0.5, 1, 32]} />;
    case 'sphere': return <sphereGeometry args={[0.5, 28, 20]} />;
    case 'cone': return <coneGeometry args={[0.5, 1, 32]} />;
    case 'wedge': return <WedgeGeometry />;
    case 'plane': return <planeGeometry args={[1, 1]} />;
    default: return <boxGeometry args={[1, 1, 1]} />;
  }
}

const DEGREES = Math.PI / 180;
const TONE_FACTOR = { '': 1, dark: 0.62, light: 1.28 } as const;

function partColor(base: string, tone: LandmarkPart['tone']) {
  const factor = TONE_FACTOR[tone ?? ''];
  return factor === 1 ? base : `#${new Color(base).multiplyScalar(factor).getHexString()}`;
}

/** A piece built from several volumes. Each is scaled on its own, before its rotation, so a stretched cart keeps round wheels. */
function PartsProp({ landmark, selected }: Pick<Props, 'landmark' | 'selected'>) {
  const [width, depth, height] = landmark.size;
  const base = landmarkColor(landmark);
  return (
    <>
      {(landmark.parts ?? []).map((part, index) => (
        <mesh
          key={index}
          position={[part.center[0] * width, part.center[1] * height, part.center[2] * depth]}
          rotation={[(part.rotation?.[0] ?? 0) * DEGREES, (part.rotation?.[1] ?? 0) * DEGREES, (part.rotation?.[2] ?? 0) * DEGREES]}
          scale={[part.size[0] * width, part.size[2] * height, part.size[1] * depth]}
          castShadow
          receiveShadow
        >
          <ShapeGeometry shape={part.shape} />
          <meshStandardMaterial
            color={partColor(base, part.tone)} roughness={0.8} side={part.shape === 'wedge' || part.shape === 'plane' ? DoubleSide : FrontSide}
            emissive={selected ? SELECTION_COLOR : '#fcebee'} emissiveIntensity={selected ? 0.35 : 0}
          />
        </mesh>
      ))}
    </>
  );
}

/** Unit geometry scaled to `size`, so a scale drag never rebuilds a buffer. */
export function PrimitiveProp({ landmark, selected, labelled, onPick }: Props) {
  const [width, depth, height] = landmark.size;
  const shape = landmark.shape ?? 'box';
  // A plane is an upright panel (a backdrop, a screen, a window): width by height, no depth.
  const scale: [number, number, number] = shape === 'plane' ? [width, height, 1] : [width, height, depth];
  return (
    <group position={[landmark.position[0], landmark.elevation_m ?? 0, landmark.position[1]]} rotation={[0, ((landmark.yaw_deg ?? 0) * Math.PI) / 180, 0]} onClick={onPick}>
      {landmark.parts?.length ? <PartsProp landmark={landmark} selected={selected} /> : (
        <mesh position={[0, height / 2, 0]} scale={scale} castShadow receiveShadow>
          <ShapeGeometry shape={shape} />
          <meshStandardMaterial
            color={landmarkColor(landmark)} roughness={0.8} transparent={landmark.origin !== 'blockout'} opacity={landmark.origin === 'blockout' ? 1 : 0.88} side={shape === 'plane' || shape === 'wedge' ? DoubleSide : FrontSide}
            emissive={selected ? SELECTION_COLOR : '#fcebee'} emissiveIntensity={selected ? 0.35 : 0}
          />
        </mesh>
      )}
      {labelled && (
        <Text position={[0, height + 0.18, 0]} fontSize={0.13} color={selected ? SELECTION_COLOR : '#46373e'} anchorX="center" anchorY="bottom" userData={{ [HELPER_FLAG]: true }}>
          {landmark.name}
        </Text>
      )}
    </group>
  );
}
