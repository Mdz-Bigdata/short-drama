import { Vector3 } from 'three';
import { describe, expect, it } from 'vitest';

import { boneLocals, contactsOf, figureMatrix, figureTop, groundLift, solveBones } from './mannequinRig';
import { BODY_TYPE_IDS, POSE_PRESETS, clampPose, expandFingerPreset, mirrorJoints } from './poses';

describe('the jointed figure', () => {
  it('stands exactly one unit tall on its soles for every body type, so height_m is its height', () => {
    BODY_TYPE_IDS.forEach(bodyType => {
      expect(groundLift({}, bodyType), bodyType).toBeCloseTo(0, 9);
      expect(figureTop({}, bodyType), bodyType).toBeCloseTo(1, 9);
    });
  });

  it('keeps its lowest contact on the ground for every preset and body type', () => {
    BODY_TYPE_IDS.forEach(bodyType => {
      POSE_PRESETS.forEach(preset => {
        const joints = clampPose(preset.joints, bodyType);
        const lift = groundLift(joints, bodyType);
        const contacts = contactsOf(solveBones(joints, bodyType), bodyType);
        const lowest = Math.min(...contacts.map(contact => contact.point.y - contact.radius + lift));
        expect(lowest, `${preset.id}/${bodyType}`).toBeCloseTo(0, 9);
        // Nothing is under the floor and the figure has not left it.
        contacts.forEach(contact => expect(contact.point.y - contact.radius + lift).toBeGreaterThanOrEqual(-1e-9));
        expect(figureTop(joints, bodyType)).toBeLessThanOrEqual(1.35);
      });
    });
  });

  it('rests on a foot in the standing presets and on a knee when kneeling', () => {
    const resting = (id: string) => {
      const joints = POSE_PRESETS.find(preset => preset.id === id)!.joints;
      const lift = groundLift(joints, 'standard');
      return contactsOf(solveBones(joints, 'standard'), 'standard').filter(contact => contact.point.y - contact.radius + lift < 0.012).map(contact => contact.id);
    };
    ['stand', 'walk', 'run', 'kick', 'fight', 'bow', 'sit', 'crouch'].forEach(id => {
      expect(resting(id).some(contact => /Heel|Toe/.test(contact)), id).toBe(true);
    });
    expect(resting('kneel-one')).toContain('rightKnee');
    expect(resting('kneel-two')).toEqual(expect.arrayContaining(['leftKnee', 'rightKnee']));
    // A lying figure rests on its back, not on its feet.
    const lying = groundLift({ 'body.pitch': 90 }, 'standard');
    expect(figureTop({ 'body.pitch': 90 }, 'standard')).toBeLessThan(0.35);
    expect(lying).toBeGreaterThan(-0.6);
  });

  it('gets shorter when it sits, crouches or kneels', () => {
    const top = (id: string) => figureTop(POSE_PRESETS.find(preset => preset.id === id)!.joints, 'standard');
    expect(top('sit')).toBeLessThan(0.85);
    expect(top('crouch')).toBeLessThan(0.75);
    expect(top('kneel-two')).toBeLessThan(0.8);
  });

  it('puts the left side on +X, swings a positive pitch forward and bends knees back, elbows forward', () => {
    const rest = solveBones({}, 'standard');
    expect(rest.leftShoulder.position.x).toBeGreaterThan(0);
    expect(rest.rightHip.position.x).toBeLessThan(0);
    expect(solveBones({ 'rightShoulder.pitch': 90 }, 'standard').rightHand.position.z).toBeGreaterThan(0.25);
    expect(solveBones({ 'leftHip.pitch': 60 }, 'standard').leftFoot.position.z).toBeGreaterThan(0.3);
    expect(solveBones({ 'leftKnee.bend': 90 }, 'standard').leftFoot.position.z).toBeLessThan(-0.2);
    expect(solveBones({ 'leftElbow.bend': 90 }, 'standard').leftHand.position.z).toBeGreaterThan(0.1);
    // Spread opens away from the body on both sides.
    expect(solveBones({ 'leftShoulder.spread': -80 }, 'standard').leftHand.position.x).toBeGreaterThan(0.35);
    expect(solveBones({ 'rightShoulder.spread': 80 }, 'standard').rightHand.position.x).toBeLessThan(-0.35);
    // Body leans forward on a negative pitch, the head nods down on a positive one.
    expect(solveBones({ 'body.pitch': -40 }, 'standard').head.position.z).toBeGreaterThan(0.1);
  });

  it('mirrors geometrically: a mirrored pose is the reflection in the X = 0 plane', () => {
    POSE_PRESETS.forEach(preset => {
      const joints = { ...preset.joints, ...expandFingerPreset('left', 'pinch') };
      const original = solveBones(joints, 'standard');
      const mirrored = solveBones(mirrorJoints(joints), 'standard');
      Object.keys(original).forEach(id => {
        const twin = id.startsWith('left') ? `right${id.slice(4)}` : id.startsWith('right') ? `left${id.slice(5)}` : id;
        const expected = original[id].position.clone().multiply(new Vector3(-1, 1, 1));
        expect(mirrored[twin].position.distanceTo(expected), `${preset.id}:${id}`).toBeLessThan(1e-9);
      });
    });
  });

  it('curls a finger towards the palm', () => {
    const open = solveBones({}, 'standard')['leftHand.index.tip'].position;
    const curled = solveBones({ 'leftHand.index.curl': 90 }, 'standard')['leftHand.index.tip'].position;
    expect(curled.x).toBeLessThan(open.x - 0.01);
    expect(boneLocals({}, 'standard').filter(bone => bone.id.includes('Hand.'))).toHaveLength(20);
  });

  it('places a grounded figure on the stage at the actor height', () => {
    const matrix = figureMatrix({ position: [2, -3], yaw_deg: 90, height_m: 1.6 }, 0);
    const head = new Vector3(0, 1, 0).applyMatrix4(matrix);
    expect(head.toArray().map(value => Math.round(value * 1000) / 1000)).toEqual([2, 1.6, -3]);
    const nose = new Vector3(0, 0, 1).applyMatrix4(matrix);
    expect(nose.x).toBeCloseTo(3.6, 6);
  });
});
