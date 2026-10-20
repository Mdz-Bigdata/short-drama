// Two-bone inverse kinematics for the jointed figure: a wrist or an ankle is dragged, the
// shoulder / hip (a clamped ball joint) and the elbow / knee (a clamped hinge) follow.
// Written for this desk from a description of the behaviour (cyclic coordinate descent with a
// foot lock); no code was taken from any other project. Pure maths on three's vector types.

import { Euler, Quaternion, Vector3 } from 'three';

import { clampControl, controlRange, type Joints } from './poses';
import { LIMB_ORDER, effectorBones, limbControls, limbRotation, solveBones, type EffectorId, type Triple } from './mannequinRig';

export const IK_MAX_ITERATIONS = 10;
export const IK_TOLERANCE_M = 0.005;
const RAD = Math.PI / 180;
const X_AXIS = new Vector3(1, 0, 0);

export type Range = [number, number];

/** A limb at the moment it was grabbed. Bones run along −Y of their own frame. */
export interface TwoBoneChain {
  /** Upper joint (shoulder / hip) in the solver's space. */
  origin: Vector3;
  /** Rotation of the upper joint's parent in that space. */
  frame: Quaternion;
  /** Local rotation of the upper bone, radians, Euler order ZXY. */
  upper: Triple;
  /** Hinge angle, radians, never negative. */
  bend: number;
  hingeSign: 1 | -1;
  upperLength: number;
  lowerLength: number;
  limits: { upper: [Range, Range, Range]; bend: Range };
}

export interface IkOptions {
  /** Pin the target's height here (the effector's height when it was grabbed). */
  lockY?: number;
  maxIterations?: number;
  tolerance?: number;
}

export interface IkResult {
  upper: Triple;
  bend: number;
  effector: Vector3;
  /** Distance left between the effector and the (possibly locked) target. */
  error: number;
  iterations: number;
  reached: boolean;
}

const clamp = (value: number, [min, max]: Range) => Math.min(max, Math.max(min, value));

function upperQuaternion(chain: TwoBoneChain, upper: Triple): Quaternion {
  return chain.frame.clone().multiply(new Quaternion().setFromEuler(new Euler(upper[0], upper[1], upper[2], LIMB_ORDER)));
}

function place(chain: TwoBoneChain, upper: Triple, bend: number) {
  const upperWorld = upperQuaternion(chain, upper);
  const joint = new Vector3(0, -chain.upperLength, 0).applyQuaternion(upperWorld).add(chain.origin);
  const lowerWorld = upperWorld.clone().multiply(new Quaternion().setFromAxisAngle(X_AXIS, chain.hingeSign * bend));
  const effector = new Vector3(0, -chain.lowerLength, 0).applyQuaternion(lowerWorld).add(joint);
  return { upperWorld, joint, effector };
}

export function effectorOf(chain: TwoBoneChain): Vector3 {
  return place(chain, chain.upper, chain.bend).effector;
}

/**
 * Always solved from `chain` — the grab snapshot — never from a previous answer, so the same
 * target gives the same limb however the pointer wandered on its way there.
 */
export function solveTwoBone(chain: TwoBoneChain, target: Vector3, options: IkOptions = {}): IkResult {
  const tolerance = options.tolerance ?? IK_TOLERANCE_M;
  const maxIterations = Math.min(IK_MAX_ITERATIONS, options.maxIterations ?? IK_MAX_ITERATIONS);
  const goal = target.clone();
  if (options.lockY !== undefined) goal.y = options.lockY;

  let upper: Triple = [...chain.upper];
  let bend = chain.bend;
  let state = place(chain, upper, bend);
  let iterations = 0;

  if (state.effector.distanceTo(goal) > tolerance) {
    // Plain CCD crawls out of a straight limb, so the hinge is opened first to the angle whose
    // chord is the distance to the goal (law of cosines); the descent below then only has to aim.
    const { upperLength: a, lowerLength: b } = chain;
    const span = Math.min(a + b, Math.max(Math.abs(a - b), goal.distanceTo(chain.origin)));
    const interior = Math.acos(Math.min(1, Math.max(-1, (a * a + b * b - span * span) / (2 * a * b))));
    bend = clamp(Math.PI - interior, chain.limits.bend);
    state = place(chain, upper, bend);
  }

  while (state.effector.distanceTo(goal) > tolerance && iterations < maxIterations) {
    iterations += 1;
    // The ball joint swings the whole limb at the goal, inside its ranges.
    const reach = state.effector.clone().sub(chain.origin);
    const wanted = goal.clone().sub(chain.origin);
    if (reach.lengthSq() > 1e-10 && wanted.lengthSq() > 1e-10) {
      const swing = new Quaternion().setFromUnitVectors(reach.normalize(), wanted.normalize());
      const local = chain.frame.clone().invert().multiply(swing.multiply(state.upperWorld));
      const euler = new Euler().setFromQuaternion(local, LIMB_ORDER);
      upper = [clamp(euler.x, chain.limits.upper[0]), clamp(euler.y, chain.limits.upper[1]), clamp(euler.z, chain.limits.upper[2])];
      state = place(chain, upper, bend);
    }
    if (state.effector.distanceTo(goal) <= tolerance) break;
    // Then the hinge turns, about its own axis only, until the effector is as near as it gets.
    const axis = X_AXIS.clone().applyQuaternion(state.upperWorld);
    const toEffector = state.effector.clone().sub(state.joint).projectOnPlane(axis);
    const toGoal = goal.clone().sub(state.joint).projectOnPlane(axis);
    if (toEffector.lengthSq() > 1e-10 && toGoal.lengthSq() > 1e-10) {
      const turn = Math.atan2(new Vector3().crossVectors(toEffector, toGoal).dot(axis), toEffector.dot(toGoal));
      bend = clamp(bend + chain.hingeSign * turn, chain.limits.bend);
      state = place(chain, upper, bend);
    }
  }

  const error = state.effector.distanceTo(goal);
  return { upper, bend, effector: state.effector, error, iterations, reached: error <= tolerance };
}

/** The limb behind an effector of a posed figure, in metres, in the actor's own frame (not grounded). */
export function chainOf(joints: Joints, bodyType: string | undefined | null, heightM: number, effector: EffectorId): TwoBoneChain {
  const bones = solveBones(joints, bodyType);
  const names = effectorBones(effector);
  const upper = bones[names.upper];
  const parentId = names.upper.endsWith('Shoulder') ? 'torso' : 'body';
  const radians = (key: string): Range => {
    const [min, max] = controlRange(key, bodyType) ?? [-180, 180];
    return [min * RAD, max * RAD];
  };
  // limbRotation negates every channel, so each control range arrives here flipped.
  const flipped = (key: string): Range => { const [min, max] = radians(key); return [-max, -min]; };
  return {
    origin: upper.position.clone().multiplyScalar(heightM),
    frame: bones[parentId].quaternion.clone(),
    upper: limbRotation(joints, names.upper),
    bend: Math.max(0, (joints[names.bendKey] ?? 0) * RAD),
    hingeSign: names.hingeSign,
    upperLength: bones[names.lower].position.distanceTo(upper.position) * heightM,
    lowerLength: bones[names.end].position.distanceTo(bones[names.lower].position) * heightM,
    limits: { upper: [flipped(`${names.upper}.pitch`), flipped(`${names.upper}.twist`), flipped(`${names.upper}.spread`)], bend: radians(names.bendKey) },
  };
}

/** A solved limb written back as control keys: tenths of a degree (a whole degree at the wrist is 5 mm), inside the body's ranges. */
export function ikControls(effector: EffectorId, result: Pick<IkResult, 'upper' | 'bend'>, bodyType?: string | null): Joints {
  const names = effectorBones(effector);
  const raw: Joints = { ...limbControls(names.upper, result.upper), [names.bendKey]: result.bend / RAD };
  const controls: Joints = {};
  Object.entries(raw).forEach(([key, value]) => { controls[key] = Math.round(clampControl(key, value, bodyType) * 10) / 10 || 0; });
  return controls;
}
