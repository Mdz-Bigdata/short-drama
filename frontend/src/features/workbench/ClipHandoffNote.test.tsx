// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ClipHandoffNote } from './ClipHandoffNote';
import type { HandoffReport } from './clipHandoffApi';

const REPORT: HandoffReport = {
  episode: 1, suspect: 1, summary: '1 处衔接可疑',
  pairs: [
    { from: { scene_id: 'E1S01', shot_id: 1, video_url: '/media/a.mp4' }, to: { scene_id: 'E1S01', shot_id: 2, video_url: '/media/b.mp4' },
      verdict: 'suspect', label: '可疑', tail: '结尾：向右，还在动，主体从画面右侧出画', head: '开头：向左，还在动，主体从画面右侧入画',
      findings: [{ code: 'exit_entry', text: '出画入画对不上：上一镜主体从画面右侧出画，这一镜又从画面右侧入画' }] },
    { from: { scene_id: 'E1S01', shot_id: 2, video_url: '/media/b.mp4' }, to: { scene_id: 'E1S01', shot_id: 3, video_url: '/media/c.mp4' },
      verdict: 'good', label: '接得上', tail: '结尾：看不出方向，画面停住', head: '开头：看不出方向，画面停住', findings: [] },
  ],
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('ClipHandoffNote', () => {
  it('shows the cut into and out of the selected shot', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, json: async () => REPORT } as Response);
    render(<ClipHandoffNote taskId="t1" sceneId="E1S01" shotId={2} videoUrl="/media/b.mp4" />);
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '查衔接' }));
    const section = await screen.findByRole('region', { name: '镜头衔接质检' });
    expect(String(fetch.mock.calls[0][0])).toContain('/api/drama/t1/episodes/1/handoff');
    const [into, out] = within(section).getAllByRole('listitem').filter(item => item.className.includes('clip-handoff__cut'));
    expect(into.textContent).toContain('接上一镜');
    expect(into.textContent).toContain('出画入画对不上');
    expect(into.className).toContain('is-suspect');
    expect(out.textContent).toContain('接下一镜');
    expect(out.textContent).toContain('接得上');
    expect(within(section).getByText(/本集：1 处衔接可疑/)).toBeTruthy();
  });

  it('says so for a shot with no neighbour, and shows nothing for a shot with no clip', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, json: async () => ({ ...REPORT, pairs: [] }) } as Response);
    render(<ClipHandoffNote taskId="t1" sceneId="E1S01" shotId={9} videoUrl="/media/z.mp4" />);
    fireEvent.click(screen.getByRole('button', { name: '查衔接' }));
    expect(await screen.findByText('这一镜前后没有能比的片段。')).toBeTruthy();
    cleanup();
    const nothing = render(<ClipHandoffNote taskId="t1" sceneId="E1S01" shotId={1} videoUrl="" />);
    expect(nothing.container.textContent).toBe('');
  });
});
