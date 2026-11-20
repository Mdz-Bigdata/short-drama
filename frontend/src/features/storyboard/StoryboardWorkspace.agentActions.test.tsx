// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { storyboardActionFrom, type StoryboardViewAction } from './storyboardActions';
import { StoryboardWorkspace, type StoryboardShot } from './StoryboardWorkspace';

vi.mock('../directorDesk/DirectorDesk', () => ({
  DirectorDesk: ({ sceneId, initialSideTab }: { sceneId: string; initialSideTab?: string }) => (
    <div role="dialog" aria-label="3D 导演台">{sceneId}:{initialSideTab}</div>
  ),
}));
vi.mock('../spatial/SpatialStageDialog', () => ({
  SpatialStageDialog: ({ sceneId }: { sceneId: string }) => <div role="dialog" aria-label="空间调度">{sceneId}</div>,
}));
vi.mock('./ExportDialog', () => ({
  ExportDialog: ({ kind, sceneId }: { kind: string; sceneId?: string }) => <div role="dialog" aria-label={`导出-${kind}`}>{sceneId}</div>,
}));

const shots: StoryboardShot[] = [
  { shot_id: 1, scene_id: 'E1S01', image_url: 'https://img.test/1.png', size: 'MS', motion: 'Static' },
  { shot_id: 2, scene_id: 'E1S02', image_url: 'https://img.test/2.png', size: 'CU', motion: 'Static' },
];

function workspace(action: StoryboardViewAction | null) {
  return <StoryboardWorkspace title="换命录" shots={shots} taskId="task-1" onRefresh={vi.fn()} onRegenerate={vi.fn()} externalAction={action} />;
}

describe('storyboardActionFrom', () => {
  it('takes the last view the agent opened in a turn', () => {
    const calls = [
      { tool: 'get_scene_board', result: { ok: true, result: { status: 'done' } } },
      { tool: 'open_storyboard_view', result: { ok: true, result: { ui_action: { type: 'storyboard_view', scene_id: 'E1S01', view: 'prompt' } } } },
      { tool: 'open_storyboard_view', result: { ok: true, result: { ui_action: { type: 'storyboard_view', scene_id: 'E1S02', view: 'desk' } } } },
    ];
    expect(storyboardActionFrom(calls, 7)).toEqual({ sceneId: 'E1S02', view: 'desk', nonce: 7 });
  });

  it('ignores failed calls, unknown views and anything that is not a list', () => {
    expect(storyboardActionFrom([{ tool: 'open_storyboard_view', result: { ok: false } }], 1)).toBeNull();
    expect(storyboardActionFrom([{ result: { ok: true, result: { ui_action: { type: 'storyboard_view', scene_id: 'E1S01', view: 'nuke' } } } }], 1)).toBeNull();
    expect(storyboardActionFrom(undefined, 1)).toBeNull();
  });
});

describe('StoryboardWorkspace opens what the agent asked for', () => {
  afterEach(cleanup);

  it('selects the scene and opens its prompt', () => {
    render(workspace({ sceneId: 'E1S02', view: 'prompt', nonce: 1 }));
    expect(screen.getByRole('heading', { name: 'E1S02 时序分镜' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /查看提示词/ }).getAttribute('aria-expanded')).toBe('true');
  });

  it('opens the spatial stage, the export dialogs and the desk', async () => {
    const { rerender } = render(workspace({ sceneId: 'E1S01', view: 'spatial', nonce: 1 }));
    expect((await screen.findByRole('dialog', { name: '空间调度' })).textContent).toBe('E1S01');
    rerender(workspace({ sceneId: 'E1S01', view: 'packages', nonce: 2 }));
    expect(await screen.findByRole('dialog', { name: '导出-packages' })).toBeTruthy();
    expect(screen.queryByRole('dialog', { name: '空间调度' })).toBeNull();
    rerender(workspace({ sceneId: 'E1S01', view: 'sheets', nonce: 3 }));
    expect(await screen.findByRole('dialog', { name: '导出-sheets' })).toBeTruthy();
    rerender(workspace({ sceneId: 'E1S02', view: 'blender', nonce: 4 }));
    expect((await screen.findByRole('dialog', { name: '3D 导演台' })).textContent).toBe('E1S02:blender');
  });

  it('keeps the secondary tools one click away under 「更多」', async () => {
    render(workspace(null));
    expect(screen.queryByRole('menuitem', { name: '提示词分包' })).toBeNull();

    await userEvent.click(screen.getByRole('button', { name: '更多' }));
    expect(screen.getAllByRole('menuitem').map(item => item.textContent?.trim())).toEqual(['360° 全景', '图片池', '提示词分包', '资产设定图']);
    await userEvent.click(screen.getByRole('menuitem', { name: '提示词分包' }));

    expect((await screen.findByRole('dialog', { name: '导出-packages' })).textContent).toBe('E1S01');
    expect(screen.queryByRole('menu')).toBeNull();
    // The whole-stage rerun stays in view: the spatial stage's redraw notice sends people to it by name.
    expect(screen.getByRole('button', { name: /重跑分镜阶段/ }).getAttribute('title')).toContain('已完成的分镜页会保留');
  });

  it('applies the same request only once and a repeated one again', async () => {
    const { rerender } = render(workspace({ sceneId: 'E1S01', view: 'desk', nonce: 5 }));
    expect((await screen.findByRole('dialog', { name: '3D 导演台' })).textContent).toBe('E1S01:inspector');
    rerender(workspace({ sceneId: 'E1S01', view: 'board', nonce: 5 }));
    expect(screen.getByRole('dialog', { name: '3D 导演台' })).toBeTruthy();
    rerender(workspace({ sceneId: 'E1S01', view: 'board', nonce: 6 }));
    expect(screen.queryByRole('dialog', { name: '3D 导演台' })).toBeNull();
  });
});
