// The real hand of a jointed figure, for contacts.ts: where the posed mannequin's palm actually is
// on the stage, read off the same rig the figure is drawn from (lib/mannequinRig.ts). Kept out of
// contacts.ts because it needs three.js; the desk loads it alongside its 3D views.

import { Vector3 } from 'three';

import type { SpacePoint, StageActor } from '../../spatial/spatialTypes';
import type { Hand, HandLocator } from './contacts';
import { contactsOf, figureMatrix, solveBones } from './mannequinRig';
import { jointsOf } from './poses';

const scratch = new Vector3();

function palmOf(points: ReturnType<typeof contactsOf>, side: 'left' | 'right') {
  return points.find(point => point.id === `${side}Palm`)?.point;
}

/**
 * The palm of a posed mannequin: the middle of the two palms for both hands. Any other figure, or
 * a mannequin nobody has posed, gets `null` and the contract's formula instead.
 */
export const mannequinHandPoint = ((actor: StageActor, hand: Hand): SpacePoint | null => {
  if (actor.figure !== 'mannequin' || !actor.pose) return null;
  const joints = jointsOf(actor);
  const points = contactsOf(solveBones(joints, actor.body_type), actor.body_type);
  // Grounded the way the figure is drawn: its lowest contact on the floor.
  const lift = -Math.min(...points.map(point => point.point.y - point.radius));
  const left = palmOf(points, 'left');
  const right = palmOf(points, 'right');
  if (!left || !right) return null;
  if (hand === 'both') scratch.copy(left).add(right).multiplyScalar(0.5);
  else scratch.copy(hand === 'left' ? left : right);
  scratch.applyMatrix4(figureMatrix(actor, lift, joints['body.offsetY'] ?? 0));
  return [scratch.x, scratch.y, scratch.z];
}) satisfies HandLocator;
