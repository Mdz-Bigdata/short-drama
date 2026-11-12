import { describe, expect, it } from 'vitest';

import { chatCardsFrom } from './chatCards';

describe('chatCardsFrom', () => {
  it('tolerates garbage: nothing, strings, broken entries', () => {
    expect(chatCardsFrom(undefined, undefined)).toEqual([]);
    expect(chatCardsFrom(null, null)).toEqual([]);
    expect(chatCardsFrom('nope', 42)).toEqual([]);
    expect(chatCardsFrom({ tool: 'x' }, [])).toEqual([]);
    expect(chatCardsFrom([null, 'x', 7, {}], { tool: 'only_tool' })).toEqual([
      { kind: 'tool_calls', calls: [{ tool: '?', ok: true }] },
    ]);
  });

  it('makes one face card per successful face_sculpt_changed event', () => {
    const calls = [
      { tool: 'sculpt_face', arguments: { name: '林婉' }, result: { ok: true, result: {
        ui_action: { type: 'face_sculpt_changed', name: '林婉', before: '鹅蛋脸', after: '瓜子脸，丹凤眼', revision: 3, sheet_stale: true, snapshot_id: 'snap-9' },
      } } },
      { tool: 'sculpt_face', arguments: {}, result: { ok: false, error: '没这个人', result: {
        ui_action: { type: 'face_sculpt_changed', name: '无名', before: '', after: '', revision: 1, sheet_stale: false },
      } } },
    ];
    const cards = chatCardsFrom(calls, null);
    expect(cards).toEqual([
      { kind: 'face_sculpt_changed', name: '林婉', before: '鹅蛋脸', after: '瓜子脸，丹凤眼', revision: 3, sheetStale: true, snapshotId: 'snap-9' },
      { kind: 'tool_calls', calls: [{ tool: 'sculpt_face', ok: true }, { tool: 'sculpt_face', ok: false, error: '没这个人' }] },
    ]);
  });

  it('makes a stage card with the change lists and failing checks', () => {
    const calls = [
      { tool: 'move_actor', arguments: {}, result: { ok: true, result: { ui_action: {
        type: 'stage_changed', scene_id: 'E1S03', revision: 12, snapshot_id: null, summary: '林婉挪到窗边',
        failing_checks: ['sightline', 7, ''],
        changed: { actors: ['林婉'], pieces_added: [], pieces_changed: ['窗'], pieces_removed: ['椅子'], cameras: ['C2'] },
      } } } },
    ];
    expect(chatCardsFrom(calls, undefined)[0]).toEqual({
      kind: 'stage_changed', sceneId: 'E1S03', revision: 12, summary: '林婉挪到窗边', failingChecks: ['sightline'],
      changed: { actors: ['林婉'], pieces_added: [], pieces_changed: ['窗'], pieces_removed: ['椅子'], cameras: ['C2'] },
    });
    // 什么都没改的 changed 不带上；缺 scene_id 的事件不成卡。
    const bare = chatCardsFrom([
      { tool: 'noop', result: { ok: true, result: { ui_action: { type: 'stage_changed', scene_id: 'E1S01', revision: 1, summary: '', changed: { actors: [] } } } } },
      { tool: 'noop', result: { ok: true, result: { ui_action: { type: 'stage_changed', revision: 1 } } } },
    ], undefined);
    expect(bare[0]).toEqual({ kind: 'stage_changed', sceneId: 'E1S01', revision: 1, summary: '', failingChecks: [] });
    expect(bare).toHaveLength(2);
    expect(bare[1].kind).toBe('tool_calls');
  });

  it('leaves storyboard views to storyboardActions and ignores unknown events', () => {
    const calls = [
      { tool: 'open_storyboard_view', result: { ok: true, result: { ui_action: { type: 'storyboard_view', scene_id: 'E1S01', view: 'desk' } } } },
      { tool: 'other', result: { ok: true, result: { ui_action: { type: 'something_else' } } } },
    ];
    expect(chatCardsFrom(calls, undefined)).toEqual([
      { kind: 'tool_calls', calls: [{ tool: 'open_storyboard_view', ok: true }, { tool: 'other', ok: true }] },
    ]);
  });

  it('adds a proposal card when the proposal names a tool and a message', () => {
    const proposal = { tool: 'regenerate_sheet', arguments: { name: '林婉' }, message: '要重出林婉的定妆照吗？' };
    expect(chatCardsFrom([], proposal)).toEqual([
      { kind: 'proposal', tool: 'regenerate_sheet', message: '要重出林婉的定妆照吗？', arguments: { name: '林婉' } },
    ]);
    expect(chatCardsFrom([], { tool: 'x' })).toEqual([]);
    expect(chatCardsFrom([], { message: 'x' })).toEqual([]);
    expect(chatCardsFrom([], { tool: 'x', message: 'y', arguments: 'bad' })).toEqual([
      { kind: 'proposal', tool: 'x', message: 'y', arguments: {} },
    ]);
  });

  it('summarises tool names and failures, treating a result without ok or error as success', () => {
    const calls = [
      { tool: 'a', result: { result: { done: true } } },
      { tool: 'b', result: { error: '超时' } },
      { tool: 'c', result: { ok: false } },
      { tool: 'd' },
    ];
    expect(chatCardsFrom(calls, undefined)).toEqual([
      { kind: 'tool_calls', calls: [
        { tool: 'a', ok: true }, { tool: 'b', ok: false, error: '超时' }, { tool: 'c', ok: false }, { tool: 'd', ok: true },
      ] },
    ]);
  });
});
