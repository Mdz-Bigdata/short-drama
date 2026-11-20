import { useMemo } from 'react';
import { Matrix4, Quaternion, Vector3 } from 'three';

import type { StageLandmark } from '../../../spatial/spatialTypes';

const UP = new Vector3(0, 1, 0);
/** A facing this close to the way the piece's height runs says nothing about its roll. */
const PARALLEL = 1e-3;

/** The turn of a piece leaning along `up` with its depth facing `forward` as nearly as that allows. */
export function tiltQuaternion(up: readonly number[], forward: readonly number[]): Quaternion {
  const y = new Vector3(up[0], up[1], up[2]);
  if (y.lengthSq() < 1e-12) return new Quaternion();
  y.normalize();
  const z = new Vector3(forward[0], forward[1], forward[2]);
  z.addScaledVector(y, -z.dot(y));
  // No usable facing: any direction square to the lean will do, as long as it is the same one every frame.
  if (z.lengthSq() < PARALLEL) z.set(1, 0, 0).addScaledVector(y, -y.x);
  if (z.lengthSq() < PARALLEL) z.set(0, 0, 1).addScaledVector(y, -y.z);
  z.normalize();
  const x = new Vector3().crossVectors(y, z);
  return new Quaternion().setFromRotationMatrix(new Matrix4().makeBasis(x, y, z));
}

/**
 * How a set piece is turned where it stands: about the vertical by its `yaw_deg`, or, for a long
 * thing leaning in a hand (`tilt`, see contacts.ts), the way the hand holds it.
 */
export function usePropTurn(landmark: Pick<StageLandmark, 'yaw_deg' | 'tilt'>): Quaternion {
  const yaw = landmark.yaw_deg ?? 0;
  const [ux, uy, uz] = landmark.tilt?.up ?? [0, 0, 0];
  const [fx, fy, fz] = landmark.tilt?.forward ?? [0, 0, 0];
  const tilted = Boolean(landmark.tilt);
  return useMemo(() => (
    tilted ? tiltQuaternion([ux, uy, uz], [fx, fy, fz]) : new Quaternion().setFromAxisAngle(UP, (yaw * Math.PI) / 180)
  ), [fx, fy, fz, tilted, ux, uy, uz, yaw]);
}
