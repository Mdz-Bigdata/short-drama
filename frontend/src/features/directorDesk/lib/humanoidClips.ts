// The clip list and bone paths of the built-in skinned figure.
//
// From mangfufu/director-desk (MIT) src/animation/library/humanoid-v1-manifest.json; the figure and
// its ten motions are a curated derivative of the Quaternius Universal Animation Library (CC0-1.0),
// see public/models/director-desk/NOTICE.txt. What changed: the GLB the upstream ships as base64
// inside a JSON resource package is served here as a binary file, and only the clip table and the
// bone paths of the manifest are kept.

export const HUMANOID_MODEL_URL = `${import.meta.env.BASE_URL}models/director-desk/humanoid-v1.glb`;
export const HUMANOID_MODEL_SHA256 = '157fa9ab2f70d938621fcd8299db77fabf570f43d2cc8415f2ecedac51dc276b';

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
];

export const DEFAULT_HUMANOID_CLIP = HUMANOID_CLIPS[0].id;

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
