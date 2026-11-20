import { describe, expect, it } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { StagePlan } from '../../spatial/spatialTypes';
import { focusOf } from './viewFocus';

describe('focusOf', () => {
  it('has nothing to look at without a selection, or when the pick is not on stage', () => {
    expect(focusOf(PLAN, PLAN.shots[0], [])).toBeNull();
    expect(focusOf(PLAN, PLAN.shots[0], [{ kind: 'actor', name: '不在场' }])).toBeNull();
    // 助手 is offstage in shot 2.
    expect(focusOf(PLAN, PLAN.shots[1], [{ kind: 'actor', name: '助手' }])).toBeNull();
  });

  it('centres on an actor at half height', () => {
    expect(focusOf(PLAN, PLAN.shots[0], [{ kind: 'actor', name: '林夏' }])).toEqual({ center: [-1.3, 0.85, 0], radius: 1.7 * 0.75 });
  });

  it('follows a shot override rather than the mark', () => {
    const shot = { ...PLAN.shots[0], overrides: [{ name: '林夏', position: [0, 2] as [number, number], reason: '走到窗边' }] };
    expect(focusOf(PLAN, shot, [{ kind: 'actor', name: '林夏' }])?.center).toEqual([0, 0.85, 2]);
  });

  it('centres on a raised piece where it is, and never closes in tighter than a small prop needs', () => {
    const plan: StagePlan = { ...PLAN, landmarks: [{ ...PLAN.landmarks[0], size: [0.1, 0.02, 0.02], elevation_m: 0.75 }] };
    expect(focusOf(plan, undefined, [{ kind: 'landmark', name: '录音笔' }])).toEqual({ center: [0, 0.76, -0.9], radius: 0.6 });
  });

  it('takes a large piece by its diagonal', () => {
    const plan: StagePlan = { ...PLAN, landmarks: [{ ...PLAN.landmarks[0], size: [6, 8, 0] }] };
    expect(focusOf(plan, undefined, [{ kind: 'landmark', name: '录音笔' }])?.radius).toBe(5);
  });

  it('looks at a lens or at its look-at handle', () => {
    expect(focusOf(PLAN, undefined, [{ kind: 'camera', id: 'cam-01' }])).toEqual({ center: [0, 1.45, 5.2], radius: 1.5 });
    expect(focusOf(PLAN, undefined, [{ kind: 'camera-target', id: 'cam-01' }])).toEqual({ center: [0, 0.9, 0], radius: 1.5 });
  });

  it('holds everything picked in one ball', () => {
    const focus = focusOf(PLAN, PLAN.shots[0], [{ kind: 'actor', name: '林夏' }, { kind: 'actor', name: '周教授' }])!;
    expect(focus.center[0]).toBeCloseTo(0, 6);
    expect(focus.center[2]).toBeCloseTo(0, 6);
    // 2.6 m apart, plus each one's own reach on either side.
    expect(focus.radius).toBeCloseTo(1.3 + 1.7 * 0.75, 6);
  });

  it('takes a crowd by its members', () => {
    const plan: StagePlan = {
      ...PLAN,
      actors: [
        ...PLAN.actors,
        { id: 'actor-10', name: '路人 1', position: [4, 4], yaw_deg: 180, height_m: 1.7, posture: 'stand', role: 'crowd', screen_side: 'center', crowd_id: 'crowd-01' },
        { id: 'actor-11', name: '路人 2', position: [10, 4], yaw_deg: 180, height_m: 1.7, posture: 'stand', role: 'crowd', screen_side: 'center', crowd_id: 'crowd-01' },
      ],
    };
    const focus = focusOf(plan, undefined, [{ kind: 'crowd', id: 'crowd-01' }])!;
    expect(focus.center[0]).toBeCloseTo(7, 6);
    expect(focus.radius).toBeCloseTo(3 + 1.2, 6);
  });
});
