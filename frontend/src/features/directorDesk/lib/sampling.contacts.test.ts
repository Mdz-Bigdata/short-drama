import { describe, expect, it } from 'vitest';

import { contactPlan } from '../../spatial/spatialFixtures';
import { actorsInShot, type StagePlan } from '../../spatial/spatialTypes';
import { applyAll } from '../deskOperations';
import { formulaHandPoint } from './contacts';
import { mannequinHandPoint } from './handBones';
import { sampleShot, stagePlanAt } from './sampling';

// 林夏 walks from her mark to the far side over two seconds, the recorder in her right hand.
function walking(plan: StagePlan = contactPlan()): StagePlan {
  return {
    ...plan,
    timelines: {
      1: {
        duration_s: 4, fps: 24, camera: [],
        actors: { 林夏: [{ time: 0, position: [-1.3, 0], yaw_deg: 90, easing: 'linear' }, { time: 2, position: [1.3, 0], yaw_deg: 90, easing: 'linear' }] },
      },
    },
  };
}

function pen(plan: StagePlan) {
  return plan.landmarks.find(item => item.name === '录音笔')!;
}

describe('contacts over the timeline', () => {
  it('carries a held prop along with a walking actor, frame after frame', () => {
    const plan = walking();
    [[0, -1.12], [0.5, -0.47], [1, 0.18], [2, 1.48], [3, 1.48]].forEach(([t, x]) => {
      const drawn = stagePlanAt(plan, 1, t);
      const lin = actorsInShot(drawn, drawn.shots[0]).find(actor => actor.name === '林夏')!;
      expect(pen(drawn).position[0], `t=${t}`).toBeCloseTo(x, 6);
      expect(pen(drawn).position[1], `t=${t}`).toBeCloseTo(0.22, 6);
      expect(pen(drawn).position).toEqual(formulaHandPoint(lin, 'right').filter((_, index) => index !== 1).map(value => Math.round(value * 1000) / 1000));
    });
  });

  it('follows a drag of the holder in progress, the way the desk previews it', () => {
    const dragged = applyAll(contactPlan(), [{ op: 'move_actor', name: '林夏', position: [0.5, 1] }]);
    expect(pen(stagePlanAt(dragged, 1, 0)).position).toEqual([0.68, 1.22]);
  });

  it('keeps a held prop in a posed mannequin’s real hand while the shot plays', () => {
    const base = walking();
    const plan = { ...base, actors: base.actors.map(actor => (actor.name === '林夏' ? { ...actor, figure: 'mannequin' as const, pose: { preset: 'walk', joints: {} } } : actor)) };
    [0.25, 0.5].forEach(t => {
      const drawn = stagePlanAt(plan, 1, t, undefined, { hand: mannequinHandPoint });
      const lin = actorsInShot(drawn, drawn.shots[0]).find(actor => actor.name === '林夏')!;
      const palm = mannequinHandPoint(lin, 'right')!;
      expect(pen(drawn).position[0]).toBeCloseTo(palm[0], 3);
      expect(pen(drawn).position[1]).toBeCloseTo(palm[2], 3);
    });
    // The gait swings the arm: the hand, and what it holds, is somewhere else a quarter cycle later.
    const early = pen(stagePlanAt(plan, 1, 0.25, undefined, { hand: mannequinHandPoint }));
    const later = pen(stagePlanAt(plan, 1, 0.5, undefined, { hand: mannequinHandPoint }));
    expect(early.elevation_m).not.toBeCloseTo(later.elevation_m ?? 0, 3);
  });

  it('keeps someone sitting on their seat whatever the keys say', () => {
    const base = walking();
    const plan: StagePlan = {
      ...base,
      contacts: [...(base.contacts || []), { id: 'contact-02', kind: 'sit', actor: '周教授', target: '扶手椅', support: '', hand: '', shot_ids: [1], source: 'manual' }],
      timelines: { 1: { ...base.timelines![1], actors: { ...base.timelines![1].actors, 周教授: [{ time: 0, position: [0, 3], easing: 'linear' }] } } },
    };
    expect(sampleShot(plan, plan.shots[0], 1).actors['周教授'].position).toEqual([2.5, 0]);
    const drawn = stagePlanAt(plan, 1, 1);
    const zhou = actorsInShot(drawn, drawn.shots[0]).find(actor => actor.name === '周教授')!;
    expect(zhou.position).toEqual([2.5, 0]);
    expect(zhou.posture).toBe('sit');
    // Shot 2 has no sit: the professor stands on his mark there.
    expect(sampleShot(plan, plan.shots[1], 1).actors['周教授'].position).toEqual([1.3, 0]);
  });

  it('draws a plan with no contacts exactly as before', () => {
    const plan = contactPlan({ contacts: [] });
    expect(stagePlanAt(plan, 1, 0)).toBe(plan);
    const old = { ...contactPlan() };
    delete old.contacts;
    expect(stagePlanAt(old, 1, 0)).toBe(old);
  });
});
