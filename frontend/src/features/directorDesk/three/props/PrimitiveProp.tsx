import { useEffect, useMemo } from 'react';
import { Text } from '@react-three/drei';
import type { ThreeEvent } from '@react-three/fiber';
import { BufferGeometry, DoubleSide, Float32BufferAttribute, FrontSide } from 'three';

import type { StageLandmark } from '../../../spatial/spatialTypes';
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

/** Unit geometry scaled to `size`, so a scale drag never rebuilds a buffer. */
export function PrimitiveProp({ landmark, selected, labelled, onPick }: Props) {
  const [width, depth, height] = landmark.size;
  const shape = landmark.shape ?? 'box';
  // A plane is an upright panel (a backdrop, a screen, a window): width by height, no depth.
  const scale: [number, number, number] = shape === 'plane' ? [width, height, 1] : [width, height, depth];
  return (
    <group position={[landmark.position[0], 0, landmark.position[1]]} rotation={[0, ((landmark.yaw_deg ?? 0) * Math.PI) / 180, 0]} onClick={onPick}>
      <mesh position={[0, height / 2, 0]} scale={scale}>
        <ShapeGeometry shape={shape} />
        <meshStandardMaterial
          color={landmarkColor(landmark)} roughness={0.8} transparent opacity={0.88} side={shape === 'plane' || shape === 'wedge' ? DoubleSide : FrontSide}
          emissive={selected ? SELECTION_COLOR : '#fcebee'} emissiveIntensity={selected ? 0.35 : 0}
        />
      </mesh>
      {labelled && (
        <Text position={[0, height + 0.18, 0]} fontSize={0.13} color={selected ? SELECTION_COLOR : '#46373e'} anchorX="center" anchorY="bottom" userData={{ [HELPER_FLAG]: true }}>
          {landmark.name}
        </Text>
      )}
    </group>
  );
}
