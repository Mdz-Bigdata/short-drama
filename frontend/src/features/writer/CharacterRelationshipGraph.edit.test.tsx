// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CharacterRelationshipGraph } from './CharacterRelationshipGraph';
import { RelationshipEditor } from './RelationshipEditor';
import type { WriterRelationship } from './types';

const roles = [
  { name: '萧遥', position: '男主角' },
  { name: '王衍', position: '权臣' },
  { name: '管家', position: '配角' },
];

const relationships: WriterRelationship[] = [
  { from: '萧遥', to: '王衍', relation: '智斗', bidirectional: false },
  { from: '萧遥', to: '管家', relation: '同场互动 · 2 场', bidirectional: true },
];

describe('CharacterRelationshipGraph', () => {
  afterEach(cleanup);

  it('draws the cast as nodes with a name chip and role, the lead in the middle, and the relations as lines', () => {
    const { container } = render(<CharacterRelationshipGraph roles={roles} relationships={relationships} avatars={{ 萧遥: 'https://cdn/xiao.png' }} />);
    expect(screen.getByRole('img', { name: '3名角色、1条人物关系组成的关系图谱' })).toBeTruthy();
    const lead = container.querySelector('.writer-relationship-graph__node.is-lead');
    expect(lead?.getAttribute('transform')).toBe('translate(340 190)');
    expect(lead?.querySelector('image')?.getAttribute('href')).toBe('https://cdn/xiao.png');
    expect(container.querySelectorAll('.writer-relationship-graph__node')).toHaveLength(3);
    expect([...container.querySelectorAll('.writer-relationship-graph__name')].map(node => node.textContent)).toEqual(['萧遥', '王衍', '管家']);
    expect([...container.querySelectorAll('.writer-relationship-graph__role')].map(node => node.textContent)).toEqual(['男主角', '权臣', '配角']);
    // Nobody without a portrait is left blank: the first character stands in.
    expect(container.querySelectorAll('.writer-relationship-graph__initial')).toHaveLength(2);
    // A pairing counted from shared scenes is not a relation: it is not drawn.
    expect(container.querySelectorAll('[data-relation-edge]')).toHaveLength(1);
    // Every line is named by its relation.
    expect([...container.querySelectorAll('[data-relation-label="true"]')].map(node => node.textContent)).toEqual(['智斗']);
    expect(container.textContent).not.toMatch(/同场/);
    expect(screen.getByRole('group', { name: '星图缩放' })).toBeTruthy();
  });

  it('names the people who did not fit in the picture', () => {
    const many = Array.from({ length: 15 }, (_, index) => ({ name: `角色${index + 1}`, position: index === 0 ? '男主角' : '配角' }));
    render(<CharacterRelationshipGraph roles={many} relationships={[]} />);
    expect(screen.getByRole('img', { name: '图中展示12/15名角色、0/0条人物关系' })).toBeTruthy();
    expect(screen.getByLabelText('图外角色 3 名').textContent).toContain('角色13（配角）');
  });
});

describe('RelationshipEditor', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('lists every relation as from → to · tag and is read-only without a save handler', () => {
    render(<RelationshipEditor roles={roles} relationships={relationships} />);
    const rows = screen.getAllByText(/→|↔/);
    expect(rows).toHaveLength(2);
    expect(screen.getByText('智斗')).toBeTruthy();
    expect(screen.queryByRole('form')).toBeNull();
    expect(screen.queryByRole('button', { name: /删除/ })).toBeNull();
  });

  it('adds a relationship from the form with both ends picked from the cast', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<RelationshipEditor roles={roles} relationships={relationships} onSave={onSave} />);

    const form = screen.getByRole('form', { name: '新增人物关系' });
    await user.selectOptions(within(form).getByLabelText('起始角色'), '王衍');
    await user.selectOptions(within(form).getByLabelText('目标角色'), '管家');
    await user.type(within(form).getByPlaceholderText('例如: 夫妻, 宿敌'), '主仆');
    await user.click(within(form).getByRole('checkbox'));
    await user.click(within(form).getByRole('button', { name: '添加' }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith([...relationships, { from: '王衍', to: '管家', relation: '主仆', bidirectional: true }]);
  });

  it('rejects a relationship whose two ends are the same character', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<RelationshipEditor roles={roles} relationships={relationships} onSave={onSave} />);

    const form = screen.getByRole('form', { name: '新增人物关系' });
    await user.selectOptions(within(form).getByLabelText('起始角色'), '萧遥');
    await user.selectOptions(within(form).getByLabelText('目标角色'), '萧遥');
    await user.click(within(form).getByRole('button', { name: '添加' }));

    expect(screen.getByRole('alert').textContent).toContain('不能是同一个角色');
    expect(onSave).not.toHaveBeenCalled();
  });

  it('edits an existing relationship in the same form', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<RelationshipEditor roles={roles} relationships={relationships} onSave={onSave} />);

    await user.click(screen.getByRole('button', { name: '编辑 萧遥 与 王衍 的关系' }));
    const form = screen.getByRole('form', { name: '编辑人物关系' });
    expect((within(form).getByLabelText('起始角色') as HTMLSelectElement).value).toBe('萧遥');
    const relation = within(form).getByPlaceholderText('例如: 夫妻, 宿敌');
    await user.clear(relation);
    await user.type(relation, '亦敌亦友');
    await user.click(within(form).getByRole('button', { name: '保存修改' }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const saved = onSave.mock.calls[0][0] as WriterRelationship[];
    expect(saved[0]).toEqual({ from: '萧遥', to: '王衍', relation: '亦敌亦友', bidirectional: false });
    expect(saved[1]).toEqual(relationships[1]);
    await waitFor(() => expect(screen.getByRole('form', { name: '新增人物关系' })).toBeTruthy());
  });

  it('deletes a relationship and surfaces save failures', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn()
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error('人物关系保存失败，请确认后端服务可用后重试。'));
    render(<RelationshipEditor roles={roles} relationships={relationships} onSave={onSave} />);

    await user.click(screen.getByRole('button', { name: '删除 萧遥 与 王衍 的关系' }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith([relationships[1]]));

    await user.click(screen.getByRole('button', { name: '删除 萧遥 与 管家 的关系' }));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', '人物关系保存失败，请确认后端服务可用后重试。');
  });

  it('moves a person by dragging and zooms with the buttons and the wheel', () => {
    const originalCtm = (SVGElement.prototype as unknown as { getScreenCTM?: unknown }).getScreenCTM;
    const originalPoint = (globalThis as { DOMPoint?: unknown }).DOMPoint;
    // jsdom has no layout: the screen and the field share coordinates.
    (SVGElement.prototype as unknown as { getScreenCTM: () => unknown }).getScreenCTM = () => ({ inverse: () => ({}) });
    (globalThis as { DOMPoint?: unknown }).DOMPoint = class {
      x: number; y: number;
      constructor(x: number, y: number) { this.x = x; this.y = y; }
      matrixTransform() { return { x: this.x, y: this.y }; }
    };
    try {
      const { container } = render(<CharacterRelationshipGraph roles={roles} relationships={relationships} />);
      const svg = container.querySelector('svg.writer-relationship-graph') as SVGSVGElement;
      const node = container.querySelector('[data-node-name="王衍"]') as SVGGElement;
      const before = node.getAttribute('transform');
      const [x, y] = (before?.match(/translate\(([-\d.]+) ([-\d.]+)\)/) || []).slice(1).map(Number);
      fireEvent.pointerDown(node, { pointerId: 1, clientX: x, clientY: y, button: 0 });
      fireEvent.pointerMove(svg, { pointerId: 1, clientX: x + 40, clientY: y + 25 });
      fireEvent.pointerUp(svg, { pointerId: 1, clientX: x + 40, clientY: y + 25 });
      expect(container.querySelector('[data-node-name="王衍"]')?.getAttribute('transform')).toBe(`translate(${x + 40} ${y + 25})`);

      const viewBox = () => svg.getAttribute('viewBox');
      expect(viewBox()).toBe('0 0 680 400');
      fireEvent.click(screen.getByRole('button', { name: '放大' }));
      expect(viewBox()).toBe('68 40 544 320');
      fireEvent.wheel(container.querySelector('.writer-relationship-canvas') as Element, { deltaY: 200 });
      expect(Number(viewBox()?.split(' ')[2])).toBeGreaterThan(544);
      fireEvent.click(screen.getByRole('button', { name: '适应画布' }));
      expect(viewBox()).toBe('0 0 680 400');
      expect(container.querySelector('[data-node-name="王衍"]')?.getAttribute('transform')).toBe(before);
    } finally {
      (SVGElement.prototype as unknown as { getScreenCTM?: unknown }).getScreenCTM = originalCtm;
      (globalThis as { DOMPoint?: unknown }).DOMPoint = originalPoint;
    }
  });
});
