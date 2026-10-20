// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { StoryboardWorkspace, type StoryboardShot } from './StoryboardWorkspace';

vi.mock('../spatial/SpatialStageDialog', () => ({
  SpatialStageDialog: ({ taskId, sceneId, onClose, onRedrawRequested }: {
    taskId: string; sceneId: string; onClose: () => void; onRedrawRequested?: () => void;
  }) => (
    <div role="dialog" aria-label="空间调度">
      {taskId}/{sceneId}
      <button type="button" onClick={onRedrawRequested}>redraw</button>
      <button type="button" onClick={onClose}>close</button>
    </div>
  ),
}));

const shots: StoryboardShot[] = [
  { shot_id: 1, scene_id: 'E1S01', image_url: 'https://img.test/1.png', size: 'MS', motion: 'Static' },
  { shot_id: 1, scene_id: 'E1S02', image_url: 'https://img.test/2.png', size: 'CU', motion: 'Static' },
];

describe('StoryboardWorkspace spatial stage entry', () => {
  afterEach(cleanup);

  it('opens the spatial stage of the selected scene and refreshes the boards after a redraw', async () => {
    const onRefresh = vi.fn();
    render(<StoryboardWorkspace title="暗室回声" shots={shots} taskId="task-1" onRefresh={onRefresh} onRegenerate={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: '空间调度' }));
    expect(screen.getByRole('dialog', { name: '空间调度' }).textContent).toContain('task-1/E1S01');

    await userEvent.click(screen.getByRole('button', { name: 'redraw' }));
    expect(onRefresh).toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'close' }));
    expect(screen.queryByRole('dialog', { name: '空间调度' })).toBeNull();
  });

  it('marks every frame with the cut into it, keeping optical transitions in view', () => {
    const planned: StoryboardShot[] = [
      { ...shots[0], cut_in: { from_shot: 0, kind: 'fade', label: '淡入淡出·开场', compositor: 'dip_to_black' } },
      { shot_id: 2, scene_id: 'E1S01', image_url: 'https://img.test/3.png', cut_in: { from_shot: 1, kind: 'cut', label: '硬切·正反打' } },
      { shot_id: 3, scene_id: 'E1S01', image_url: 'https://img.test/4.png' },
    ];
    render(<StoryboardWorkspace title="暗室回声" shots={planned} taskId="task-1" onRefresh={vi.fn()} onRegenerate={vi.fn()} />);

    const opening = screen.getByTitle('切入本镜：淡入淡出·开场');
    expect(opening.textContent).toBe('淡入淡出·开场');
    expect(opening.className).toContain('is-optical');
    expect(screen.getByTitle('切入本镜：硬切·正反打').className).not.toContain('is-optical');
    expect(document.querySelectorAll('.storyboard-frame__cut')).toHaveLength(2);   // a legacy shot has no badge
  });

  it('needs a task to talk to', () => {
    render(<StoryboardWorkspace title="暗室回声" shots={shots} onRefresh={vi.fn()} onRegenerate={vi.fn()} />);
    expect(screen.getByRole('button', { name: '空间调度' })).toHaveProperty('disabled', true);
  });
});
