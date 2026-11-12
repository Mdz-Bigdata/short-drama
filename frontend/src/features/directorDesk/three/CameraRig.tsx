import { useMemo } from 'react';
import { Line } from '@react-three/drei';
import type { ThreeEvent } from '@react-three/fiber';

import { parseAspect } from '../../spatial/floorPlanGeometry';
import type { StageCamera } from '../../spatial/spatialTypes';
import { frustumReach } from '../lib/viewHelpers';
import { ScreenLifted, ScreenSized } from './ScreenSized';
import { StageLabel } from './StageLabel';
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
  /** Pointer handlers for the two things of a lens that can be picked: its body and its look-at handle. */
  bodyPointer?: PointerHandlers;
  targetPointer?: PointerHandlers;
}

export interface PointerHandlers {
  onPointerOver?: (event: ThreeEvent<PointerEvent>) => void;
  onPointerOut?: (event: ThreeEvent<PointerEvent>) => void;
  onDoubleClick?: (event: ThreeEvent<MouseEvent>) => void;
}

/** The body and the look-at handle keep at least this many pixels across, so a lens across a street can still be picked. */
const BODY_PIXELS = 16;
const TARGET_PIXELS = 14;
/** The body's box, and the longest side of it. */
const BODY_BOX: Point = [0.22, 0.16, 0.28];
const BODY_SIZE_M = 0.28;
/** How far over the lens its label sits while the body is its real size. */
const LABEL_LIFT_M = 0.24;
const AT_ANCHOR: Point = [0, 0, 0];

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

export function CameraRig({ camera, label, active, selected, targetSelected, onPick, onPickTarget, bodyPointer, targetPointer }: Props) {
  const picked = selected || targetSelected;
  const open = active || picked;
  const lines = useMemo(() => {
    const distance = Math.hypot(camera.target[0] - camera.position[0], camera.target[1] - camera.position[1], camera.target[2] - camera.position[2]);
    return frustumLines(camera, frustumReach(distance, picked ? 'selected' : active ? 'active' : 'idle'));
  }, [active, camera, picked]);
  // A new array would have drei rebuild the line each time the desk renders, which is every frame of playback.
  const sightLine = useMemo(() => [camera.position, camera.target], [camera.position, camera.target]);
  const color = picked ? SELECTION_COLOR : active ? '#e65100' : '#957884';
  // The frustum is a helper, not scenery: only the lens in hand draws solid rays, and the far
  // rectangle (the last line) is always the faintest part, so the cast stays readable through it.
  const rayWidth = picked ? 1.2 : active ? 1 : 0.8;
  const rayOpacity = picked ? 0.9 : active ? 0.55 : 1;
  return (
    <group>
      {lines.map((points, index) => {
        const opacity = open && index === lines.length - 1 ? rayOpacity * 0.5 : rayOpacity;
        return <Line key={index} points={points} color={color} lineWidth={rayWidth} transparent opacity={opacity} />;
      })}
      <ScreenSized position={camera.position} size={BODY_SIZE_M} minPixels={BODY_PIXELS}>
        <mesh onClick={onPick} {...bodyPointer}>
          <boxGeometry args={BODY_BOX} />
          <meshStandardMaterial color={color} emissive={color} emissiveIntensity={selected ? 0.5 : 0.1} />
        </mesh>
      </ScreenSized>
      {/* The label rises with the body: from across a street the enlarged box would otherwise cover the foot of the number. */}
      <ScreenLifted position={camera.position} lift={LABEL_LIFT_M} size={BODY_SIZE_M} minPixels={BODY_PIXELS}>
        <StageLabel position={AT_ANCHOR} fontSize={0.13} color={color} kind="camera" selected={picked}>{label}</StageLabel>
      </ScreenLifted>
      {open && (
        <>
          <Line points={sightLine} color={color} lineWidth={0.8} dashed dashSize={0.12} gapSize={0.1} transparent opacity={picked ? 1 : 0.6} />
          {/* The look-at handle: drag it and the lens pans and tilts to follow. */}
          <ScreenSized position={camera.target} size={0.18} minPixels={TARGET_PIXELS}>
            <mesh onClick={onPickTarget} {...targetPointer}>
              <sphereGeometry args={[0.09, 16, 12]} />
              <meshBasicMaterial color={targetSelected ? SELECTION_COLOR : color} />
            </mesh>
          </ScreenSized>
        </>
      )}
    </group>
  );
}
