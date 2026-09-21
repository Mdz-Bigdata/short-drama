// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { StoryboardWorkspace, type StoryboardShot } from './StoryboardWorkspace';

vi.mock('../directorDesk/DirectorDesk', () => ({
  DirectorDesk: ({ taskId, sceneId, onClose }: { taskId: string; sceneId: string; onClose: () => void }) => (
    <div role="dialog" aria-label="3D 导演台">
      {taskId}/{sceneId}
      <button type="button" onClick={onClose}>close desk</button>
    </div>
  ),
}));

const shots: StoryboardShot[] = [
  { shot_id: 1, scene_id: 'E1S01', image_url: 'https://img.test/1.png', size: 'MS', motion: 'Static' },
];

describe('StoryboardWorkspace director desk entry', () => {
  afterEach(cleanup);

  it('opens the desk on the selected scene, beside the spatial stage, and refreshes the boards on the way out', async () => {
    const onRefresh = vi.fn();
    render(<StoryboardWorkspace title="暗室回声" shots={shots} taskId="task-1" onRefresh={onRefresh} onRegenerate={vi.fn()} />);

    expect(screen.getByRole('button', { name: '空间调度' })).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: '3D 导演台' }));
    expect((await screen.findByRole('dialog', { name: '3D 导演台' })).textContent).toContain('task-1/E1S01');

    // A still applied in the desk changes what stage 5 reads, so the workspace reads again.
    await userEvent.click(screen.getByRole('button', { name: 'close desk' }));
    expect(screen.queryByRole('dialog', { name: '3D 导演台' })).toBeNull();
    expect(onRefresh).toHaveBeenCalled();
  });

  it('needs a task to talk to', () => {
    render(<StoryboardWorkspace title="暗室回声" shots={shots} onRefresh={vi.fn()} onRegenerate={vi.fn()} />);
    expect(screen.getByRole('button', { name: '3D 导演台' })).toHaveProperty('disabled', true);
  });
});
