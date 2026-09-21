import { describe, expect, it } from 'vitest';

import { crowdMembersOf, mulberry32, nextCrowdId } from './crowdLayout';

describe('crowdLayout', () => {
  // Reference values printed by backend app/core/spatial_stage/crowds.py for the same input.
  it('draws the same numbers as the server', () => {
    const draw = mulberry32(42);
    expect([draw(), draw(), draw()]).toEqual([0.6011037519201636, 0.44829055899754167, 0.8524657934904099]);
  });

  it('lays out the same people as the server', () => {
    const members = crowdMembersOf({ id: 'crowd-01', label: '围观', rows: 2, columns: 2, spacing: 1.5, center: [1, -2], yaw_deg: 30, body_type: 'standard', seed: 42 });
    expect(members.map(actor => [actor.id, actor.name, actor.position, actor.yaw_deg, actor.height_m])).toEqual([
      ['crowd-01-001', '围观-01', [1.991, -1.674], 38.459, 1.723],
      ['crowd-01-002', '围观-02', [0.552, -0.736], 30.706, 1.64],
      ['crowd-01-003', '围观-03', [1.209, -2.775], 19.995, 1.741],
      ['crowd-01-004', '围观-04', [0.08, -2.593], 36.88, 1.683],
    ]);
    expect(members.every(actor => actor.role === 'crowd' && actor.crowd_id === 'crowd-01')).toBe(true);
  });

  it('numbers the next crowd the way the server will', () => {
    expect(nextCrowdId([])).toBe('crowd-01');
    expect(nextCrowdId([{ id: 'crowd-03' }, { id: 'crowd-01' }] as never)).toBe('crowd-04');
  });
});
