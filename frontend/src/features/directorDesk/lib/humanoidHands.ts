// The real hand of the skinned figure, for contacts.ts: where its palm is on the stage at one
// instant of the motion it is showing. Read off a private copy of the same model the figure is
// drawn from, posed the same way (three/figures/Humanoid.tsx), so a sword in the hand goes where
// the hand goes through a swing. Kept out of contacts.ts because it needs three.js and the model.

import { AnimationMixer, LoopOnce, LoopRepeat, Vector3, type AnimationAction, type AnimationClip, type Object3D } from 'three';
import { SkeletonUtils } from 'three-stdlib';

import type { SpacePoint, StageActor } from '../../spatial/spatialTypes';
import type { Hand, HandGrip, HandLocator } from './contacts';
import { clipForPosture, humanoidClip } from './humanoidClips';

/** What the locator needs of the loaded model (three/figures/humanoidSource.ts hands this over). */
export interface HandSource {
  scene: Object3D;
  clips: AnimationClip[];
  /** The figure's own height and the height of its soles, in model units. */
  height: number;
  floor: number;
}

/**
 * Per side: the wrist, then the roots of the middle, index and little fingers. The grip sits between
 * the wrist and the middle knuckle; what a fist holds runs along the knuckles, in at the little
 * finger and out past the index finger and thumb, the way a sword or a torch is held.
 */
const HAND_BONES = { left: ['leftHand', 'joint007', 'joint004', 'joint010'], right: ['rightHand', 'joint026', 'joint023', 'joint029'] } as const;
/** How far from the wrist towards the knuckle a closed hand holds something. */
const GRIP_ALONG_PALM = 0.6;

function round4(value: number): number {
  return Math.round(value * 10000) / 10000 + 0;
}

/**
 * A locator for figures drawn from `source`. It answers for skinned figures only (`null` for any
 * other, so the next locator or the contract's formula takes over), and `null` too when the model
 * has no bone it knows.
 */
export function humanoidHandLocator(source: HandSource): HandLocator {
  const scene = SkeletonUtils.clone(source.scene);
  const mixer = new AnimationMixer(scene);
  const bones = {
    left: HAND_BONES.left.map(name => scene.getObjectByName(name)),
    right: HAND_BONES.right.map(name => scene.getObjectByName(name)),
  };
  const usable = [...bones.left, ...bones.right].every(Boolean);
  const wrist = new Vector3();
  const knuckle = new Vector3();
  const index = new Vector3();
  const little = new Vector3();
  const other = new Vector3();
  let action: AnimationAction | null = null;
  let posed = '';

  /** The model-space grip of one side, with the copy standing in the frame last asked for. */
  const grip = (side: 'left' | 'right', into: Vector3) => {
    const [from, to] = bones[side] as unknown as Object3D[];
    from.getWorldPosition(wrist);
    to.getWorldPosition(knuckle);
    return into.copy(wrist).lerp(knuckle, GRIP_ALONG_PALM);
  };

  return (actor: StageActor, hand: Hand): HandGrip | null => {
    if (actor.figure !== 'humanoid' || !usable) return null;
    // The same frame the figure itself shows: its clip, or what its posture implies, at its phase.
    const spec = humanoidClip(actor.pose?.clip || clipForPosture(actor.posture));
    const clip = source.clips[spec.index];
    if (!clip) return null;
    const phase = Math.min(Math.max(actor.pose?.clip_phase ?? 0, 0), 0.9999);
    const frame = `${spec.id}@${phase}`;
    if (frame !== posed) {
      if (action?.getClip() !== clip) {
        mixer.stopAllAction();
        action = mixer.clipAction(clip);
        action.setLoop(spec.loop ? LoopRepeat : LoopOnce, spec.loop ? Infinity : 1);
        action.clampWhenFinished = true;
        action.play();
      }
      mixer.setTime(phase * clip.duration);
      scene.updateMatrixWorld(true);
      posed = frame;
    }
    const point = hand === 'both' ? grip('left', new Vector3()).add(grip('right', other)).multiplyScalar(0.5) : grip(hand, new Vector3());
    // Onto the stage the way the figure is drawn: scaled to the actor's height, soles on the floor, turned, then moved to the mark.
    const scale = actor.height_m / source.height;
    const x = point.x * scale;
    const y = (point.y - source.floor) * scale;
    const z = point.z * scale;
    const yaw = (actor.yaw_deg * Math.PI) / 180;
    const cos = Math.cos(yaw);
    const sin = Math.sin(yaw);
    // Which way the fist points what it holds, and which way its knuckles face. Two hands on one thing: the right hand leads.
    const [from, middle, first, last] = bones[hand === 'left' ? 'left' : 'right'] as unknown as Object3D[];
    const turned = (vector: Vector3): SpacePoint => {
      vector.normalize();
      return [round4(vector.x * cos + vector.z * sin), round4(vector.y), round4(-vector.x * sin + vector.z * cos)];
    };
    const along = turned(first.getWorldPosition(index).sub(last.getWorldPosition(little)));
    const forward = turned(middle.getWorldPosition(knuckle).sub(from.getWorldPosition(wrist)));
    return { point: [actor.position[0] + x * cos + z * sin, Math.max(0, y), actor.position[1] - x * sin + z * cos], along, forward };
  };
}
