// The skeleton of the jointed figure as data: proportions per body type, the bone tree, how each
// control key turns a bone, and forward kinematics. The R3F component draws exactly this tree and
// the IK and ground-contact maths read it, so what is solved is what is shown.
//
// The proportions idea (a table per body type feeding nested joint groups) follows
//   lkhxxx123/jlmlh-3d-director (MIT, © 2026 YZ) src/editor/runtime/mannequin/{bodyTypes.ts,ProceduralMannequin.tsx}
// What changed: the figure is one unit tall (scaled by the actor's height instead of a free
// model scale), the character's left is +X with the face on +Z, joints carry explicit axes and
// signs, hands, feet and fingers are articulated, and the figure is grounded from its contacts.

import { Euler, Matrix4, Quaternion, Vector3, type EulerOrder } from 'three';

import { FINGERS, normalizeBodyType, type BodyType, type Finger, type Joints, type Side } from './poses';

export interface Proportions {
  hipY: number;
  hipX: number;
  thigh: number;
  calf: number;
  ankle: number;
  footBack: number;
  footFront: number;
  waist: number;
  neckY: number;
  headLift: number;
  headRadius: number;
  shoulderY: number;
  shoulderX: number;
  upperArm: number;
  forearm: number;
  palm: number;
  finger: number;
  /** Multiplies every radius: what makes a figure slim or heavy. */
  girth: number;
}

const STANDARD: Proportions = {
  hipY: 0.53, hipX: 0.055, thigh: 0.245, calf: 0.24, ankle: 0.045, footBack: 0.035, footFront: 0.105,
  waist: 0.06, neckY: 0.845, headLift: 0.08, headRadius: 0.075, shoulderY: 0.8, shoulderX: 0.115,
  upperArm: 0.165, forearm: 0.15, palm: 0.05, finger: 0.045, girth: 1,
};

export const PROPORTIONS: Record<BodyType, Proportions> = {
  standard: STANDARD,
  slim: { ...STANDARD, shoulderX: 0.1, hipX: 0.05, girth: 0.84 },
  heavy: { ...STANDARD, shoulderX: 0.135, hipX: 0.065, girth: 1.28 },
  // A child is not a small adult: a bigger head on shorter legs, still one unit tall.
  child: {
    ...STANDARD, hipY: 0.47, thigh: 0.215, calf: 0.21, neckY: 0.81, headLift: 0.095, headRadius: 0.095,
    shoulderY: 0.765, shoulderX: 0.1, upperArm: 0.145, forearm: 0.13, palm: 0.045, finger: 0.04, girth: 0.95,
  },
};

export function proportionsOf(bodyType: string | undefined | null): Proportions {
  return PROPORTIONS[normalizeBodyType(bodyType)];
}

export type Triple = [number, number, number];

export interface BoneLocal {
  id: string;
  parent: string | null;
  offset: Triple;
  /** Radians. */
  rotation: Triple;
  order: EulerOrder;
}

const RAD = Math.PI / 180;
// Limbs twist about their own length first, then swing: R = Rz · Rx · Ry.
export const LIMB_ORDER: EulerOrder = 'ZXY';
const TRUNK_ORDER: EulerOrder = 'YXZ';
const SIDES: Side[] = ['left', 'right'];
const FINGER_Z: Record<Finger, number> = { thumb: 0.5, index: 0.36, middle: 0.12, ring: -0.12, pinky: -0.36 };

export function sideSign(side: Side): 1 | -1 {
  return side === 'left' ? 1 : -1;
}

/** Shoulder / hip: pitch swings forward, spread is signed by side (see poses.ts), twist is about the limb. */
export function limbRotation(joints: Joints, prefix: string): Triple {
  return [-(joints[`${prefix}.pitch`] ?? 0) * RAD, -(joints[`${prefix}.twist`] ?? 0) * RAD, -(joints[`${prefix}.spread`] ?? 0) * RAD];
}

/** The inverse of `limbRotation`, in degrees. */
export function limbControls(prefix: string, rotation: Triple): Joints {
  return { [`${prefix}.pitch`]: -rotation[0] / RAD, [`${prefix}.twist`]: -rotation[1] / RAD, [`${prefix}.spread`]: -rotation[2] / RAD };
}

/** Every bone of the figure with its local offset and rotation for `joints`, parents before children. */
export function boneLocals(joints: Joints, bodyType?: string | null): BoneLocal[] {
  const p = proportionsOf(bodyType);
  const at = (key: string) => (joints[key] ?? 0) * RAD;
  const bones: BoneLocal[] = [
    // Body and torso lean forward on a negative pitch (upstream's sign); the head nods down on a positive one.
    { id: 'body', parent: null, offset: [0, p.hipY, 0], rotation: [-at('body.pitch'), at('body.yaw'), at('body.roll')], order: TRUNK_ORDER },
    { id: 'torso', parent: 'body', offset: [0, p.waist, 0], rotation: [-at('torso.pitch'), at('torso.yaw'), at('torso.roll')], order: TRUNK_ORDER },
    { id: 'head', parent: 'torso', offset: [0, p.neckY - p.hipY - p.waist, 0], rotation: [at('head.pitch'), at('head.yaw'), at('head.roll')], order: TRUNK_ORDER },
  ];
  SIDES.forEach(side => {
    const s = sideSign(side);
    bones.push(
      { id: `${side}Shoulder`, parent: 'torso', offset: [s * p.shoulderX, p.shoulderY - p.hipY - p.waist, 0], rotation: limbRotation(joints, `${side}Shoulder`), order: LIMB_ORDER },
      { id: `${side}Elbow`, parent: `${side}Shoulder`, offset: [0, -p.upperArm, 0], rotation: [-at(`${side}Elbow.bend`), 0, 0], order: LIMB_ORDER },
      { id: `${side}Hand`, parent: `${side}Elbow`, offset: [0, -p.forearm, 0], rotation: [-at(`${side}Hand.pitch`), -at(`${side}Hand.twist`), -at(`${side}Hand.roll`)], order: LIMB_ORDER },
    );
    FINGERS.forEach(finger => {
      const curl = at(`${side}Hand.${finger}.curl`);
      const spread = at(`${side}Hand.${finger}.spread`);
      const thumb = finger === 'thumb';
      // The palm faces the thigh, so fingers curl about Z towards the body and fan about X.
      const fan = -Math.sign(FINGER_Z[finger]) * spread - (thumb ? 50 * RAD : 0);
      bones.push(
        { id: `${side}Hand.${finger}`, parent: `${side}Hand`, offset: [0, thumb ? -p.palm * 0.35 : -p.palm, FINGER_Z[finger] * p.palm], rotation: [fan, 0, -s * curl * 0.9], order: 'XZY' },
        { id: `${side}Hand.${finger}.tip`, parent: `${side}Hand.${finger}`, offset: [0, -p.finger * 0.55, 0], rotation: [0, 0, -s * curl], order: 'XZY' },
      );
    });
    bones.push(
      { id: `${side}Hip`, parent: 'body', offset: [s * p.hipX, 0, 0], rotation: limbRotation(joints, `${side}Hip`), order: LIMB_ORDER },
      { id: `${side}Knee`, parent: `${side}Hip`, offset: [0, -p.thigh, 0], rotation: [at(`${side}Knee.bend`), 0, 0], order: LIMB_ORDER },
      // A positive foot pitch points the toes down.
      { id: `${side}Foot`, parent: `${side}Knee`, offset: [0, -p.calf, 0], rotation: [at(`${side}Foot.pitch`), -at(`${side}Foot.twist`), -at(`${side}Foot.roll`)], order: LIMB_ORDER },
    );
  });
  return bones;
}

export interface BoneWorld {
  position: Vector3;
  quaternion: Quaternion;
}

/** Forward kinematics in figure space: one unit tall, feet towards −Y, not yet grounded. */
export function solveBones(joints: Joints, bodyType?: string | null): Record<string, BoneWorld> {
  const world: Record<string, BoneWorld> = {};
  const euler = new Euler();
  boneLocals(joints, bodyType).forEach(bone => {
    const parent = bone.parent ? world[bone.parent] : null;
    const local = new Quaternion().setFromEuler(euler.set(bone.rotation[0], bone.rotation[1], bone.rotation[2], bone.order));
    const offset = new Vector3(...bone.offset);
    world[bone.id] = parent
      ? { position: offset.applyQuaternion(parent.quaternion).add(parent.position), quaternion: parent.quaternion.clone().multiply(local) }
      : { position: offset, quaternion: local };
  });
  return world;
}

export interface Contact {
  id: string;
  point: Vector3;
  radius: number;
}

function offsetFrom(bone: BoneWorld, x: number, y: number, z: number): Vector3 {
  return new Vector3(x, y, z).applyQuaternion(bone.quaternion).add(bone.position);
}

/** Everything that may touch the floor, as spheres: soles first, then the parts a kneel, a sit or a fall rests on. */
export function contactsOf(bones: Record<string, BoneWorld>, bodyType?: string | null): Contact[] {
  const p = proportionsOf(bodyType);
  const g = p.girth;
  const contacts: Contact[] = [
    { id: 'pelvis', point: bones.body.position.clone(), radius: 0.075 * g },
    { id: 'chest', point: offsetFrom(bones.torso, 0, 0.14, 0), radius: 0.085 * g },
    { id: 'head', point: offsetFrom(bones.head, 0, p.headLift, 0), radius: p.headRadius },
  ];
  SIDES.forEach(side => {
    const foot = bones[`${side}Foot`];
    contacts.push(
      { id: `${side}Heel`, point: offsetFrom(foot, 0, -p.ankle, -p.footBack), radius: 0 },
      { id: `${side}Toe`, point: offsetFrom(foot, 0, -p.ankle, p.footFront), radius: 0 },
      { id: `${side}Knee`, point: bones[`${side}Knee`].position.clone(), radius: 0.034 * g },
      { id: `${side}Elbow`, point: bones[`${side}Elbow`].position.clone(), radius: 0.024 * g },
      { id: `${side}Palm`, point: offsetFrom(bones[`${side}Hand`], 0, -p.palm * 0.6, 0), radius: 0.022 * g },
    );
  });
  return contacts;
}

/** How far the figure has to rise (figure units) for its lowest contact to rest on y = 0. */
export function groundLift(joints: Joints, bodyType?: string | null): number {
  const lowest = Math.min(...contactsOf(solveBones(joints, bodyType), bodyType).map(contact => contact.point.y - contact.radius));
  return -lowest;
}

/** Top of the posed figure above the floor, in figure units (1 when standing). */
export function figureTop(joints: Joints, bodyType?: string | null): number {
  const bones = solveBones(joints, bodyType);
  const contacts = contactsOf(bones, bodyType);
  const lowest = Math.min(...contacts.map(contact => contact.point.y - contact.radius));
  return Math.max(...contacts.map(contact => contact.point.y + contact.radius)) - lowest;
}

export type EffectorId = 'leftWrist' | 'rightWrist' | 'leftAnkle' | 'rightAnkle';
export const EFFECTORS: Array<{ id: EffectorId; label: string; side: Side; limb: 'arm' | 'leg' }> = [
  { id: 'leftWrist', label: '左腕', side: 'left', limb: 'arm' }, { id: 'rightWrist', label: '右腕', side: 'right', limb: 'arm' },
  { id: 'leftAnkle', label: '左踝', side: 'left', limb: 'leg' }, { id: 'rightAnkle', label: '右踝', side: 'right', limb: 'leg' },
];

export interface EffectorBones {
  upper: string;
  lower: string;
  end: string;
  bendKey: string;
  /** Which way a positive bend turns the hinge about its local X. */
  hingeSign: 1 | -1;
}

export function effectorBones(id: EffectorId): EffectorBones {
  const spec = EFFECTORS.find(item => item.id === id) ?? EFFECTORS[0];
  return spec.limb === 'arm'
    ? { upper: `${spec.side}Shoulder`, lower: `${spec.side}Elbow`, end: `${spec.side}Hand`, bendKey: `${spec.side}Elbow.bend`, hingeSign: -1 }
    : { upper: `${spec.side}Hip`, lower: `${spec.side}Knee`, end: `${spec.side}Foot`, bendKey: `${spec.side}Knee.bend`, hingeSign: 1 };
}

/** Figure space → the stage: grounded, scaled to the actor's height, turned and placed. */
export function figureMatrix(actor: { position: [number, number]; yaw_deg: number; height_m: number }, lift: number, offsetY = 0): Matrix4 {
  return new Matrix4().compose(
    new Vector3(actor.position[0], lift * actor.height_m + offsetY, actor.position[1]),
    new Quaternion().setFromEuler(new Euler(0, actor.yaw_deg * RAD, 0)),
    new Vector3(actor.height_m, actor.height_m, actor.height_m),
  );
}
