// The clip list and bone paths of the built-in skinned figure.
//
// From mangfufu/director-desk (MIT) src/animation/library/humanoid-v1-manifest.json; the figure and
// its ten motions are a curated derivative of the Quaternius Universal Animation Library (CC0-1.0),
// see public/models/director-desk/NOTICE.txt. What changed: the GLB the upstream ships as base64
// inside a JSON resource package is served here as a binary file, and only the clip table and the
// bone paths of the manifest are kept.
//
// humanoid-v2.glb is that file with twenty-four more motions (sword, fists, taking a hit, leaps)
// copied onto the same skeleton from the free Standard files of Universal Animation Library 1
// and 2 (CC0-1.0) by scripts/build-humanoid-motions.py. The first ten motions, the mesh and the
// bones are untouched, so everything below that was true of v1 still is.

export const HUMANOID_MODEL_URL = `${import.meta.env.BASE_URL}models/director-desk/humanoid-v2.glb`;
export const HUMANOID_MODEL_SHA256 = '81716d1b1f94db02dacfff2ceced8a75a92495b458631526bc4a2977ac5c4de2';

export interface HumanoidClip {
  id: string;
  name: string;
  group: string;
  /** Index of the animation inside the GLB. */
  index: number;
  duration: number;
  loop: boolean;
  /** The plan posture the clip shows; written as the pose's preset so the backend projects the right height. */
  posture: string;
}

export const HUMANOID_CLIPS: HumanoidClip[] = [
  { id: 'human-idle-v1', name: '站立待机', group: '站立', index: 0, duration: 2.5, loop: true, posture: 'stand' },
  { id: 'human-talk-v1', name: '交谈手势', group: '站立', index: 1, duration: 2.9333, loop: true, posture: 'stand' },
  { id: 'human-walk-v1', name: '行走', group: '移动', index: 2, duration: 1.3333, loop: true, posture: 'walk' },
  { id: 'human-jog-v1', name: '慢跑', group: '移动', index: 3, duration: 0.9333, loop: true, posture: 'run' },
  { id: 'human-crouch-idle-v1', name: '蹲姿待机', group: '蹲姿', index: 4, duration: 2.9333, loop: true, posture: 'crouch' },
  { id: 'human-crouch-walk-v1', name: '蹲着前进', group: '移动', index: 5, duration: 2, loop: true, posture: 'crouch' },
  { id: 'human-sit-enter-v1', name: '坐下', group: '坐姿', index: 6, duration: 1.3, loop: false, posture: 'sit' },
  { id: 'human-sit-idle-v1', name: '坐姿待机', group: '坐姿', index: 7, duration: 1.6667, loop: true, posture: 'sit' },
  { id: 'human-sit-talk-v1', name: '坐姿交谈', group: '坐姿', index: 8, duration: 2.9333, loop: true, posture: 'sit' },
  { id: 'human-sit-exit-v1', name: '站起', group: '坐姿', index: 9, duration: 1.0333, loop: false, posture: 'sit' },
  // From here on: scripts/build-humanoid-motions.py appends them in this order.
  { id: 'human-sword-idle-v1', name: '持剑戒备', group: '持剑', index: 10, duration: 1.6667, loop: true, posture: 'fight' },
  { id: 'human-sword-attack-v1', name: '挥剑劈砍', group: '持剑', index: 11, duration: 1.5333, loop: false, posture: 'fight' },
  { id: 'human-sword-block-v1', name: '持剑格挡', group: '持剑', index: 12, duration: 1.2333, loop: false, posture: 'fight' },
  { id: 'human-sword-dash-v1', name: '持剑突刺', group: '持剑', index: 13, duration: 1.5667, loop: false, posture: 'fight' },
  { id: 'human-sword-heavy-v1', name: '回身重斩', group: '持剑', index: 14, duration: 2, loop: false, posture: 'fight' },
  { id: 'human-sword-combo-v1', name: '三连斩', group: '持剑', index: 15, duration: 3, loop: false, posture: 'fight' },
  { id: 'human-sword-heavy-combo-v1', name: '重击连招', group: '持剑', index: 16, duration: 4.3333, loop: false, posture: 'fight' },
  { id: 'human-punch-jab-v1', name: '刺拳', group: '拳脚', index: 17, duration: 0.8667, loop: false, posture: 'fight' },
  { id: 'human-punch-cross-v1', name: '直拳', group: '拳脚', index: 18, duration: 1, loop: false, posture: 'fight' },
  { id: 'human-punch-hook-v1', name: '勾拳', group: '拳脚', index: 19, duration: 0.4667, loop: false, posture: 'fight' },
  { id: 'human-hit-chest-v1', name: '胸口受击', group: '受击', index: 20, duration: 0.3333, loop: false, posture: 'fight' },
  { id: 'human-hit-head-v1', name: '头部受击', group: '受击', index: 21, duration: 0.4333, loop: false, posture: 'fight' },
  { id: 'human-hit-knockback-v1', name: '被击退', group: '受击', index: 22, duration: 0.8333, loop: false, posture: 'fight' },
  { id: 'human-fall-v1', name: '中招倒地', group: '受击', index: 23, duration: 2.4, loop: false, posture: 'lie' },
  { id: 'human-get-up-v1', name: '倒地起身', group: '受击', index: 24, duration: 1.5333, loop: false, posture: 'stand' },
  { id: 'human-roll-v1', name: '翻滚', group: '腾跃', index: 25, duration: 1.4667, loop: false, posture: 'crouch' },
  { id: 'human-jump-start-v1', name: '起跳', group: '腾跃', index: 26, duration: 1.3333, loop: false, posture: 'stand' },
  { id: 'human-jump-air-v1', name: '腾空', group: '腾跃', index: 27, duration: 2.5, loop: true, posture: 'stand' },
  { id: 'human-jump-land-v1', name: '落地', group: '腾跃', index: 28, duration: 1.2667, loop: false, posture: 'stand' },
  { id: 'human-leap-start-v1', name: '轻功起跳', group: '腾跃', index: 29, duration: 0.9667, loop: false, posture: 'stand' },
  { id: 'human-leap-air-v1', name: '轻功腾空', group: '腾跃', index: 30, duration: 2, loop: true, posture: 'stand' },
  { id: 'human-leap-land-v1', name: '轻功落地', group: '腾跃', index: 31, duration: 1.2667, loop: false, posture: 'stand' },
  { id: 'human-sprint-v1', name: '冲刺', group: '移动', index: 32, duration: 0.6667, loop: true, posture: 'run' },
  { id: 'human-fold-arms-v1', name: '抱臂而立', group: '站立', index: 33, duration: 2.5, loop: true, posture: 'stand' },
];

export const DEFAULT_HUMANOID_CLIP = HUMANOID_CLIPS[0].id;

/** The motions under their group names, groups in the order they first appear: what a picker lists. */
export const HUMANOID_CLIP_GROUPS: Array<{ group: string; clips: HumanoidClip[] }> = [...new Set(HUMANOID_CLIPS.map(clip => clip.group))]
  .map(group => ({ group, clips: HUMANOID_CLIPS.filter(clip => clip.group === group) }));

const POSTURE_CLIPS: Record<string, string> = { walk: 'human-walk-v1', run: 'human-jog-v1', crouch: 'human-crouch-idle-v1', kneel: 'human-crouch-idle-v1', sit: 'human-sit-idle-v1' };

/** The clip a skinned figure shows before anyone picked one: whatever matches the plan's posture. */
export function clipForPosture(posture: string | undefined | null): string {
  return POSTURE_CLIPS[String(posture || '')] ?? DEFAULT_HUMANOID_CLIP;
}

export function humanoidClip(id: string | undefined | null): HumanoidClip {
  return HUMANOID_CLIPS.find(item => item.id === id) ?? HUMANOID_CLIPS[0];
}

/** Child-index paths from the scene root to each anatomical bone (the rig definition of the manifest). */
export const HUMANOID_BONE_PATHS: Record<string, string> = {
  hips: '0/0/1/0', spine: '0/0/1/0/0', chest: '0/0/1/0/0/0', upperChest: '0/0/1/0/0/0/0', neck: '0/0/1/0/0/0/0/0', head: '0/0/1/0/0/0/0/0/0',
  leftShoulder: '0/0/1/0/0/0/0/1', leftUpperArm: '0/0/1/0/0/0/0/1/0', leftLowerArm: '0/0/1/0/0/0/0/1/0/0', leftHand: '0/0/1/0/0/0/0/1/0/0/0',
  rightShoulder: '0/0/1/0/0/0/0/2', rightUpperArm: '0/0/1/0/0/0/0/2/0', rightLowerArm: '0/0/1/0/0/0/0/2/0/0', rightHand: '0/0/1/0/0/0/0/2/0/0/0',
  leftUpperLeg: '0/0/1/0/1', leftLowerLeg: '0/0/1/0/1/0', leftFoot: '0/0/1/0/1/0/0', leftToes: '0/0/1/0/1/0/0/0',
  rightUpperLeg: '0/0/1/0/2', rightLowerLeg: '0/0/1/0/2/0', rightFoot: '0/0/1/0/2/0/0', rightToes: '0/0/1/0/2/0/0/0',
};
