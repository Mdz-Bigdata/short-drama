// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { contactPlan } from '../../spatial/spatialFixtures';
import type { StageContact, StagePlan } from '../../spatial/spatialTypes';
import type { EditRequest, SelectionRef } from '../deskTypes';
import { Inspector } from './Inspector';
import { Outliner } from './Outliner';

vi.mock('../elementLibraryApi', () => ({
  listModelElements: vi.fn(() => Promise.resolve([])),
  importModelElement: vi.fn(),
  modelRefusal: vi.fn(() => ''),
}));

const HOLD = contactPlan().contacts![0];

describe('the 接触 section of the inspector', () => {
  const onCommit = vi.fn<(request: EditRequest) => void>();
  const show = (plan: StagePlan, selection: SelectionRef[], shotIndex = 0, editable = true) => (
    <Inspector plan={plan} shot={plan.shots[shotIndex]} selection={selection} editable={editable} error="" taskId="t1" onCommit={onCommit} onSelect={vi.fn()} />
  );
  const sent = () => onCommit.mock.calls.map(call => call[0].operations);
  const section = () => screen.getByRole('region', { name: '接触' });

  afterEach(() => {
    cleanup();
    onCommit.mockReset();
  });

  it('shows who holds a prop and in which hand, and keeps its place fields to the hand', () => {
    render(show(contactPlan(), [{ kind: 'landmark', name: '录音笔' }]));
    expect((within(section()).getByLabelText('拿在谁手里') as HTMLSelectElement).value).toBe('林夏');
    expect((within(section()).getByLabelText('哪只手') as HTMLSelectElement).value).toBe('right');
    expect((within(section()).getByLabelText('接触生效范围') as HTMLSelectElement).value).toBe('scene');
    expect(within(section()).getByText('跟着林夏的右手走；要单独移动，先选「不拿在手里」。')).toBeTruthy();
    expect((screen.getByLabelText('X（米）') as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText('朝向（°）') as HTMLInputElement).disabled).toBe(true);
    // Its size is still its own.
    expect((screen.getByLabelText('高（米）') as HTMLInputElement).disabled).toBe(false);
  });

  it('puts a free prop in a hand for this shot, or for the whole scene once 整场 is picked', async () => {
    const plan = contactPlan({ contacts: [] });
    const { unmount } = render(show(plan, [{ kind: 'landmark', name: '录音笔' }]));
    expect((within(section()).getByLabelText('哪只手') as HTMLSelectElement).disabled).toBe(true);
    await userEvent.selectOptions(within(section()).getByLabelText('拿在谁手里'), '周教授');
    expect(sent()[0]).toEqual([{ op: 'set_contact', kind: 'hold', actor: '周教授', target: '录音笔', hand: 'right', shot_ids: [1] }]);
    expect(onCommit.mock.calls[0][0].label).toBe('录音笔 交到 周教授 右手');
    unmount();

    render(show(plan, [{ kind: 'landmark', name: '录音笔' }]));
    await userEvent.selectOptions(within(section()).getByLabelText('接触生效范围'), 'scene');
    expect(onCommit).toHaveBeenCalledTimes(1);
    await userEvent.selectOptions(within(section()).getByLabelText('拿在谁手里'), '林夏');
    expect(sent()[1]).toEqual([{ op: 'set_contact', kind: 'hold', actor: '林夏', target: '录音笔', hand: 'right', shot_ids: [] }]);
  });

  it('switches hands and scope on the contact as it stands, and lets go of it', async () => {
    render(show(contactPlan(), [{ kind: 'landmark', name: '录音笔' }]));
    await userEvent.selectOptions(within(section()).getByLabelText('哪只手'), 'both');
    expect(sent()[0]).toEqual([{ op: 'set_contact', kind: 'hold', actor: '林夏', target: '录音笔', hand: 'both', shot_ids: [] }]);
    await userEvent.selectOptions(within(section()).getByLabelText('接触生效范围'), 'shot');
    // Narrowed to this shot, it is taken off the others first: a new contact only takes its own shots from them.
    expect(sent()[1]).toEqual([
      { op: 'remove_contact', target: '录音笔' },
      { op: 'set_contact', kind: 'hold', actor: '林夏', target: '录音笔', support: '', hand: 'right', shot_ids: [1] },
    ]);
    await userEvent.selectOptions(within(section()).getByLabelText('拿在谁手里'), '');
    // A whole-scene contact is let go of everywhere.
    expect(sent()[2]).toEqual([{ op: 'remove_contact', target: '录音笔' }]);
  });

  it('lets go of a contact tied to shots in this shot only, and names the shots a planner tied it to', async () => {
    const plan = contactPlan({ contacts: [{ ...HOLD, shot_ids: [1, 2] }] });
    render(show(plan, [{ kind: 'landmark', name: '录音笔' }], 1));
    const scope = within(section()).getByLabelText('接触生效范围') as HTMLSelectElement;
    expect(scope.value).toBe('listed');
    expect(within(scope).getByRole('option', { name: '第 1、2 镜' })).toBeTruthy();
    // Widened to the whole scene, the new contact replaces it alone.
    await userEvent.selectOptions(scope, 'scene');
    expect(sent()[0]).toEqual([{ op: 'set_contact', kind: 'hold', actor: '林夏', target: '录音笔', support: '', hand: 'right', shot_ids: [] }]);
    onCommit.mockReset();
    await userEvent.selectOptions(within(section()).getByLabelText('拿在谁手里'), '');
    expect(sent()[0]).toEqual([{ op: 'remove_contact', target: '录音笔', shot_id: 2 }]);
  });

  it('puts a prop on a piece of furniture, and takes it off again', async () => {
    render(show(contactPlan({ contacts: [] }), [{ kind: 'landmark', name: '茶杯' }]));
    const support = within(section()).getByLabelText('放在哪件东西上');
    // Only the set and the furniture are offered, never the piece itself or another hand prop.
    expect(within(support).getAllByRole('option').map(option => option.textContent)).toEqual(['不放在别的东西上', '书案', '扶手椅']);
    await userEvent.selectOptions(support, '书案');
    expect(sent()[0]).toEqual([{ op: 'set_contact', kind: 'rest', target: '茶杯', support: '书案', shot_ids: [1] }]);
    cleanup();

    const rest: StageContact = { id: 'contact-02', kind: 'rest', actor: '', target: '茶杯', support: '书案', hand: '', shot_ids: [1], source: 'manual' };
    render(show(contactPlan({ contacts: [rest] }), [{ kind: 'landmark', name: '茶杯' }]));
    expect(within(section()).getByText('贴在「书案」的台面上，只能在台面范围内挪动。')).toBeTruthy();
    await userEvent.selectOptions(within(section()).getByLabelText('放在哪件东西上'), '');
    expect(sent()[1]).toEqual([{ op: 'remove_contact', target: '茶杯', shot_id: 1 }]);
  });

  it('seats an actor on a seat-high piece, moves them to another, and stands them up', async () => {
    const plan = contactPlan({ contacts: [] });
    const { rerender } = render(show(plan, [{ kind: 'actor', name: '周教授' }]));
    const seat = within(section()).getByLabelText('坐在哪件家具上');
    // The desk is too high to sit on; the armchair is not.
    expect(within(seat).getAllByRole('option').map(option => option.textContent)).toEqual(['不坐', '扶手椅（0.45 米高）']);
    await userEvent.selectOptions(seat, '扶手椅');
    expect(sent()[0]).toEqual([{ op: 'set_contact', kind: 'sit', actor: '周教授', target: '扶手椅', shot_ids: [1] }]);

    const stool = { id: 'mark-09', name: '圆凳', kind: 'furniture' as const, position: [3, 2] as [number, number], size: [0.4, 0.4, 0.5] as [number, number, number] };
    const seated = contactPlan({
      landmarks: [...plan.landmarks, stool],
      contacts: [{ id: 'contact-02', kind: 'sit', actor: '周教授', target: '扶手椅', support: '', hand: '', shot_ids: [1], source: 'manual' }],
    });
    rerender(show(seated, [{ kind: 'actor', name: '周教授' }]));
    expect((screen.getByLabelText('X（米）') as HTMLInputElement).disabled).toBe(true);
    await userEvent.selectOptions(within(section()).getByLabelText('坐在哪件家具上'), '圆凳');
    // Off the old seat in the same edit, so one undo puts them back on it.
    expect(sent()[1]).toEqual([
      { op: 'remove_contact', target: '扶手椅', shot_id: 1 },
      { op: 'set_contact', kind: 'sit', actor: '周教授', target: '圆凳', shot_ids: [1] },
    ]);
    await userEvent.selectOptions(within(section()).getByLabelText('坐在哪件家具上'), '');
    expect(sent()[2]).toEqual([{ op: 'remove_contact', target: '扶手椅', shot_id: 1 }]);
    expect(onCommit.mock.calls[2][0].label).toBe('周教授 站起来');
  });

  it('carries contacts over a rename and takes them off before a delete', async () => {
    const rest: StageContact = { id: 'contact-02', kind: 'rest', actor: '', target: '茶杯', support: '书案', hand: '', shot_ids: [], source: 'manual' };
    render(show(contactPlan({ contacts: [HOLD, rest] }), [{ kind: 'landmark', name: '书案' }]));
    await userEvent.click(screen.getByRole('button', { name: /删除道具/ }));
    expect(sent()[0]).toEqual([{ op: 'remove_contact', target: '茶杯' }, { op: 'remove_landmark', name: '书案' }]);
    const name = screen.getByLabelText('名称') as HTMLInputElement;
    await userEvent.clear(name);
    await userEvent.type(name, '长案{Enter}');
    const renamed = sent()[1];
    expect(renamed[0]).toEqual({ op: 'remove_contact', target: '茶杯' });
    expect(renamed.slice(1, 3).map(item => item.op)).toEqual(['remove_landmark', 'add_landmark']);
    expect(renamed[renamed.length - 1]).toEqual({ op: 'set_contact', kind: 'rest', actor: '', target: '茶杯', support: '长案', hand: '', shot_ids: [] });
  });

  it('is read-only when the desk is', () => {
    render(show(contactPlan(), [{ kind: 'landmark', name: '录音笔' }], 0, false));
    within(section()).getAllByRole('combobox').forEach(select => expect((select as HTMLSelectElement).disabled).toBe(true));
  });
});

describe('the outliner', () => {
  it('says what a hand holds, what rests where and who sits on what', () => {
    const plan = contactPlan({
      contacts: [
        HOLD,
        { id: 'contact-02', kind: 'rest', actor: '', target: '茶杯', support: '书案', hand: '', shot_ids: [], source: 'manual' },
        { id: 'contact-03', kind: 'sit', actor: '周教授', target: '扶手椅', support: '', hand: '', shot_ids: [1], source: 'manual' },
      ],
    });
    const outliner = (shot: number) => (
      <Outliner
        plan={plan} shot={plan.shots[shot]} selection={[]} hidden={[]} locked={[]} editable
        onSelect={vi.fn()} onToggleHidden={vi.fn()} onToggleLocked={vi.fn()} onAddProp={vi.fn()} onAddCrowd={vi.fn()}
      />
    );
    const { rerender } = render(outliner(0));
    expect(screen.getByText('立方体 · 在林夏右手里')).toBeTruthy();
    expect(screen.getByText('立方体 · 放在书案上')).toBeTruthy();
    expect(screen.getByText('本镜主体 · 坐在扶手椅上')).toBeTruthy();
    // The sit is for shot 1 only.
    rerender(outliner(1));
    expect(screen.queryByText(/坐在扶手椅上/)).toBeNull();
    expect(screen.getByText('立方体 · 在林夏右手里')).toBeTruthy();
    cleanup();
  });
});
