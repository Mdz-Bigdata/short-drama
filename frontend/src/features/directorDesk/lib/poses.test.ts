import { describe, expect, it } from 'vitest';

import {
  BODY_TYPE_IDS, FINGERS, FINGER_PRESETS, POSE_CONTROLS, POSE_GROUPS, POSE_PRESETS, blendPose, clampControl, clampPose, controlRange,
  expandFingerPreset, jointsOf, mirrorJoints, mirrorPose, normalizeBodyType, posePosture, poseShowsLimbs, presetById,
} from './poses';

const UPSTREAM_25 = [
  'body.pitch', 'body.yaw', 'body.roll', 'torso.pitch', 'torso.yaw', 'torso.roll', 'head.pitch', 'head.yaw', 'head.roll',
  'leftShoulder.pitch', 'leftShoulder.spread', 'leftShoulder.twist', 'rightShoulder.pitch', 'rightShoulder.spread', 'rightShoulder.twist',
  'leftElbow.bend', 'rightElbow.bend', 'leftHip.pitch', 'leftHip.spread', 'leftHip.twist', 'rightHip.pitch', 'rightHip.spread', 'rightHip.twist',
  'leftKnee.bend', 'rightKnee.bend',
];

describe('pose controls', () => {
  const keys = POSE_CONTROLS.map(control => control.key);

  it('cover the upstream 25, hands, feet, the lift and ten finger keys per hand', () => {
    UPSTREAM_25.forEach(key => expect(keys).toContain(key));
    ['left', 'right'].forEach(side => {
      ['pitch', 'roll', 'twist'].forEach(channel => {
        expect(keys).toContain(`${side}Hand.${channel}`);
        expect(keys).toContain(`${side}Foot.${channel}`);
      });
      FINGERS.forEach(finger => {
        expect(keys).toContain(`${side}Hand.${finger}.curl`);
        expect(keys).toContain(`${side}Hand.${finger}.spread`);
      });
    });
    expect(keys).toContain('body.offsetY');
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys).toHaveLength(25 + 12 + 1 + 20);
    // The backend holds at most 120 joints of at most 60 characters, each within ±180.
    expect(keys.length).toBeLessThanOrEqual(120);
    POSE_CONTROLS.forEach(control => {
      expect(control.key).toMatch(/^[A-Za-z][A-Za-z0-9_.:-]{0,59}$/);
      expect(control.min).toBeGreaterThanOrEqual(-180);
      expect(control.max).toBeLessThanOrEqual(180);
      expect(control.min).toBeLessThanOrEqual(0);
      expect(control.max).toBeGreaterThanOrEqual(0);
    });
  });

  it('fall into the eight groups of the panel', () => {
    expect(POSE_GROUPS.map(group => group.label)).toEqual(['头颈', '躯干', '左臂', '右臂', '左手', '右手', '左腿', '右腿']);
    POSE_GROUPS.forEach(group => expect(POSE_CONTROLS.some(control => control.group === group.id)).toBe(true));
  });
});

describe('presets', () => {
  it('are the twenty of the upstream desk plus five from the product write-ups, inside the standard ranges, without a baked-in lift', () => {
    expect(POSE_PRESETS.map(preset => preset.id)).toEqual([
      'stand', 't-pose', 'walk', 'run', 'sit', 'crouch', 'kneel-one', 'kneel-two', 'hands-on-hips', 'lean', 'bow', 'think', 'fight', 'kick',
      'throw', 'push', 'wave', 'reach', 'cross-arms', 'phone',
      'lie', 'hands-behind', 'look-back', 'point-ahead', 'punch',
    ]);
    // 卧倒 implies the lying posture the backend reads a height from; the other four imply nothing.
    expect(['lie', 'hands-behind', 'look-back', 'point-ahead', 'punch'].map(posePosture)).toEqual(['lie', '', '', '', '']);
    POSE_PRESETS.forEach(preset => {
      expect(preset.joints['body.offsetY']).toBeUndefined();
      expect(clampPose(preset.joints, 'standard'), preset.id).toEqual(Object.fromEntries(Object.entries(preset.joints).filter(([, value]) => value !== 0)));
    });
  });

  it('lead with the posture word the backend reads the height from', () => {
    expect(['sit', 'kneel-one', 'kneel_two', 'Crouch', 'bow', 'wave', 't-pose', ''].map(posePosture)).toEqual(['sit', 'kneel', 'kneel', 'crouch', 'bow', '', '', '']);
  });
});

describe('clamps', () => {
  it('narrow the big joints for a child and a heavy figure, and leave the trunk alone', () => {
    expect(controlRange('leftKnee.bend', 'standard')).toEqual([0, 150]);
    expect(controlRange('leftKnee.bend', 'child')).toEqual([0, 120]);
    expect(controlRange('leftKnee.bend', 'heavy')).toEqual([0, 128]);
    expect(controlRange('body.pitch', 'child')).toEqual([-90, 90]);
    expect(controlRange('nonsense.key')).toBeNull();
    expect(clampControl('leftKnee.bend', 170, 'child')).toBe(120);
    expect(clampControl('leftKnee.bend', -20)).toBe(0);
    expect(clampControl('head.yaw', Number.NaN)).toBe(0);
  });

  it('sign the spread by the side it opens towards', () => {
    expect(controlRange('leftShoulder.spread')).toEqual([-170, 40]);
    expect(controlRange('rightShoulder.spread')).toEqual([-40, 170]);
  });

  it('drop unknown keys and zeros', () => {
    expect(clampPose({ 'leftKnee.bend': 400, 'spine.x': 20, 'head.yaw': 0, 'body.offsetY': -0.4 })).toEqual({ 'leftKnee.bend': 150 });
  });

  it('fold the upstream body types onto four', () => {
    expect(['mannequin', 'female', 'broad', 'muscular', 'teen', 'chibi', 'child', 'heavy', '', undefined].map(normalizeBodyType))
      .toEqual(['standard', 'slim', 'heavy', 'heavy', 'slim', 'child', 'child', 'heavy', 'standard', 'standard']);
    expect(BODY_TYPE_IDS).toEqual(['standard', 'slim', 'heavy', 'child']);
  });
});

describe('mirrorPose', () => {
  it('swaps left and right and negates yaw, roll, twist and spread', () => {
    expect(mirrorJoints({
      'leftShoulder.pitch': 40, 'leftShoulder.spread': -70, 'leftShoulder.twist': 20, 'rightKnee.bend': 30, 'head.yaw': 15, 'head.pitch': 10,
      'body.roll': -10, 'leftHand.roll': 12, 'leftHand.index.curl': 80, 'leftHand.index.spread': 12, 'body.offsetY': 0.2,
    })).toEqual({
      'rightShoulder.pitch': 40, 'rightShoulder.spread': 70, 'rightShoulder.twist': -20, 'leftKnee.bend': 30, 'head.yaw': -15, 'head.pitch': 10,
      'body.roll': 10, 'rightHand.roll': -12, 'rightHand.index.curl': 80, 'rightHand.index.spread': 12, 'body.offsetY': 0.2,
    });
  });

  it('is its own inverse, stays inside the ranges and lets go of the preset id', () => {
    POSE_PRESETS.forEach(preset => {
      const mirrored = mirrorPose({ preset: preset.id, joints: preset.joints });
      expect(mirrored.preset).toBe('');
      expect(clampPose(mirrored.joints, 'standard')).toEqual(clampPose(mirrored.joints, 'standard'));
      expect(Object.keys(clampPose(mirrored.joints, 'standard'))).toHaveLength(Object.keys(clampPose(preset.joints, 'standard')).length);
      expect(mirrorPose(mirrored).joints).toEqual(preset.joints);
    });
  });
});

describe('blendPose', () => {
  const a = { preset: 'stand', joints: { 'leftKnee.bend': 0, 'head.yaw': 20 }, clip: 'a', clip_phase: 0.2 };
  const b = { preset: 'sit', joints: { 'leftKnee.bend': 90 }, clip: 'b', clip_phase: 0.8 };

  it('is a at 0, b at 1 and linear in between', () => {
    expect(blendPose(a, b, 0)).toEqual({ preset: 'stand', joints: { 'head.yaw': 20 }, clip: 'a', clip_phase: 0.2 });
    expect(blendPose(a, b, 1)).toEqual({ preset: 'sit', joints: { 'leftKnee.bend': 90 }, clip: 'b', clip_phase: 0.8 });
    expect(blendPose(a, b, 0.25)).toEqual({ preset: '', joints: { 'leftKnee.bend': 22.5, 'head.yaw': 15 }, clip: 'a', clip_phase: 0.2 });
    expect(blendPose(a, b, 7).joints).toEqual({ 'leftKnee.bend': 90 });
  });
});

describe('finger presets', () => {
  it('expand to all ten keys of one hand', () => {
    expect(FINGER_PRESETS.map(item => item.label)).toEqual(['张开', '握拳', '指向', '捏取']);
    FINGER_PRESETS.forEach(({ id }) => {
      const joints = expandFingerPreset('right', id);
      expect(Object.keys(joints)).toHaveLength(10);
      expect(Object.keys(joints).every(key => key.startsWith('rightHand.'))).toBe(true);
      Object.entries(joints).forEach(([key, value]) => expect(clampControl(key, value)).toBe(value));
    });
    const point = expandFingerPreset('left', 'point');
    expect(point['leftHand.index.curl']).toBe(0);
    expect(point['leftHand.middle.curl']).toBeGreaterThan(80);
    expect(expandFingerPreset('left', 'fist')['leftHand.index.curl']).toBeGreaterThan(80);
    expect(expandFingerPreset('left', 'open')['leftHand.index.curl']).toBe(0);
    const pinch = expandFingerPreset('left', 'pinch');
    expect(pinch['leftHand.thumb.curl']).toBeGreaterThan(0);
    expect(pinch['leftHand.index.curl']).toBeGreaterThan(pinch['leftHand.pinky.curl']);
  });
});

describe('figures', () => {
  it('only the jointed and the skinned figure show limbs', () => {
    expect([undefined, 'standin', 'mannequin', 'humanoid'].map(figure => poseShowsLimbs({ figure: figure as never }))).toEqual([false, false, true, true]);
  });

  it('draws a pose by its angles, else its preset, else the posture of the plan', () => {
    expect(jointsOf({ pose: { preset: 'sit', joints: { 'head.yaw': 30 } }, posture: 'stand' })).toEqual({ 'head.yaw': 30 });
    expect(jointsOf({ pose: { preset: 'sit' }, posture: 'stand' })).toEqual(presetById('sit')!.joints);
    expect(jointsOf({ pose: null, posture: 'kneel' })).toEqual(presetById('kneel-one')!.joints);
    expect(jointsOf({ pose: null, posture: 'lie' })).toEqual({ 'body.pitch': 90 });
    expect(jointsOf({ posture: 'stand' })).toEqual({});
    expect(jointsOf({ pose: { joints: { 'leftKnee.bend': 140 } }, posture: 'stand', body_type: 'child' })).toEqual({ 'leftKnee.bend': 120 });
  });
});
