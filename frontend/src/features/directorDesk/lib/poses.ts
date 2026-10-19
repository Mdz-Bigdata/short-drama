// The pose vocabulary of the desk: control keys, their ranges, the preset table and the pure
// operations on a pose (clamp, mirror, blend). Nothing here touches three.js.
//
// Control keys and the 20 preset angle tables are ported from
//   jiguang132/storyai-3d-director-desk and lkhxxx123/jlmlh-3d-director (MIT, © 2026 YZ)
//   src/editor/presets/mannequinPosePresets.ts, src/editor/presets/skeletonMappings.ts,
//   src/editor/runtime/mannequin/{mannequinPose,bodyTypes}.ts
// What changed: `body.offsetY` is dropped from the presets (this desk grounds the figure from its
// own geometry, see mannequinRig.groundLift) and is kept only as a manual lift; the single ±90°
// limit became per-control ranges with a per-body-type factor; a few arm angles were re-tuned for
// this rig's joint axes; hand / foot controls are actually driven; finger controls, finger
// presets, mirror and blend are new. Their eight body types fold onto this desk's four.

import type { StageActor, StagePose } from '../../spatial/spatialTypes';

export type Side = 'left' | 'right';
export type BodyType = 'standard' | 'slim' | 'heavy' | 'child';
export type PoseGroupId = 'head' | 'torso' | 'leftArm' | 'rightArm' | 'leftHand' | 'rightHand' | 'leftLeg' | 'rightLeg';
export type Joints = Record<string, number>;

export const FINGERS = ['thumb', 'index', 'middle', 'ring', 'pinky'] as const;
export type Finger = typeof FINGERS[number];
const FINGER_LABELS: Record<Finger, string> = { thumb: '拇指', index: '食指', middle: '中指', ring: '无名指', pinky: '小指' };

export interface PoseControl {
  key: string;
  label: string;
  group: PoseGroupId;
  min: number;
  max: number;
  step: number;
  /** Metres rather than degrees (`body.offsetY`). */
  metres?: boolean;
  /** Narrowed by the body type's factor: the big limb joints. */
  limb?: boolean;
}

export const POSE_GROUPS: Array<{ id: PoseGroupId; label: string }> = [
  { id: 'head', label: '头颈' }, { id: 'torso', label: '躯干' },
  { id: 'leftArm', label: '左臂' }, { id: 'rightArm', label: '右臂' },
  { id: 'leftHand', label: '左手' }, { id: 'rightHand', label: '右手' },
  { id: 'leftLeg', label: '左腿' }, { id: 'rightLeg', label: '右腿' },
];

function sided(side: Side): PoseControl[] {
  const name = side === 'left' ? '左' : '右';
  // Spread is signed by the side it opens towards: outwards is negative on the left, positive on the right.
  const out = (inward: number, outward: number): [number, number] => (side === 'left' ? [-outward, inward] : [-inward, outward]);
  const [shoulderMin, shoulderMax] = out(40, 170);
  const [hipMin, hipMax] = out(30, 70);
  const arm: PoseGroupId = `${side}Arm`;
  const hand: PoseGroupId = `${side}Hand`;
  const leg: PoseGroupId = `${side}Leg`;
  return [
    { key: `${side}Shoulder.pitch`, label: `${name}肩 前后`, group: arm, min: -90, max: 180, step: 1, limb: true },
    { key: `${side}Shoulder.spread`, label: `${name}肩 开合`, group: arm, min: shoulderMin, max: shoulderMax, step: 1, limb: true },
    { key: `${side}Shoulder.twist`, label: `${name}肩 扭转`, group: arm, min: -90, max: 90, step: 1, limb: true },
    { key: `${side}Elbow.bend`, label: `${name}肘 弯曲`, group: arm, min: 0, max: 150, step: 1, limb: true },
    { key: `${side}Hand.pitch`, label: `${name}腕 屈伸`, group: hand, min: -80, max: 80, step: 1 },
    { key: `${side}Hand.roll`, label: `${name}腕 侧摆`, group: hand, min: -45, max: 45, step: 1 },
    { key: `${side}Hand.twist`, label: `${name}腕 扭转`, group: hand, min: -90, max: 90, step: 1 },
    ...FINGERS.flatMap<PoseControl>(finger => [
      { key: `${side}Hand.${finger}.curl`, label: `${FINGER_LABELS[finger]} 弯曲`, group: hand, min: 0, max: finger === 'thumb' ? 80 : 100, step: 1 },
      { key: `${side}Hand.${finger}.spread`, label: `${FINGER_LABELS[finger]} 张开`, group: hand, min: -20, max: 30, step: 1 },
    ]),
    { key: `${side}Hip.pitch`, label: `${name}髋 前后`, group: leg, min: -60, max: 120, step: 1, limb: true },
    { key: `${side}Hip.spread`, label: `${name}髋 开合`, group: leg, min: hipMin, max: hipMax, step: 1, limb: true },
    { key: `${side}Hip.twist`, label: `${name}髋 扭转`, group: leg, min: -60, max: 60, step: 1, limb: true },
    { key: `${side}Knee.bend`, label: `${name}膝 弯曲`, group: leg, min: 0, max: 150, step: 1, limb: true },
    { key: `${side}Foot.pitch`, label: `${name}踝 屈伸`, group: leg, min: -50, max: 70, step: 1 },
    { key: `${side}Foot.roll`, label: `${name}踝 侧摆`, group: leg, min: -30, max: 30, step: 1 },
    { key: `${side}Foot.twist`, label: `${name}踝 扭转`, group: leg, min: -40, max: 40, step: 1 },
  ];
}

export const POSE_CONTROLS: PoseControl[] = [
  { key: 'head.pitch', label: '低头 / 抬头', group: 'head', min: -60, max: 60, step: 1 },
  { key: 'head.yaw', label: '转头', group: 'head', min: -80, max: 80, step: 1 },
  { key: 'head.roll', label: '歪头', group: 'head', min: -40, max: 40, step: 1 },
  { key: 'body.pitch', label: '整体 前后倾', group: 'torso', min: -90, max: 90, step: 1 },
  { key: 'body.yaw', label: '整体 转向', group: 'torso', min: -90, max: 90, step: 1 },
  { key: 'body.roll', label: '整体 侧倾', group: 'torso', min: -90, max: 90, step: 1 },
  { key: 'torso.pitch', label: '上身 前后倾', group: 'torso', min: -60, max: 60, step: 1 },
  { key: 'torso.yaw', label: '上身 转向', group: 'torso', min: -60, max: 60, step: 1 },
  { key: 'torso.roll', label: '上身 侧倾', group: 'torso', min: -40, max: 40, step: 1 },
  { key: 'body.offsetY', label: '离地（米）', group: 'torso', min: 0, max: 2, step: 0.01, metres: true },
  ...sided('left'), ...sided('right'),
];

const CONTROL_BY_KEY = new Map(POSE_CONTROLS.map(control => [control.key, control]));

export const BODY_TYPE_IDS: BodyType[] = ['standard', 'slim', 'heavy', 'child'];
// A child's and a heavy figure's big joints open less far (upstream: 72° of 90° for a child).
const LIMB_FACTOR: Record<BodyType, number> = { standard: 1, slim: 1, heavy: 0.85, child: 0.8 };
const UPSTREAM_BODY_TYPES: Record<string, BodyType> = {
  mannequin: 'standard', female: 'slim', slim: 'slim', teen: 'slim', broad: 'heavy', muscular: 'heavy', child: 'child', chibi: 'child',
};

export function normalizeBodyType(value: string | undefined | null): BodyType {
  const text = String(value || '');
  return (BODY_TYPE_IDS as string[]).includes(text) ? text as BodyType : UPSTREAM_BODY_TYPES[text] ?? 'standard';
}

export function controlRange(key: string, bodyType: string | undefined | null = 'standard'): [number, number] | null {
  const control = CONTROL_BY_KEY.get(key);
  if (!control) return null;
  const factor = control.limb ? LIMB_FACTOR[normalizeBodyType(bodyType)] : 1;
  return [Math.round(control.min * factor), Math.round(control.max * factor)];
}

export function clampControl(key: string, value: number, bodyType?: string | null): number {
  const range = controlRange(key, bodyType);
  if (!range || !Number.isFinite(value)) return 0;
  return Math.min(range[1], Math.max(range[0], value));
}

/** Known controls only, inside their range for this body; zeros are dropped (rest is the default). */
export function clampPose(joints: Joints | undefined | null, bodyType?: string | null): Joints {
  const result: Joints = {};
  Object.entries(joints || {}).forEach(([key, value]) => {
    if (!CONTROL_BY_KEY.has(key)) return;
    const clamped = clampControl(key, Number(value), bodyType);
    if (clamped !== 0) result[key] = Math.round(clamped * 1000) / 1000;
  });
  return result;
}

export interface PosePreset {
  id: string;
  label: string;
  joints: Joints;
}

export const POSE_PRESETS: PosePreset[] = [
  { id: 'stand', label: '站立', joints: {} },
  { id: 't-pose', label: 'T型', joints: { 'leftShoulder.spread': -85, 'rightShoulder.spread': 85 } },
  { id: 'walk', label: '行走', joints: { 'leftShoulder.pitch': 20, 'rightShoulder.pitch': -20, 'leftElbow.bend': 12, 'rightElbow.bend': 18, 'leftHip.pitch': -20, 'rightHip.pitch': 20, 'leftKnee.bend': 12, 'rightKnee.bend': 4 } },
  { id: 'run', label: '跑步', joints: { 'body.pitch': -8, 'leftShoulder.pitch': 42, 'rightShoulder.pitch': -42, 'leftElbow.bend': 80, 'rightElbow.bend': 80, 'leftHip.pitch': -35, 'rightHip.pitch': 40, 'leftKnee.bend': 28, 'rightKnee.bend': 48 } },
  { id: 'sit', label: '坐姿', joints: { 'torso.pitch': -10, 'leftHip.pitch': 80, 'rightHip.pitch': 80, 'leftKnee.bend': 80, 'rightKnee.bend': 80, 'leftShoulder.pitch': 25, 'rightShoulder.pitch': 25, 'leftElbow.bend': 40, 'rightElbow.bend': 40 } },
  {
    id: 'crouch', label: '蹲下',
    joints: {
      'body.pitch': -26, 'torso.pitch': -24, 'head.pitch': -22, 'leftHip.pitch': 92, 'rightHip.pitch': 92, 'leftKnee.bend': 112, 'rightKnee.bend': 112, 'leftFoot.pitch': -40, 'rightFoot.pitch': -40,
      'leftShoulder.pitch': 52, 'rightShoulder.pitch': 50, 'leftShoulder.spread': -10, 'rightShoulder.spread': 10, 'leftElbow.bend': 80, 'rightElbow.bend': 76,
    },
  },
  {
    id: 'kneel-one', label: '单膝跪',
    joints: {
      'torso.pitch': -4, 'leftHip.pitch': 90, 'leftKnee.bend': 90, 'rightKnee.bend': 96, 'rightFoot.pitch': 70,
      'leftShoulder.pitch': 38, 'leftShoulder.spread': -6, 'leftElbow.bend': 40, 'rightShoulder.pitch': -8, 'rightShoulder.spread': 10, 'rightElbow.bend': 18,
    },
  },
  {
    id: 'kneel-two', label: '双膝跪',
    joints: {
      'body.pitch': 2, 'torso.pitch': -8, 'leftShoulder.pitch': 10, 'rightShoulder.pitch': 10, 'leftShoulder.spread': -5, 'rightShoulder.spread': 5,
      'leftElbow.bend': 8, 'rightElbow.bend': 8, 'leftHip.pitch': -4, 'rightHip.pitch': -4, 'leftKnee.bend': 94, 'rightKnee.bend': 94, 'leftFoot.pitch': 60, 'rightFoot.pitch': 60,
    },
  },
  {
    id: 'hands-on-hips', label: '叉腰',
    joints: {
      'leftShoulder.pitch': -20, 'rightShoulder.pitch': -20, 'leftShoulder.spread': -38, 'rightShoulder.spread': 38, 'leftShoulder.twist': 80, 'rightShoulder.twist': -80,
      'leftElbow.bend': 96, 'rightElbow.bend': 96, 'leftHand.roll': -35, 'rightHand.roll': 35,
    },
  },
  { id: 'lean', label: '倚靠', joints: { 'body.roll': -10, 'leftHip.spread': -10, 'rightHip.spread': 4, 'rightKnee.bend': 8, 'head.roll': 6, 'leftShoulder.spread': -12 } },
  {
    id: 'bow', label: '鞠躬',
    joints: {
      'body.pitch': -46, 'torso.pitch': -10, 'head.pitch': 20, 'leftHip.pitch': 49, 'rightHip.pitch': 49, 'leftShoulder.pitch': 5, 'rightShoulder.pitch': 5,
      'leftShoulder.spread': 10, 'rightShoulder.spread': -10, 'leftElbow.bend': 12, 'rightElbow.bend': 12,
    },
  },
  {
    id: 'think', label: '思考',
    joints: {
      'head.pitch': 8, 'rightShoulder.pitch': 30, 'rightShoulder.twist': -40, 'rightElbow.bend': 130, 'rightHand.pitch': 15,
      'leftShoulder.pitch': 12, 'leftShoulder.twist': 70, 'leftElbow.bend': 90,
    },
  },
  {
    id: 'fight', label: '格斗',
    joints: {
      'body.yaw': -10, 'body.pitch': -5, 'torso.yaw': 8, 'head.yaw': 8, 'leftShoulder.pitch': 48, 'leftShoulder.spread': -16, 'leftShoulder.twist': 22,
      'rightShoulder.pitch': 30, 'rightShoulder.twist': -22, 'leftElbow.bend': 96, 'rightElbow.bend': 110, 'leftHip.spread': -18, 'rightHip.spread': 22,
      'leftHip.pitch': 14, 'rightHip.pitch': -6, 'leftKnee.bend': 22, 'rightKnee.bend': 18,
    },
  },
  { id: 'kick', label: '踢球', joints: { 'leftHip.pitch': -8, 'rightHip.pitch': 58, 'rightKnee.bend': 35, 'leftShoulder.pitch': 18, 'rightShoulder.pitch': -24, 'leftKnee.bend': 6 } },
  {
    id: 'throw', label: '投掷',
    joints: {
      'body.pitch': -5, 'body.yaw': 14, 'torso.yaw': -10, 'head.yaw': 8, 'rightShoulder.pitch': 150, 'rightShoulder.spread': 14, 'rightShoulder.twist': 28, 'rightElbow.bend': 86,
      'rightHand.roll': 18, 'rightHand.pitch': -12, 'leftShoulder.pitch': 34, 'leftShoulder.spread': -10, 'leftShoulder.twist': 8, 'leftElbow.bend': 54, 'leftHand.pitch': -10,
      'leftHip.spread': -12, 'rightHip.spread': 18, 'leftHip.pitch': 24, 'rightHip.pitch': -10, 'leftKnee.bend': 30, 'rightKnee.bend': 14, 'leftFoot.pitch': -8, 'rightFoot.roll': 6,
    },
  },
  {
    id: 'push', label: '推进',
    joints: {
      'body.pitch': -12, 'torso.pitch': -4, 'head.pitch': -6, 'leftShoulder.pitch': 92, 'rightShoulder.pitch': 92, 'leftShoulder.spread': -6, 'rightShoulder.spread': 6,
      'leftElbow.bend': 6, 'rightElbow.bend': 6, 'leftHand.pitch': -60, 'rightHand.pitch': -60, 'leftHip.spread': -12, 'rightHip.spread': 14,
      'leftHip.pitch': 38, 'rightHip.pitch': -20, 'leftKnee.bend': 42, 'rightKnee.bend': 20, 'leftFoot.pitch': -6, 'rightFoot.roll': 8,
    },
  },
  {
    id: 'wave', label: '招手',
    joints: {
      'rightShoulder.pitch': 20, 'rightShoulder.spread': 80, 'rightShoulder.twist': 80, 'rightElbow.bend': 100, 'rightHand.roll': -20,
      'leftShoulder.pitch': -10, 'leftShoulder.spread': -8, 'leftElbow.bend': 18, 'leftHand.pitch': -8,
    },
  },
  { id: 'reach', label: '伸手', joints: { 'rightShoulder.pitch': 80, 'rightElbow.bend': 12, 'torso.pitch': -6 } },
  {
    id: 'cross-arms', label: '抱臂',
    joints: {
      'leftShoulder.pitch': 28, 'leftShoulder.spread': -8, 'leftShoulder.twist': 75, 'leftElbow.bend': 96, 'leftHand.pitch': -10,
      'rightShoulder.pitch': 36, 'rightShoulder.spread': 8, 'rightShoulder.twist': -75, 'rightElbow.bend': 104, 'rightHand.roll': 18, 'rightHand.pitch': -10,
    },
  },
  {
    id: 'phone', label: '看手机',
    joints: {
      'head.pitch': 18, 'rightShoulder.pitch': 20, 'rightShoulder.spread': 4, 'rightShoulder.twist': -30, 'rightElbow.bend': 112, 'rightHand.pitch': 14,
      'leftShoulder.pitch': -10, 'leftShoulder.spread': -8, 'leftElbow.bend': 16, 'leftHand.pitch': -8,
    },
  },
  // Five more from the product write-ups' own examples (万兴剧厂 / LUMI AI), written for this desk.
  {
    // 反派卧倒在地：俯卧，脸侧向一边，手臂收在身侧。
    id: 'lie', label: '卧倒',
    joints: {
      'body.pitch': 88, 'head.pitch': -20, 'head.yaw': 35, 'leftShoulder.pitch': -20, 'rightShoulder.pitch': 60, 'rightShoulder.spread': 30,
      'rightElbow.bend': 90, 'leftElbow.bend': 20, 'leftHip.pitch': -6, 'rightHip.pitch': 8, 'rightKnee.bend': 24,
    },
  },
  {
    // 背手站立：双手交叠在身后，胸口打开。
    id: 'hands-behind', label: '背手站立',
    joints: {
      'torso.pitch': -4, 'leftShoulder.pitch': -40, 'leftShoulder.spread': -10, 'leftShoulder.twist': 30, 'leftElbow.bend': 50, 'leftHand.pitch': 10,
      'rightShoulder.pitch': -40, 'rightShoulder.spread': 10, 'rightShoulder.twist': -30, 'rightElbow.bend': 50, 'rightHand.pitch': 10,
    },
  },
  {
    // 侧身回头：身体留在原方向，上身和头转向身后。
    id: 'look-back', label: '侧身回头',
    joints: {
      'torso.yaw': 35, 'head.yaw': 50, 'head.pitch': -4, 'leftShoulder.pitch': 6, 'rightShoulder.pitch': -8, 'leftElbow.bend': 14, 'rightElbow.bend': 10,
      'leftHip.spread': -8, 'rightHip.spread': 6, 'rightKnee.bend': 6,
    },
  },
  {
    // 抬手指向远处：右臂平伸，食指伸直，视线顺着手臂。
    id: 'point-ahead', label: '抬手指向',
    joints: {
      'torso.yaw': -8, 'head.yaw': -6, 'rightShoulder.pitch': 88, 'rightShoulder.spread': 6, 'rightElbow.bend': 6, 'rightHand.pitch': -8,
      'leftShoulder.pitch': -6, 'leftShoulder.spread': -6, 'leftElbow.bend': 14,
      'rightHand.thumb.curl': 60, 'rightHand.middle.curl': 95, 'rightHand.ring.curl': 95, 'rightHand.pinky.curl': 95,
    },
  },
  {
    // 出拳：左脚在前的弓步，右拳打出，左拳护在颌下。
    id: 'punch', label: '出拳',
    joints: {
      'body.yaw': -22, 'body.pitch': -6, 'torso.yaw': -18, 'head.yaw': 16, 'rightShoulder.pitch': 92, 'rightShoulder.spread': 4, 'rightShoulder.twist': -20,
      'rightElbow.bend': 8, 'rightHand.pitch': -4, 'leftShoulder.pitch': 50, 'leftShoulder.spread': -14, 'leftShoulder.twist': 30, 'leftElbow.bend': 120,
      'leftHip.pitch': 30, 'leftHip.spread': -16, 'leftKnee.bend': 36, 'rightHip.pitch': -18, 'rightHip.spread': 20, 'rightKnee.bend': 14, 'rightFoot.roll': 8,
      'rightHand.thumb.curl': 60, 'rightHand.index.curl': 95, 'rightHand.middle.curl': 95, 'rightHand.ring.curl': 95, 'rightHand.pinky.curl': 95,
      'leftHand.thumb.curl': 60, 'leftHand.index.curl': 95, 'leftHand.middle.curl': 95, 'leftHand.ring.curl': 95, 'leftHand.pinky.curl': 95,
    },
  },
];

export function presetById(id: string | undefined | null): PosePreset | undefined {
  return POSE_PRESETS.find(item => item.id === id);
}

export type FingerPresetId = 'open' | 'fist' | 'point' | 'pinch';
export const FINGER_PRESETS: Array<{ id: FingerPresetId; label: string }> = [
  { id: 'open', label: '张开' }, { id: 'fist', label: '握拳' }, { id: 'point', label: '指向' }, { id: 'pinch', label: '捏取' },
];
const FINGER_SHAPES: Record<FingerPresetId, Record<Finger, [curl: number, spread: number]>> = {
  open: { thumb: [0, 25], index: [0, 12], middle: [0, 4], ring: [0, 8], pinky: [0, 14] },
  fist: { thumb: [60, 0], index: [95, 0], middle: [95, 0], ring: [95, 0], pinky: [95, 0] },
  point: { thumb: [60, 0], index: [0, 0], middle: [95, 0], ring: [95, 0], pinky: [95, 0] },
  pinch: { thumb: [35, -10], index: [55, 0], middle: [25, 4], ring: [20, 6], pinky: [18, 10] },
};

/** The ten finger keys of one hand for a hand shape; every key is present so it overwrites what was there. */
export function expandFingerPreset(side: Side, preset: FingerPresetId): Joints {
  const joints: Joints = {};
  FINGERS.forEach(finger => {
    const [curl, spread] = FINGER_SHAPES[preset][finger];
    joints[`${side}Hand.${finger}.curl`] = curl;
    joints[`${side}Hand.${finger}.spread`] = spread;
  });
  return joints;
}

// Channels that change sign when left and right trade places. A finger's `spread` is measured
// away from the middle finger on either hand, so it is the one spread that does not.
const MIRRORED = /\.(yaw|roll|twist|spread)$/;
const FINGER_KEY = /Hand\.(thumb|index|middle|ring|pinky)\./;

function mirrorKey(key: string): string {
  if (key.startsWith('left')) return `right${key.slice(4)}`;
  if (key.startsWith('right')) return `left${key.slice(5)}`;
  return key;
}

export function mirrorJoints(joints: Joints): Joints {
  const result: Joints = {};
  Object.entries(joints).forEach(([key, value]) => {
    const flipped = MIRRORED.test(key) && !FINGER_KEY.test(key) ? -value : value;
    result[mirrorKey(key)] = flipped === 0 ? 0 : flipped;
  });
  return result;
}

/** Left and right swapped. The preset id no longer names these angles, so it is let go; a clip cannot be mirrored and stays. */
export function mirrorPose(pose: StagePose): StagePose {
  return { ...pose, preset: '', joints: mirrorJoints(pose.joints || {}) };
}

/** `a` at t = 0, `b` at t = 1, every control linearly in between (a control one side lacks is at rest there). */
export function blendPose(a: StagePose, b: StagePose, t: number): StagePose {
  const weight = Math.min(1, Math.max(0, t));
  const from = a.joints || {};
  const to = b.joints || {};
  const joints: Joints = {};
  new Set([...Object.keys(from), ...Object.keys(to)]).forEach(key => {
    const value = (from[key] ?? 0) * (1 - weight) + (to[key] ?? 0) * weight;
    if (Math.abs(value) > 1e-9) joints[key] = Math.round(value * 1000) / 1000;
  });
  const nearer = weight < 0.5 ? a : b;
  return {
    preset: weight === 0 ? a.preset || '' : weight === 1 ? b.preset || '' : '',
    joints, clip: nearer.clip || '', clip_phase: nearer.clip_phase ?? 0,
  };
}

/** A white model with limbs: a video model copies them, so captures of it carry `shows_limbs`. */
export function poseShowsLimbs(actor: Pick<StageActor, 'figure'>): boolean {
  return actor.figure === 'mannequin' || actor.figure === 'humanoid';
}

const POSTURES = new Set(['stand', 'walk', 'run', 'sit', 'crouch', 'kneel', 'lie', 'fight', 'bow', 'lean']);

/** Mirrors the backend's `pose_posture`: the posture a preset id leads with, or ''. */
export function posePosture(preset: string | undefined | null): string {
  const token = String(preset || '').trim().toLowerCase().replace(/_/g, '-').split('-', 1)[0];
  return POSTURES.has(token) ? token : '';
}

const POSTURE_PRESETS: Record<string, string> = {
  stand: 'stand', walk: 'walk', run: 'run', sit: 'sit', crouch: 'crouch', kneel: 'kneel-one', fight: 'fight', bow: 'bow', lean: 'lean',
};

/**
 * The angles a jointed figure is drawn with: the pose's own; else its preset's; else, for an
 * actor nobody has posed, what the plan's posture implies.
 */
export function jointsOf(actor: Pick<StageActor, 'pose' | 'posture' | 'body_type'>): Joints {
  const pose = actor.pose;
  if (pose?.joints && Object.keys(pose.joints).length) return clampPose(pose.joints, actor.body_type);
  if (pose?.preset) return clampPose(presetById(pose.preset)?.joints, actor.body_type);
  if (actor.posture === 'lie') return { 'body.pitch': 90 };
  return clampPose(presetById(POSTURE_PRESETS[actor.posture])?.joints, actor.body_type);
}
