import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useThree, type ThreeEvent } from '@react-three/fiber';
import { Euler, Matrix4, Plane, Quaternion, Raycaster, Vector2, Vector3 } from 'three';

import type { StageActor, StageOperation } from '../../spatial/spatialTypes';
import { poseOperation } from '../deskOperations';
import { HELPER_FLAG } from '../lib/capture';
import { chainOf, effectorOf, ikControls, solveTwoBone, type TwoBoneChain } from '../lib/ik';
import { EFFECTORS, effectorBones, groundLift, solveBones, type EffectorId } from '../lib/mannequinRig';
import { jointsOf, type Joints } from '../lib/poses';
import type { PointerHandlers } from './CameraRig';
import { hitOnTop } from './hitOnTop';
import { ScreenSized } from './ScreenSized';
import { SELECTION_COLOR } from './stageLook';

interface Props {
  /** The actor as drawn (with the drag in progress). */
  actor: StageActor;
  /** The actor as it was before the drag: what every solve starts from. */
  baseActor: StageActor;
  /** Set when the edit belongs to one shot only. */
  shotId?: number;
  footLock: boolean;
  /** What the pointer shows over a handle. A handle held out over bare floor has nothing behind it to say it can be grabbed. */
  pointer?: Pick<PointerHandlers, 'onPointerOver' | 'onPointerOut'>;
  onDragState: (dragging: boolean) => void;
  onPreview: (operations: StageOperation[] | null) => void;
  onCommit: (operations: StageOperation[]) => void;
}

interface Grab {
  effector: EffectorId;
  joints: Joints;
  chain: TwoBoneChain;
  lockY?: number;
  /** Stage → the actor's own metres, feet not yet grounded: the space the chain lives in. */
  toLocal: Matrix4;
  plane: Plane;
  operation: StageOperation | null;
}

const HANDLE_RADIUS_M = 0.055;
const HANDLE_PIXELS = 16;

function actorFrame(actor: StageActor, joints: Joints): Matrix4 {
  const lift = groundLift(joints, actor.body_type) * actor.height_m + (joints['body.offsetY'] ?? 0);
  return new Matrix4().compose(
    new Vector3(actor.position[0], lift, actor.position[1]),
    new Quaternion().setFromEuler(new Euler(0, (actor.yaw_deg * Math.PI) / 180, 0)),
    new Vector3(1, 1, 1),
  );
}

/** Wrist and ankle handles of the selected jointed figure: drag one and the limb follows by IK. */
export function PoseHandles({ actor, baseActor, shotId, footLock, pointer, onDragState, onPreview, onCommit }: Props) {
  const camera = useThree(state => state.camera);
  const canvas = useThree(state => state.gl.domElement);
  const grab = useRef<Grab | null>(null);
  const stop = useRef<(() => void) | null>(null);

  const handles = useMemo(() => {
    const joints = jointsOf(actor);
    const bones = solveBones(joints, actor.body_type);
    const frame = actorFrame(actor, joints);
    return EFFECTORS.map(item => ({
      ...item, point: bones[effectorBones(item.id).end].position.clone().multiplyScalar(actor.height_m).applyMatrix4(frame),
    }));
  }, [actor]);

  useEffect(() => () => stop.current?.(), []);

  const begin = useCallback((effector: EffectorId, limb: 'arm' | 'leg') => (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    if (grab.current) return;
    const joints = jointsOf(baseActor);
    const chain = chainOf(joints, baseActor.body_type, baseActor.height_m, effector);
    const frame = actorFrame(baseActor, joints);
    const start = effectorOf(chain);
    // The handle slides in the plane that faces the viewer through the point it was grabbed at.
    const plane = new Plane().setFromNormalAndCoplanarPoint(camera.getWorldDirection(new Vector3()).negate(), start.clone().applyMatrix4(frame));
    grab.current = { effector, joints, chain, lockY: footLock && limb === 'leg' ? start.y : undefined, toLocal: frame.clone().invert(), plane, operation: null };
    onDragState(true);

    const raycaster = new Raycaster();
    const move = (pointer: PointerEvent) => {
      const held = grab.current;
      if (!held) return;
      const rect = canvas.getBoundingClientRect();
      raycaster.setFromCamera(new Vector2(((pointer.clientX - rect.left) / rect.width) * 2 - 1, -((pointer.clientY - rect.top) / rect.height) * 2 + 1), camera);
      const hit = raycaster.ray.intersectPlane(held.plane, new Vector3());
      if (!hit) return;
      const solved = solveTwoBone(held.chain, hit.applyMatrix4(held.toLocal), { lockY: held.lockY });
      const pose = { ...(baseActor.pose || {}), joints: { ...held.joints, ...ikControls(held.effector, solved, baseActor.body_type) } };
      held.operation = poseOperation(baseActor.name, shotId, pose);
      onPreview([held.operation]);
    };
    const end = () => {
      const held = grab.current;
      grab.current = null;
      stop.current?.();
      onDragState(false);
      // One set_pose per gesture, on release.
      if (held?.operation) onCommit([held.operation]);
      else onPreview(null);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end);
    window.addEventListener('pointercancel', end);
    stop.current = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
      window.removeEventListener('pointercancel', end);
      stop.current = null;
    };
  }, [baseActor, camera, canvas, footLock, onCommit, onDragState, onPreview, shotId]);

  return (
    <group userData={{ [HELPER_FLAG]: true }}>
      {handles.map(handle => (
        // An 11 cm ball is a few pixels once the view backs off to take in the set: it never draws smaller than a fingertip.
        <ScreenSized key={handle.id} position={handle.point} size={HANDLE_RADIUS_M * 2} minPixels={HANDLE_PIXELS}>
          <mesh name={`pose-handle-${handle.id}`} renderOrder={10} raycast={hitOnTop} onPointerDown={begin(handle.id, handle.limb)} onClick={event => event.stopPropagation()} {...pointer}>
            <sphereGeometry args={[HANDLE_RADIUS_M, 16, 12]} />
            <meshBasicMaterial color={SELECTION_COLOR} transparent opacity={0.85} depthTest={false} />
          </mesh>
        </ScreenSized>
      ))}
    </group>
  );
}
