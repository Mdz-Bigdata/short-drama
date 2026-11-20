// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { contactPlan } from '../../spatial/spatialFixtures';
import type { StageEffect, StagePlan } from '../../spatial/spatialTypes';
import type { EditRequest, SelectionRef } from '../deskTypes';
import { placeFor } from '../lib/effects';
import { EffectsSection } from './EffectsSection';

const MARK: StageEffect = { id: 'effect-01', kind: 'shock', position: [1, 0], radius_m: 3, source: '林夏', note: '', shot_ids: [] };

describe('the 特效占位 section', () => {
  const onCommit = vi.fn<(request: EditRequest) => void>();
  const show = (plan: StagePlan, selection: SelectionRef[] = [], editable = true, shotIndex = 0) => (
    <EffectsSection plan={plan} shot={plan.shots[shotIndex]} selection={selection} editable={editable} onCommit={onCommit} />
  );
  const sent = () => onCommit.mock.calls.map(call => call[0].operations);

  afterEach(() => {
    cleanup();
    onCommit.mockReset();
  });

  it('places a new marker a metre in front of the selected character, for this shot, with them as its sender', async () => {
    const user = userEvent.setup();
    const plan = contactPlan();
    const actor = plan.actors.find(item => item.name === '林夏')!;
    render(show(plan, [{ kind: 'actor', name: '林夏' }]));
    await user.selectOptions(screen.getByLabelText('新占位的种类'), 'fire');
    await user.click(screen.getByRole('button', { name: /放一个/ }));
    const [operation] = sent()[0];
    expect(operation).toMatchObject({ op: 'set_effect', id: 'effect-01', kind: 'fire', radius_m: 1.5, source: '林夏', shot_ids: [plan.shots[0].shot_id] });
    expect(operation.position).toEqual(placeFor(plan, [{ kind: 'actor', name: '林夏' }]).position);
    const [x, z] = operation.position as [number, number];
    expect(Math.hypot(x - actor.position[0], z - actor.position[1])).toBeCloseTo(1, 1);
    expect(onCommit.mock.calls[0][0].label).toBe('放一个火焰占位');
  });

  it('numbers the markers of the shot as the diagram does and dims one that belongs to another shot', () => {
    const plan = contactPlan({ effects: [MARK, { ...MARK, id: 'effect-02', kind: 'fire', shot_ids: [plan2ndShot()], note: '掌风' }] });
    render(show(plan));
    expect(screen.getByRole('group', { name: 'VFX-01 冲击波' })).toBeTruthy();
    const other = screen.getByRole('group', { name: `掌风（第 ${plan2ndShot()} 镜）` });
    expect(other.className).toContain('is-off');
  });

  it('sends one edit for each change: kind, radius, sender, scope, place, name, removal', async () => {
    const user = userEvent.setup();
    const plan = contactPlan({ effects: [MARK] });
    render(show(plan, [{ kind: 'landmark', name: plan.landmarks[0].name }]));
    const item = within(screen.getByRole('group', { name: 'VFX-01 冲击波' }));
    await user.selectOptions(item.getByLabelText(/的种类/), 'blast');
    await user.clear(item.getByLabelText(/的范围半径/));
    await user.type(item.getByLabelText(/的范围半径/), '4.5{Enter}');
    await user.selectOptions(item.getByLabelText(/由谁发出/), '');
    await user.selectOptions(item.getByLabelText(/的生效范围/), 'shot');
    await user.clear(item.getByLabelText(/的 X/));
    await user.type(item.getByLabelText(/的 X/), '-2{Enter}');
    await user.type(item.getByLabelText(/的叫法/), '气浪{Enter}');
    await user.click(item.getByRole('button', { name: /移到选中处/ }));
    await user.click(item.getByRole('button', { name: /删除/ }));
    expect(sent().map(operations => operations[0])).toEqual([
      { op: 'set_effect', id: 'effect-01', kind: 'blast' },
      { op: 'set_effect', id: 'effect-01', radius_m: 4.5 },
      { op: 'set_effect', id: 'effect-01', source: '' },
      { op: 'set_effect', id: 'effect-01', shot_ids: [plan.shots[0].shot_id] },
      { op: 'set_effect', id: 'effect-01', position: [-2, 0] },
      { op: 'set_effect', id: 'effect-01', note: '气浪' },
      { op: 'set_effect', id: 'effect-01', position: [plan.landmarks[0].position[0], plan.landmarks[0].position[1]] },
      { op: 'remove_effect', id: 'effect-01' },
    ]);
  });

  it('refuses a radius out of range in words and puts the old one back', async () => {
    const user = userEvent.setup();
    render(show(contactPlan({ effects: [MARK] })));
    const field = screen.getByLabelText(/的范围半径/) as HTMLInputElement;
    await user.clear(field);
    await user.type(field, '99{Enter}');
    expect(sent()).toEqual([]);
    expect(screen.getByRole('alert').textContent).toContain('0.2 到 30');
    expect(field.value).toBe('3');
  });

  it('is read-only when the desk is', () => {
    render(show(contactPlan({ effects: [MARK] }), [], false));
    expect((screen.getByRole('group', { name: 'VFX-01 冲击波' }) as HTMLFieldSetElement).disabled).toBe(true);
    expect(screen.queryByRole('button', { name: /放一个/ })).toBeNull();
  });
});

function plan2ndShot(): number {
  return contactPlan().shots[1].shot_id;
}
