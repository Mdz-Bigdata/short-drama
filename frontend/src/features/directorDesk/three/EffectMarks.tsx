import { useCallback, useEffect, useMemo, useRef } from 'react';
import { Line } from '@react-three/drei';
import { useThree, type ThreeEvent } from '@react-three/fiber';
import { Plane, Raycaster, Vector2, Vector3 } from 'three';

import type { GroundPoint, StageEffect, StageOperation } from '../../spatial/spatialTypes';
import type { SnapSettings } from '../deskTypes';
import { HELPER_FLAG } from '../lib/capture';
import { EFFECT_COLOR, EFFECT_HANDLE_RADIUS, draggedCentre, effectMove, effectName, effectNumber, floorRing, ringCount } from '../lib/effects';
import type { PointerHandlers } from './CameraRig';
import { ScreenSized } from './ScreenSized';
import { StageLabel } from './StageLabel';

const FLOOR_LIFT = 0.03;
const HANDLE_PIXELS = 18;

/** What a marker needs to be dragged; without it the markers are only drawn (read-only desk, playback, another tool). */
export interface EffectDrag {
  snap: SnapSettings;
  /** What the pointer shows over the puck. */
  pointer?: Pick<PointerHandlers, 'onPointerOver' | 'onPointerOut'>;
  onDragState: (dragging: boolean) => void;
  onPreview: (operations: StageOperation[] | null) => void;
  onCommit: (operations: StageOperation[]) => void;
}

/** One ring of a marker. Its points are kept between renders: drei rebuilds a line whenever `points` is a new array. */
function Ring({ x, z, radius, outer }: { x: number; z: number; radius: number; outer: boolean }) {
  const points = useMemo(() => floorRing([x, z], radius, FLOOR_LIFT), [x, z, radius]);
  return <Line points={points} color={EFFECT_COLOR} lineWidth={outer ? 2 : 1.2} dashed={!outer} dashSize={0.18} gapSize={0.12} />;
}

/**
 * The puck at the centre of a marker: press it and slide it over the floor. The rings follow as a
 * preview; one `set_effect` goes out on release, none when the puck ends where it began. Escape puts
 * it back.
 */
function Puck({ effect, drag }: { effect: StageEffect; drag: EffectDrag }) {
  const camera = useThree(state => state.camera);
  const canvas = useThree(state => state.gl.domElement);
  const stop = useRef<(() => void) | null>(null);
  // The latest handlers and snap: a drag in progress must not be torn down when the desk re-renders.
  const live = useRef(drag);
  useEffect(() => { live.current = drag; }, [drag]);
  useEffect(() => () => stop.current?.(), []);

  const begin = useCallback((event: ThreeEvent<PointerEvent>) => {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || stop.current) return;
    event.stopPropagation();
    const start: GroundPoint = [effect.position[0], effect.position[1]];
    const grab: GroundPoint = [event.point.x, event.point.z];
    const raycaster = new Raycaster();
    const ground = new Plane(new Vector3(0, 1, 0), 0);
    let operation: StageOperation | null = null;
    live.current.onDragState(true);

    const move = (pointer: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      raycaster.setFromCamera(new Vector2(((pointer.clientX - rect.left) / rect.width) * 2 - 1, -((pointer.clientY - rect.top) / rect.height) * 2 + 1), camera);
      const hit = raycaster.ray.intersectPlane(ground, new Vector3());
      if (!hit) return;
      operation = effectMove({ id: effect.id, position: start }, draggedCentre(start, grab, [hit.x, hit.z], live.current.snap));
      live.current.onPreview(operation ? [operation] : null);
    };
    const finish = (commit: boolean) => {
      stop.current?.();
      live.current.onDragState(false);
      // One set_effect per gesture, on release.
      if (commit && operation) live.current.onCommit([operation]);
      else live.current.onPreview(null);
    };
    const up = () => finish(true);
    const cancel = () => finish(false);
    const key = (pressed: KeyboardEvent) => {
      if (pressed.key !== 'Escape') return;
      // Escape means "put the marker back", not "clear the selection": the desk's own handler must not see it.
      pressed.stopImmediatePropagation();
      pressed.preventDefault();
      finish(false);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', cancel);
    window.addEventListener('keydown', key, true);
    stop.current = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', cancel);
      window.removeEventListener('keydown', key, true);
      stop.current = null;
    };
  }, [camera, canvas, effect.id, effect.position]);

  return (
    // A 32 cm puck is a few pixels once the view backs off to take in the set: it never draws smaller than a fingertip.
    <ScreenSized position={[effect.position[0], FLOOR_LIFT + 0.01, effect.position[1]]} size={EFFECT_HANDLE_RADIUS * 2} minPixels={HANDLE_PIXELS}>
      <mesh name={`effect-handle-${effect.id}`} onPointerDown={begin} onClick={event => event.stopPropagation()} {...drag.pointer}>
        <cylinderGeometry args={[EFFECT_HANDLE_RADIUS, EFFECT_HANDLE_RADIUS, 0.02, 28]} />
        <meshBasicMaterial color={EFFECT_COLOR} transparent opacity={0.85} />
      </mesh>
    </ScreenSized>
  );
}

/** The effect markers of the shot on show: numbered rings on the floor. Helpers, so no capture films them. */
export function EffectMarks({ effects, drag }: { effects: StageEffect[]; drag?: EffectDrag }) {
  return (
    <>
      {effects.map((effect, index) => {
        const rings = ringCount(effect.kind, effect.radius_m);
        return (
          <group key={effect.id} userData={{ [HELPER_FLAG]: true }}>
            {Array.from({ length: rings }, (_item, ring) => (
              <Ring key={ring} x={effect.position[0]} z={effect.position[1]} radius={(effect.radius_m * (rings - ring)) / rings} outer={ring === 0} />
            ))}
            {drag && <Puck effect={effect} drag={drag} />}
            <StageLabel position={[effect.position[0], 0.2, effect.position[1]]} fontSize={0.15} color={EFFECT_COLOR} kind="distance">
              {`${effectNumber(index)} ${effectName(effect)}`}
            </StageLabel>
          </group>
        );
      })}
    </>
  );
}
