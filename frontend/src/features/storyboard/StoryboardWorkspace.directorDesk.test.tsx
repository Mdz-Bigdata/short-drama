// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
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

  // First in the file on purpose: the desk chunk is only ever pending once.
  it('says the desk is loading while its chunk arrives', async () => {
    render(<StoryboardWorkspace title="暗室回声" shots={shots} taskId="task-1" onRefresh={vi.fn()} onRegenerate={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: '3D 导演台' }));
    expect(screen.getByRole('status').textContent).toContain('正在加载 3D 导演台');

    expect(await screen.findByRole('dialog', { name: '3D 导演台' })).toBeTruthy();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('keeps the two stage tools side by side, each saying what it is for, with the desk as the primary one', () => {
    render(<StoryboardWorkspace title="暗室回声" shots={shots} taskId="task-1" onRefresh={vi.fn()} onRegenerate={vi.fn()} />);

    const tools = screen.getByRole('group', { name: '场景调度' });
    const [spatial, desk] = within(tools).getAllByRole('button');
    expect(spatial.textContent).toContain('俯视图看站位');
    expect(spatial.getAttribute('title')).toContain('2D 俯视图');
    expect(spatial.className).not.toContain('storyboard-action--primary');
    expect(desk.textContent).toContain('摆人架机截图');
    expect(desk.getAttribute('title')).toContain('可编辑的 3D 场景');
    expect(desk.className).toContain('storyboard-action--primary');
  });

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
