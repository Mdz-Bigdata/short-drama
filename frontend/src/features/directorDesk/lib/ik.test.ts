import { Vector3 } from 'three';
import { describe, expect, it } from 'vitest';

import { chainOf, effectorOf, ikControls, solveTwoBone, IK_MAX_ITERATIONS, IK_TOLERANCE_M } from './ik';
import { effectorBones, solveBones, EFFECTORS } from './mannequinRig';
import { controlRange, presetById, type Joints } from './poses';

const HEIGHT = 1.7;

function effectorAfter(joints: Joints, bodyType: string, effector: Parameters<typeof chainOf>[3]) {
  return solveBones(joints, bodyType)[effectorBones(effector).end].position.clone().multiplyScalar(HEIGHT);
}

describe('solveTwoBone', () => {
  it('starts where the figure is', () => {
    EFFECTORS.forEach(({ id }) => {
      const joints = presetById('fight')!.joints;
      expect(effectorOf(chainOf(joints, 'standard', HEIGHT, id)).distanceTo(effectorAfter(joints, 'standard', id))).toBeLessThan(1e-9);
    });
  });

  it('reaches reachable targets within 5 mm in at most ten iterations', () => {
    const cases: Array<[Parameters<typeof chainOf>[3], Vector3]> = [
      ['rightWrist', new Vector3(-0.25, 1.3, 0.35)],
      ['rightWrist', new Vector3(-0.45, 1.0, 0.2)],
      ['leftWrist', new Vector3(0.2, 1.45, 0.3)],
      ['leftWrist', new Vector3(0.3, 0.9, 0.25)],
      ['leftAnkle', new Vector3(0.1, 0.35, 0.3)],
      ['rightAnkle', new Vector3(-0.12, 0.25, -0.25)],
    ];
    cases.forEach(([id, target]) => {
      const result = solveTwoBone(chainOf({}, 'standard', HEIGHT, id), target);
      expect(result.reached, `${id} → ${target.toArray()}`).toBe(true);
      expect(result.error).toBeLessThan(IK_TOLERANCE_M);
      expect(result.iterations).toBeLessThanOrEqual(IK_MAX_ITERATIONS);
    });
  });

  it('writes a solution back as control keys that put the figure where the solver said', () => {
    const target = new Vector3(-0.25, 1.3, 0.35);
    const controls = ikControls('rightWrist', solveTwoBone(chainOf({}, 'standard', HEIGHT, 'rightWrist'), target), 'standard');
    expect(Object.keys(controls).sort()).toEqual(['rightElbow.bend', 'rightShoulder.pitch', 'rightShoulder.spread', 'rightShoulder.twist']);
    Object.entries(controls).forEach(([key, value]) => {
      const [min, max] = controlRange(key, 'standard')!;
      expect(value).toBeGreaterThanOrEqual(min);
      expect(value).toBeLessThanOrEqual(max);
    });
    // Tenths of a degree cost a millimetre or two on top of the solver's 5.
    expect(effectorAfter(controls, 'standard', 'rightWrist').distanceTo(target)).toBeLessThan(0.008);
  });

  it('stretches towards a target it cannot reach, and no further', () => {
    const chain = chainOf({}, 'standard', HEIGHT, 'rightWrist');
    const target = new Vector3(-0.4, 1.6, 3);
    const result = solveTwoBone(chain, target);
    const reach = result.effector.distanceTo(chain.origin);
    expect(result.reached).toBe(false);
    expect(reach).toBeLessThanOrEqual(chain.upperLength + chain.lowerLength + 1e-9);
    expect(reach).toBeGreaterThan((chain.upperLength + chain.lowerLength) * 0.97);
    const aim = result.effector.clone().sub(chain.origin).normalize().dot(target.clone().sub(chain.origin).normalize());
    expect(aim).toBeGreaterThan(0.99);
    expect(result.bend).toBeGreaterThanOrEqual(0);
  });

  it('keeps every joint inside its range even when the target asks for more', () => {
    const chain = chainOf({}, 'child', 1.2, 'leftAnkle');
    const result = solveTwoBone(chain, new Vector3(0.05, 1.4, -0.6));
    result.upper.forEach((value, index) => {
      expect(value).toBeGreaterThanOrEqual(chain.limits.upper[index][0] - 1e-9);
      expect(value).toBeLessThanOrEqual(chain.limits.upper[index][1] + 1e-9);
    });
    expect(result.bend).toBeLessThanOrEqual(chain.limits.bend[1] + 1e-9);
    expect(ikControls('leftAnkle', result, 'child')['leftKnee.bend']).toBeLessThanOrEqual(controlRange('leftKnee.bend', 'child')![1]);
  });

  it('foot lock keeps the ankle at the height it was grabbed at', () => {
    const chain = chainOf({}, 'standard', HEIGHT, 'leftAnkle');
    const grabbedAt = effectorOf(chain).y;
    const free = solveTwoBone(chain, new Vector3(0.1, grabbedAt + 0.2, 0.3));
    const locked = solveTwoBone(chain, new Vector3(0.1, grabbedAt + 0.2, 0.3), { lockY: grabbedAt });
    expect(free.effector.y).toBeGreaterThan(grabbedAt + 0.15);
    // A straight leg cannot slide along the floor without bending the other knee: the lock holds
    // the height as closely as the leg's length allows and never lets the foot rise.
    expect(locked.effector.y).toBeLessThan(grabbedAt + 0.06);
    const crouched = chainOf(presetById('fight')!.joints, 'standard', HEIGHT, 'leftAnkle');
    const height = effectorOf(crouched).y;
    const slid = solveTwoBone(crouched, new Vector3(0.2, height + 0.3, 0.2), { lockY: height });
    expect(Math.abs(slid.effector.y - height)).toBeLessThan(IK_TOLERANCE_M);
  });

  it('is idempotent: the answer depends on the grab snapshot and the target, not on the path', () => {
    const chain = chainOf(presetById('walk')!.joints, 'standard', HEIGHT, 'rightWrist');
    const target = new Vector3(-0.3, 1.2, 0.3);
    const direct = solveTwoBone(chain, target);
    solveTwoBone(chain, new Vector3(0.3, 0.4, -0.3));
    solveTwoBone(chain, new Vector3(-0.6, 1.6, 0.1));
    const again = solveTwoBone(chain, target);
    expect(again.upper).toEqual(direct.upper);
    expect(again.bend).toBe(direct.bend);
    // The snapshot itself is never written to.
    expect(chain.upper).toEqual(chainOf(presetById('walk')!.joints, 'standard', HEIGHT, 'rightWrist').upper);
  });
});
