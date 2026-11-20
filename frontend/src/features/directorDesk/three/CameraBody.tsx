import { useMemo } from 'react';
import type { ThreeEvent } from '@react-three/fiber';
import { Object3D, type Quaternion } from 'three';

type Point = [number, number, number];

/** The longest side of the body, lens hood included: what a screen-sized wrapper scales by. */
export const CAMERA_BODY_SIZE_M = 0.36;

/** The turn that points a body's lens (+Z) from `position` at `target`; no turn when the two coincide. */
function aimQuaternion(position: Point, target: Point): Quaternion {
  const probe = new Object3D();
  probe.position.set(...position);
  if (position.some((value, index) => value !== target[index])) probe.lookAt(...target);
  return probe.quaternion.clone();
}

const NO_HIT = () => undefined;

interface Props {
  /** Where the lens points; the body turns to face it. */
  position: Point;
  target: Point;
  color: string;
  glow?: number;
  /** A ghost on a key of the route: see-through, and it never takes a click. */
  ghost?: boolean;
  onClick?: (event: ThreeEvent<MouseEvent>) => void;
  onPointerOver?: (event: ThreeEvent<PointerEvent>) => void;
  onPointerOut?: (event: ThreeEvent<PointerEvent>) => void;
  onDoubleClick?: (event: ThreeEvent<MouseEvent>) => void;
}

/**
 * A lens drawn as a camera: a body, a barrel with a hood on the side it films from, and a handle on
 * top, so which way it looks reads from any angle without following its sight line. Drawn at the
 * origin of its parent, which stands at `position`.
 */
export function CameraBody({ position, target, color, glow = 0.1, ghost = false, ...pointer }: Props) {
  const [px, py, pz] = position;
  const [tx, ty, tz] = target;
  const turn = useMemo(() => aimQuaternion([px, py, pz], [tx, ty, tz]), [px, py, pz, tx, ty, tz]);
  const material = ghost
    ? <meshBasicMaterial color={color} transparent opacity={0.32} depthWrite={false} />
    : <meshStandardMaterial color={color} emissive={color} emissiveIntensity={glow} />;
  // A ghost is looked at, never picked: a ray goes straight through it to whatever stands behind.
  const inert = ghost ? { raycast: NO_HIT } : undefined;
  return (
    <group quaternion={turn} {...(ghost ? undefined : pointer)}>
      <mesh {...inert}>
        <boxGeometry args={[0.22, 0.16, 0.26]} />
        {material}
      </mesh>
      <mesh position={[0, 0, 0.18]} rotation={[Math.PI / 2, 0, 0]} {...inert}>
        <cylinderGeometry args={[0.055, 0.055, 0.1, 14]} />
        {material}
      </mesh>
      <mesh position={[0, 0, 0.255]} rotation={[Math.PI / 2, 0, 0]} {...inert}>
        <cylinderGeometry args={[0.085, 0.06, 0.05, 14]} />
        {material}
      </mesh>
      <mesh position={[0, 0.105, -0.02]} {...inert}>
        <boxGeometry args={[0.05, 0.05, 0.16]} />
        {material}
      </mesh>
    </group>
  );
}
