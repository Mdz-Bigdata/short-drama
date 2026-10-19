import { useMemo } from 'react';
import { Line, Text } from '@react-three/drei';
import type { ThreeEvent } from '@react-three/fiber';

import { parseAspect } from '../../spatial/floorPlanGeometry';
import type { StageCamera } from '../../spatial/spatialTypes';
import { SELECTION_COLOR } from './stageLook';

type Point = [number, number, number];

interface Props {
  camera: StageCamera;
  label: string;
  /** The lens that films the selected shot, or the one the lens view looks through. */
  active: boolean;
  selected: boolean;
  targetSelected: boolean;
  onPick?: (event: ThreeEvent<MouseEvent>) => void;
  onPickTarget?: (event: ThreeEvent<MouseEvent>) => void;
}

/** The four rays and the far rectangle of a frustum that really has the lens's field of view. */
function frustumLines(camera: StageCamera, reach: number): Point[][] {
  const { position, target } = camera;
  const forward = [target[0] - position[0], target[1] - position[1], target[2] - position[2]];
  const length = Math.hypot(...forward) || 1;
  const f = forward.map(value => value / length);
  const upGuess = Math.abs(f[1]) > 0.999 ? [0, 0, -1] : [0, 1, 0];
  const right = [f[1] * upGuess[2] - f[2] * upGuess[1], f[2] * upGuess[0] - f[0] * upGuess[2], f[0] * upGuess[1] - f[1] * upGuess[0]];
  const rightLength = Math.hypot(...right) || 1;
  const r = right.map(value => value / rightLength);
  const u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]];
  const halfHeight = Math.tan((camera.fov_deg * Math.PI) / 360) * reach;
  const halfWidth = halfHeight * parseAspect(camera.aspect);
  const corner = (sx: number, sy: number): Point => [
    position[0] + f[0] * reach + r[0] * halfWidth * sx + u[0] * halfHeight * sy,
    position[1] + f[1] * reach + r[1] * halfWidth * sx + u[1] * halfHeight * sy,
    position[2] + f[2] * reach + r[2] * halfWidth * sx + u[2] * halfHeight * sy,
  ];
  const corners = [corner(-1, -1), corner(1, -1), corner(1, 1), corner(-1, 1)];
  const apex: Point = [position[0], position[1], position[2]];
  return [...corners.map(point => [apex, point]), [...corners, corners[0]]];
}

export function CameraRig({ camera, label, active, selected, targetSelected, onPick, onPickTarget }: Props) {
  const open = active || selected || targetSelected;
  const lines = useMemo(() => {
    const distance = Math.hypot(camera.target[0] - camera.position[0], camera.target[1] - camera.position[1], camera.target[2] - camera.position[2]);
    return frustumLines(camera, open ? Math.min(Math.max(distance, 0.5), 8) : 0.7);
  }, [camera, open]);
  const color = selected || targetSelected ? SELECTION_COLOR : active ? '#e65100' : '#957884';
  return (
    <group>
      {lines.map((points, index) => <Line key={index} points={points} color={color} lineWidth={open ? 1.6 : 0.8} />)}
      <mesh position={camera.position} onClick={onPick}>
        <boxGeometry args={[0.22, 0.16, 0.28]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={selected ? 0.5 : 0.1} />
      </mesh>
      <Text position={[camera.position[0], camera.position[1] + 0.24, camera.position[2]]} fontSize={0.13} color={color} anchorX="center">{label}</Text>
      {open && (
        <>
          <Line points={[camera.position, camera.target]} color={color} lineWidth={0.8} dashed dashSize={0.12} gapSize={0.1} />
          {/* The look-at handle: drag it and the lens pans and tilts to follow. */}
          <mesh position={camera.target} onClick={onPickTarget}>
            <sphereGeometry args={[0.09, 16, 12]} />
            <meshBasicMaterial color={targetSelected ? SELECTION_COLOR : color} />
          </mesh>
        </>
      )}
    </group>
  );
}
