// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CharacterRelationshipGraph } from './CharacterRelationshipGraph';
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

describe('CharacterRelationshipGraph editing', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('keeps the read-only layout when no save handler is provided', () => {
    render(<CharacterRelationshipGraph roles={roles} relationships={relationships} />);

    expect(screen.queryByRole('button', { name: /新增关系/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /删除/ })).toBeNull();
  });

  it('adds a new relationship through the editor form', async () => {
    const user = userEvent.setup();
    const onSaveRelationships = vi.fn().mockResolvedValue(undefined);
    render(
      <CharacterRelationshipGraph
        roles={roles}
        relationships={relationships}
        onSaveRelationships={onSaveRelationships}
      />,
    );

    await user.click(screen.getByRole('button', { name: /新增关系/ }));
    const form = screen.getByRole('form', { name: '新增人物关系' });
    const inputs = within(form).getAllByPlaceholderText('角色名');
    await user.type(inputs[0], '王衍');
    await user.type(inputs[1], '管家');
    await user.type(within(form).getByPlaceholderText('如：师徒 / 对立 / 盟友'), '主仆');
    await user.click(within(form).getByRole('checkbox'));
    await user.click(within(form).getByRole('button', { name: '添加' }));

    await waitFor(() => expect(onSaveRelationships).toHaveBeenCalledTimes(1));
    expect(onSaveRelationships).toHaveBeenCalledWith([
      ...relationships,
      { from: '王衍', to: '管家', relation: '主仆', bidirectional: true },
    ]);
  });

  it('rejects a relationship whose two ends are the same character', async () => {
    const user = userEvent.setup();
    const onSaveRelationships = vi.fn().mockResolvedValue(undefined);
    render(
      <CharacterRelationshipGraph
        roles={roles}
        relationships={relationships}
        onSaveRelationships={onSaveRelationships}
      />,
    );

    await user.click(screen.getByRole('button', { name: /新增关系/ }));
    const form = screen.getByRole('form', { name: '新增人物关系' });
    const inputs = within(form).getAllByPlaceholderText('角色名');
    await user.type(inputs[0], '萧遥');
    await user.type(inputs[1], '萧遥');
    await user.click(within(form).getByRole('button', { name: '添加' }));

    expect(screen.getByRole('alert').textContent).toContain('不能是同一个角色');
    expect(onSaveRelationships).not.toHaveBeenCalled();
  });

  it('edits an existing relationship in place', async () => {
    const user = userEvent.setup();
    const onSaveRelationships = vi.fn().mockResolvedValue(undefined);
    render(
      <CharacterRelationshipGraph
        roles={roles}
        relationships={relationships}
        onSaveRelationships={onSaveRelationships}
      />,
    );

    await user.click(screen.getByRole('button', { name: '编辑 萧遥 与 王衍 的关系' }));
    const form = screen.getByRole('form', { name: '编辑人物关系' });
    const relationInput = within(form).getByPlaceholderText('如：师徒 / 对立 / 盟友');
    await user.clear(relationInput);
    await user.type(relationInput, '亦敌亦友');
    await user.click(within(form).getByRole('button', { name: '保存修改' }));

    await waitFor(() => expect(onSaveRelationships).toHaveBeenCalledTimes(1));
    const saved = onSaveRelationships.mock.calls[0][0] as WriterRelationship[];
    expect(saved).toHaveLength(2);
    expect(saved[0]).toEqual({ from: '萧遥', to: '王衍', relation: '亦敌亦友', bidirectional: false });
    expect(saved[1]).toEqual(relationships[1]);
  });

  it('deletes a relationship and surfaces save failures', async () => {
    const user = userEvent.setup();
    const onSaveRelationships = vi.fn()
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error('人物关系保存失败，请确认后端服务可用后重试。'));
    render(
      <CharacterRelationshipGraph
        roles={roles}
        relationships={relationships}
        onSaveRelationships={onSaveRelationships}
      />,
    );

    await user.click(screen.getByRole('button', { name: '删除 萧遥 与 王衍 的关系' }));
    await waitFor(() => expect(onSaveRelationships).toHaveBeenCalledTimes(1));
    expect(onSaveRelationships).toHaveBeenCalledWith([relationships[1]]);

    await user.click(screen.getByRole('button', { name: '删除 萧遥 与 管家 的关系' }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toContain('人物关系保存失败');
  });
});
