import { useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { Line } from '@react-three/drei';
import { useFrame, useThree } from '@react-three/fiber';
import { Quaternion, Vector3, type Group } from 'three';

import type { SpacePoint } from '../../spatial/spatialTypes';
import { HELPER_FLAG } from '../lib/capture';
import { ghostKeys, keyStamp, pulseTime, trailArrows, trailSpot, type Trail } from '../lib/trails';
import { CAMERA_BODY_SIZE_M, CameraBody } from './CameraBody';
import { ScreenSized } from './ScreenSized';
import { StageLabel } from './StageLabel';

/** Lines on the floor sit just above it so the ground plane does not swallow them. */
const FLOOR_LIFT = 0.03;
const UP = new Vector3(0, 1, 0);
/** A ghost this close to the lens itself would only smear it. */
const GHOST_CLEARANCE_M = 0.2;
/** The pulse redraws the stage this often: enough to read as movement, a fraction of a display's refresh. */
const PULSE_FPS = 24;

function onFloor(point: SpacePoint): SpacePoint {
  return [point[0], Math.max(point[1], FLOOR_LIFT), point[2]];
}

/** What a drawn line lets this module reach: how many of its legs are drawn. */
interface PartialLine {
  visible: boolean;
  geometry: { instanceCount: number };
}

interface Props {
  trail: Trail;
  color: string;
  /** The playhead: the route up to here is drawn solid, the rest is still ahead. */
  time: number;
  /** Whoever travels it is picked: every key says when it is reached. */
  selected: boolean;
  /** A dot replays the route at the shot's own pace. */
  pulse: boolean;
}

/**
 * The route of a lens or a figure through the shot, drawn so it reads as movement: solid behind the
 * playhead and dashed ahead of it, arrowheads the way it runs, a marker on each key (a ghost of the
 * camera, for a lens), and a dot that replays the route at the shot's own pace while nothing plays.
 */
export function MotionTrail({ trail, color, time, selected, pulse }: Props) {
  // The route holds still while the shot plays through it; only a new route rebuilds the lines.
  const line = useMemo(() => trail.points.map(onFloor), [trail.points]);
  const arrows = useMemo(() => trailArrows(line).map(arrow => ({
    position: arrow.position,
    turn: new Quaternion().setFromUnitVectors(UP, new Vector3(...arrow.direction)),
  })), [line]);
  const spot = trailSpot(trail, time);
  const travelled = useRef<PartialLine | null>(null);
  // Layout, so the first frame drawn after a seek already shows the right length. `line` is listed
  // because a new route is a new geometry, which starts out drawn in full.
  useLayoutEffect(() => {
    const drawn = travelled.current;
    if (!drawn) return;
    drawn.visible = spot.legs > 0;
    drawn.geometry.instanceCount = spot.legs;
  }, [line, spot.legs]);
  const aimed = useMemo(() => (trail.kind === 'camera' ? ghostKeys(trail.keys) : []), [trail.keys, trail.kind]);
  const ghosts = aimed.filter(key => Math.hypot(key.position[0] - spot.position[0], key.position[1] - spot.position[1], key.position[2] - spot.position[2]) > GHOST_CLEARANCE_M);
  if (line.length < 2) return null;
  return (
    <group userData={{ [HELPER_FLAG]: true }}>
      <Line points={line} color={color} lineWidth={1.4} dashed dashSize={0.16} gapSize={0.1} transparent opacity={0.6} />
      <Line ref={travelled as never} points={line} color={color} lineWidth={selected ? 3.2 : 2.4} />
      {arrows.map((arrow, index) => (
        <mesh key={index} position={arrow.position} quaternion={arrow.turn}>
          <coneGeometry args={[0.07, 0.2, 10]} />
          <meshBasicMaterial color={color} />
        </mesh>
      ))}
      {trail.keys.map((key, index) => (
        <group key={index} position={onFloor(key.position)}>
          <mesh>
            <octahedronGeometry args={[trail.kind === 'camera' ? 0.07 : 0.06]} />
            <meshBasicMaterial color={color} />
          </mesh>
          {selected && <StageLabel position={[0, 0.12, 0]} fontSize={0.11} color={color} kind="prop">{keyStamp(key.time)}</StageLabel>}
        </group>
      ))}
      {ghosts.map((key, index) => (
        <ScreenSized key={index} position={key.position} size={CAMERA_BODY_SIZE_M} minPixels={12}>
          <CameraBody position={key.position} target={key.target!} color={color} ghost />
        </ScreenSized>
      ))}
      {pulse && <TrailPulse trail={trail} color={color} />}
    </group>
  );
}

/**
 * The dot that runs the route. It moves between frames without asking React for anything, and reads
 * the page's own clock, so every route of a shot pulses in step: who sets off first shows.
 */
function TrailPulse({ trail, color }: { trail: Trail; color: string }) {
  const dot = useRef<Group>(null);
  useFrame(() => {
    const node = dot.current;
    if (!node) return;
    const at = pulseTime(performance.now() / 1000, trail.durationS);
    node.visible = at !== null;
    if (at === null) return;
    const [x, y, z] = onFloor(trailSpot(trail, at).position);
    node.position.set(x, y, z);
  });
  return (
    <group ref={dot} visible={false}>
      <mesh>
        <sphereGeometry args={[0.075, 14, 10]} />
        <meshBasicMaterial color="#ffffff" />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.14, 14, 10]} />
        <meshBasicMaterial color={color} transparent opacity={0.28} depthWrite={false} />
      </mesh>
    </group>
  );
}

/**
 * Keeps a stage that only draws on demand drawing while a pulse runs, and stops asking as soon as
 * nobody can see it (a hidden tab) or `active` goes false.
 */
export function PulseDriver({ active }: { active: boolean }) {
  const invalidate = useThree(state => state.invalidate);
  useEffect(() => {
    if (!active) return undefined;
    const timer = window.setInterval(() => { if (!document.hidden) invalidate(); }, 1000 / PULSE_FPS);
    return () => window.clearInterval(timer);
  }, [active, invalidate]);
  return null;
}
