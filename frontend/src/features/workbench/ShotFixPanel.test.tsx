// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { DraftModeToggle, ShotFixPanel } from './ShotFixPanel';
import type { ShotVisualRecord } from './shotVisual';

const shot = (extra: Record<string, unknown> = {}) => ({
  shot_id: 2, scene_id: 'E1S03', desc: '断水抬刀', dialogue: '', sound: '',
  settings: { camera_motion: 'Static', shot_type: 'Close-up', duration_seconds: 6, action: '', ambiance_audio: '', lighting: '', ambiance: '' },
  settings_source: 'derived', derived_notes: [], image_url: '/media/p.png', video_url: '/media/c.mp4', candidate_urls: ['/media/c.mp4'],
  image_prompt: '', video_prompt: '', contract_fingerprint: 'x', route: null, stale: false, stale_reason: '',
  ...extra,
}) as unknown as ShotVisualRecord;

function stubFetch() {
  const calls: Array<{ url: string; method?: string; body?: unknown }> = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    calls.push({ url: String(input), method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    return { ok: true, json: async () => ({ shots: [] }) } as Response;
  });
  return calls;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('ShotFixPanel', () => {
  it('turns a 480P draft into HD either by local upscaling or by a full-size redo', async () => {
    const calls = stubFetch();
    const onWorkspace = vi.fn();
    const onNotice = vi.fn();
    const user = userEvent.setup();
    render(<ShotFixPanel taskId="t1" shot={{ ...shot(), draft_resolution: '480p' } as never} repairSupported={false} locked={false}
      onWorkspace={onWorkspace} onNotice={onNotice} onError={vi.fn()} />);

    expect(screen.getByText(/样片 480P/)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '本地放大' }));
    await user.click(screen.getByRole('button', { name: '重出高清' }));
    expect(calls.map(call => [call.url, call.body])).toEqual([
      ['/api/drama/t1/shots/2/hd?scene_id=E1S03', { mode: 'upscale' }],
      ['/api/drama/t1/shots/2/hd?scene_id=E1S03', { mode: 'regenerate' }],
    ].map(([url, body]) => [expect.stringContaining(url as string), body]));
    expect(onWorkspace).toHaveBeenCalledTimes(2);
    expect(onNotice).toHaveBeenCalled();
  });

  it('marks a retake from a second with what to fix, and needs a second first', async () => {
    const calls = stubFetch();
    const user = userEvent.setup();
    render(<ShotFixPanel taskId="t1" shot={shot()} repairSupported={false} locked={false}
      onWorkspace={vi.fn()} onNotice={vi.fn()} onError={vi.fn()} />);

    const button = screen.getByRole('button', { name: '从这里重做' }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    await user.type(screen.getByLabelText('从第几秒往后重做'), '3.5');
    await user.type(screen.getByLabelText('重做要改掉的问题'), '刀从左手穿过去了');
    await user.click(button);
    expect(calls[0].url).toContain('/shots/2/retake?scene_id=E1S03');
    expect(calls[0].body).toEqual({ from_seconds: 3.5, note: '刀从左手穿过去了' });
    expect(screen.queryByRole('button', { name: '区域修补' })).toBeNull();
  });

  it('sends the picked region of the frame for a repair and shows a failed one', async () => {
    const calls = stubFetch();
    const user = userEvent.setup();
    render(<ShotFixPanel taskId="t1" shot={{ ...shot(), repair: { status: 'failed', error: '模型拒单' } } as never} repairSupported locked={false}
      onWorkspace={vi.fn()} onNotice={vi.fn()} onError={vi.fn()} />);

    expect(screen.getByRole('alert').textContent).toContain('模型拒单');
    await user.click(screen.getByRole('button', { name: '区域修补' }));
    await user.click(screen.getByRole('radio', { name: '左下' }));
    await user.type(screen.getByLabelText('这一块要怎么改'), '去掉门口多出来的人');
    await user.type(screen.getByLabelText('修补开始秒数'), '2');
    await user.type(screen.getByLabelText('修补结束秒数'), '5');
    await user.click(screen.getByRole('button', { name: '开始修补' }));
    const body = calls[0].body as { box: { x: number; y: number }; note: string; start: number; end: number };
    expect(calls[0].url).toContain('/shots/2/repair?scene_id=E1S03');
    expect([body.box.x, body.box.y, body.note, body.start, body.end]).toEqual([0, 2 / 3, '去掉门口多出来的人', 2, 5]);
  });

  it('switches draft mode for the project', async () => {
    const calls = stubFetch();
    const user = userEvent.setup();
    render(<DraftModeToggle taskId="t1" enabled={false} locked={false} onWorkspace={vi.fn()} onError={vi.fn()} />);
    await user.click(screen.getByLabelText('样片模式（480P）'));
    expect([calls[0].url, calls[0].method, calls[0].body]).toEqual([expect.stringContaining('/api/drama/t1/shots/draft-mode'), 'PUT', { enabled: true }]);
  });
});
