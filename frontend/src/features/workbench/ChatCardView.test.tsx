// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ChatCardView } from './ChatCardView';
import type { ChatCard } from './chatCards';

afterEach(cleanup);

const LONG = '鹅蛋脸，眉形平直，眼睛略小，鼻梁偏低，嘴唇薄，下颌线柔和，肤色偏白，额头饱满，颧骨不显，整体清秀温和，少女感。';

describe('ChatCardView', () => {
  it('face card: shows name, stale badge, collapsed descriptions, and hands the buttons back', async () => {
    const card: ChatCard = { kind: 'face_sculpt_changed', name: '林婉', before: LONG, after: '瓜子脸，丹凤眼', revision: 3, sheetStale: true, snapshotId: 'snap-9' };
    const onOpenCharacter = vi.fn();
    const onUndoFace = vi.fn();
    render(<ChatCardView card={card} busy={false} onSend={vi.fn()} onOpenCharacter={onOpenCharacter} onUndoFace={onUndoFace} />);

    expect(screen.getByText('捏脸已更新 · 林婉')).toBeTruthy();
    expect(screen.getByText('定妆照需重出')).toBeTruthy();
    expect(screen.getByText(LONG).classList.contains('is-collapsed')).toBe(true);
    await userEvent.click(screen.getByRole('button', { name: '展开' }));
    expect(screen.getByText(LONG).classList.contains('is-collapsed')).toBe(false);
    // 短描述不用折叠，也就没有展开按钮。
    expect(screen.getByText('瓜子脸，丹凤眼').classList.contains('is-collapsed')).toBe(false);
    expect(screen.getAllByRole('button', { name: /展开|收起/ })).toHaveLength(1);

    await userEvent.click(screen.getByRole('button', { name: '打开角色页' }));
    expect(onOpenCharacter).toHaveBeenCalledWith('林婉');
    await userEvent.click(screen.getByRole('button', { name: '撤销这一步' }));
    expect(onUndoFace).toHaveBeenCalledWith('林婉', 'snap-9');
  });

  it('face card: no undo button without a snapshot, no stale badge when the sheet still fits', () => {
    const card: ChatCard = { kind: 'face_sculpt_changed', name: '林婉', before: 'a', after: 'b', revision: 1, sheetStale: false };
    render(<ChatCardView card={card} busy={false} onSend={vi.fn()} onOpenCharacter={vi.fn()} onUndoFace={vi.fn()} />);
    expect(screen.queryByRole('button', { name: '撤销这一步' })).toBeNull();
    expect(screen.queryByText('定妆照需重出')).toBeNull();
  });

  it('stage card: summary, chips by group, failing checks, open and undo', async () => {
    const card: ChatCard = {
      kind: 'stage_changed', sceneId: 'E1S03', revision: 12, snapshotId: 'st-4', summary: '林婉挪到窗边', failingChecks: ['sightline'],
      changed: { actors: ['林婉'], pieces_added: ['花瓶'], pieces_changed: ['窗'], pieces_removed: ['椅子'], cameras: ['C2'] },
    };
    const onOpenStage = vi.fn();
    const onUndoStage = vi.fn();
    render(<ChatCardView card={card} busy={false} onSend={vi.fn()} onOpenStage={onOpenStage} onUndoStage={onUndoStage} />);

    expect(screen.getByText('舞台已改 · E1S03')).toBeTruthy();
    expect(screen.getByText('林婉挪到窗边')).toBeTruthy();
    expect(screen.getByText('人物')).toBeTruthy();
    expect(screen.getByText('布景')).toBeTruthy();
    expect(screen.getByText('机位')).toBeTruthy();
    expect(screen.getByText('+花瓶').classList.contains('is-added')).toBe(true);
    expect(screen.getByText('−椅子').classList.contains('is-removed')).toBe(true);
    expect(screen.getByText('未通过检查')).toBeTruthy();
    expect(screen.getByText('sightline')).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: '到导演台看这场' }));
    expect(onOpenStage).toHaveBeenCalledWith('E1S03');
    await userEvent.click(screen.getByRole('button', { name: '撤销这一步' }));
    expect(onUndoStage).toHaveBeenCalledWith('E1S03', 'st-4');
  });

  it('proposal card: confirm and cancel send the slash commands, busy disables both', async () => {
    const card: ChatCard = { kind: 'proposal', tool: 'regenerate_sheet', message: '要重出林婉的定妆照吗？', arguments: {} };
    const onSend = vi.fn();
    const { rerender } = render(<ChatCardView card={card} busy={false} onSend={onSend} />);

    expect(screen.getByText('要重出林婉的定妆照吗？')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: '确认执行' }));
    expect(onSend).toHaveBeenLastCalledWith('/confirm');
    await userEvent.click(screen.getByRole('button', { name: '放弃' }));
    expect(onSend).toHaveBeenLastCalledWith('/cancel');

    rerender(<ChatCardView card={card} busy onSend={onSend} />);
    expect((screen.getByRole('button', { name: '确认执行' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: '放弃' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('proposal card: the arguments being confirmed are shown in one line, without task_id or blanks', () => {
    const card: ChatCard = {
      kind: 'proposal', tool: 'optimize_scenes', message: '「批量优化多场」会调用付费模型',
      arguments: { task_id: 't1', scene_ids: ['E1S01', 'E1S02'], episode: 1, goal: '' },
    };
    render(<ChatCardView card={card} busy={false} onSend={vi.fn()} />);
    const line = screen.getByTitle('这次确认的参数');
    expect(line.textContent).toBe('scene_ids=E1S01、E1S02，episode=1');
    expect(line.textContent).not.toContain('t1');
  });

  it('busy disables the undo buttons but still lets the boards open', () => {
    const face: ChatCard = { kind: 'face_sculpt_changed', name: '林婉', before: 'a', after: 'b', revision: 1, sheetStale: false, snapshotId: 's' };
    render(<ChatCardView card={face} busy onSend={vi.fn()} onOpenCharacter={vi.fn()} onUndoFace={vi.fn()} />);
    expect((screen.getByRole('button', { name: '撤销这一步' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: '打开角色页' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('tool_calls card: one compact line, details list each call with its outcome', async () => {
    const card: ChatCard = { kind: 'tool_calls', calls: [{ tool: 'sculpt_face', ok: true }, { tool: 'move_actor', ok: false, error: '没这个人' }] };
    render(<ChatCardView card={card} busy={false} onSend={vi.fn()} />);

    expect(screen.getByText('调用了 2 个工具')).toBeTruthy();
    expect(screen.getByText('1 个失败')).toBeTruthy();
    await userEvent.click(screen.getByText('调用了 2 个工具'));
    expect(screen.getByText('sculpt_face')).toBeTruthy();
    expect(screen.getByText('成功')).toBeTruthy();
    expect(screen.getByText('没这个人')).toBeTruthy();
  });
});
