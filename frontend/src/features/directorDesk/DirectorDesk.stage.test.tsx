// @vitest-environment jsdom
import { useEffect } from 'react';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PLAN, planResponse } from '../spatial/spatialFixtures';
import type { StagePlan } from '../spatial/spatialTypes';
import { DirectorDesk } from './DirectorDesk';
import type { ClipRequest } from './lib/clipExport';
import type { DeskViewportProps } from './three/DeskViewport';
import type { LensViewportProps } from './three/LensViewport';

// The stage batch of 2026-11-18 seen through the whole desk: the routes handed to the stage and
// listed in the outliner, the prompt bar over the stage, and 成片预演 written out as one video.

vi.mock('./three/DeskViewport', () => ({
  default: function MockDeskViewport({ trails, time }: DeskViewportProps) {
    return (
      <div data-testid="desk-viewport" data-time={time}>
        {trails?.map(trail => <span key={trail.key} data-testid={`trail-${trail.key}`}>{trail.keys.map(key => key.time).join(',')}</span>)}
      </div>
    );
  },
}));

// A lens that answers the way the real one does: ready once mounted, and each stamp acknowledged
// once the frame it names is the one on show.
const shown: Array<{ shot: number | undefined; camera: string | undefined }> = [];
vi.mock('./three/LensViewport', () => ({
  default: function MockLensViewport({ shot, camera, onReady, frameStamp, onFrameShown }: LensViewportProps) {
    useEffect(() => {
      onReady?.({ capture: () => Promise.reject(new Error('not in this test')), renderer: () => ({ gl: {}, scene: {}, camera: {}, depthRange: { near: 0, far: 1 } }) as never });
      return () => onReady?.(null);
    }, [onReady]);
    useEffect(() => {
      if (frameStamp === undefined) return;
      shown.push({ shot: shot?.shot_id, camera: camera?.id });
      onFrameShown?.(frameStamp, { labels: [], figures: [] });
    }, [camera?.id, frameStamp, onFrameShown, shot?.shot_id]);
    return <span data-testid="lens-camera">{camera?.id}</span>;
  },
}));

const exported: ClipRequest[] = [];
const exportClip = vi.fn(async (request: ClipRequest) => {
  exported.push(request);
  try {
    // A frame in the first shot, one in the second, and the first again: the stage has to follow each way.
    for (const time of [0, 1.5, 0.5]) {
      if (request.signal?.aborted) throw new DOMException('已取消导出', 'AbortError');
      await request.stage.showFrame(time);
      request.onProgress?.(0.5);
    }
    return { blob: new Blob(['x'], { type: 'video/mp4' }), format: 'mp4' as const, width: 720, height: 1280, durationS: request.durationS, fps: request.fps, frames: 3, showsLimbs: false };
  } finally {
    request.stage.release();
  }
});
vi.mock('./lib/clipExport', () => ({
  exportClip: (request: ClipRequest) => exportClip(request),
  SCENE_CLIP_LIMITS: { seconds: 600, bytes: 400 * 1024 * 1024 },
}));

vi.mock('./elementLibraryApi', () => ({
  listModelElements: vi.fn(() => Promise.resolve([])),
  importModelElement: vi.fn(),
  modelRefusal: vi.fn(() => ''),
}));

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

describe('DirectorDesk stage batch', () => {
  const fetchMock = vi.fn();
  let stage: StagePlan;
  const chats: Array<Record<string, unknown>> = [];
  const saved: string[] = [];

  beforeEach(() => {
    stage = {
      ...PLAN,
      timelines: {
        1: {
          duration_s: 1, fps: 24,
          camera: [
            { time: 0, position: [0, 1.5, 5], target: [0, 1, 0], lens_mm: 28, easing: 'linear' },
            { time: 1, position: [0, 1.5, 2], target: [0, 1, 0], lens_mm: 28, easing: 'linear' },
          ],
          actors: { 林夏: [{ time: 0, position: [-1.3, 0], easing: 'linear' }, { time: 0.5, position: [0, 0], easing: 'linear' }, { time: 1, position: [0, 1], easing: 'linear' }] },
        },
        2: { duration_s: 2, fps: 24, camera: [], actors: {} },
      },
    };
    window.localStorage.clear();
    window.innerHeight = 900;
    shown.length = 0;
    exported.length = 0;
    chats.length = 0;
    saved.length = 0;
    exportClip.mockClear();
    fetchMock.mockReset();
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/director/chat')) {
        chats.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        return json({ message: { role: 'assistant', text: '林夏往窗边挪了一步' }, changed: true, measured: { score: 80, errors: 0, warnings: 0, failing: [], notes: [] }, failing: [] });
      }
      if (url.endsWith('/director')) return json({ chat: [], snapshots: [], candidates: [], measured: { score: 80, errors: 0, warnings: 0, failing: [], notes: [] }, planner: 'rules', planner_note: '', pipeline_planner: 'model' });
      if (url.endsWith('/director-desk/kits')) return json({ kits: [] });
      if (url.includes('/director-desk/') || url.includes('/repairs')) return json({ captures: [], applied: {}, repairs: [], operations: [], revision: stage.revision });
      return json(planResponse({}, stage));
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:scene'), revokeObjectURL: vi.fn() }));
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click(this: HTMLAnchorElement) { saved.push(this.download); });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('hands the shot’s routes to the stage and lists them, each picking whoever travels it', async () => {
    render(<DirectorDesk taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    await screen.findByTestId('desk-viewport');
    expect(screen.getByTestId('trail-camera:cam-01').textContent).toBe('0,1');
    expect(screen.getByTestId('trail-actor:林夏').textContent).toBe('0,0.5,1');

    const routes = within(screen.getByRole('complementary', { name: '场景大纲' })).getByRole('region', { name: '轨迹' });
    expect(within(routes).getByText('3 个关键帧 · 2.3 米 · 1 秒')).toBeTruthy();
    expect(within(routes).getByText('2 个关键帧 · 3.0 米 · 1 秒')).toBeTruthy();
    await userEvent.click(within(routes).getByRole('button', { name: /走位 · 林夏/ }));
    expect(within(routes).getByRole('button', { name: /走位 · 林夏/ }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText('已选：林夏')).toBeTruthy();

    // The second shot has no keys of its own: nobody walks, and its lens still has the push the planner gave it.
    await userEvent.selectOptions(screen.getByRole('combobox', { name: '镜头' }), '2');
    expect(screen.queryByTestId('trail-actor:林夏')).toBeNull();
    expect(screen.getByTestId('trail-camera:cam-02').textContent).toBe('0,2');
    expect(within(screen.getByRole('region', { name: '轨迹' })).getAllByRole('listitem')).toHaveLength(1);
  });

  it('takes a one-line request over the stage for what is picked, and reads the stage again', async () => {
    render(<DirectorDesk taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    await screen.findByTestId('desk-viewport');
    await userEvent.click(within(screen.getByRole('region', { name: '轨迹' })).getByRole('button', { name: /走位 · 林夏/ }));
    const bar = screen.getByRole('region', { name: '对 AI 导演说' });
    expect(within(bar).getByTitle('只改「林夏」')).toBeTruthy();
    const reads = fetchMock.mock.calls.length;
    await userEvent.type(within(bar).getByLabelText('想怎么改'), '往窗边走一步{Enter}');
    expect((await within(bar).findByRole('status')).textContent).toContain('林夏往窗边挪了一步');
    expect(chats).toEqual([{ base_revision: stage.revision, message: '往窗边走一步', names: ['林夏'], shot_id: null }]);
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(reads + 1));
    // The whole conversation is one click away.
    await userEvent.click(within(bar).getByRole('button', { name: '打开完整对话' }));
    expect(screen.getByRole('tab', { name: 'AI 导演' }).getAttribute('aria-selected')).toBe('true');
  });

  it('writes 成片预演 out as one video, walking every shot through its own lens, and goes back to where it was', async () => {
    render(<DirectorDesk taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    await screen.findByTestId('desk-viewport');
    await userEvent.click(screen.getByRole('radio', { name: /成片预演/ }));
    const player = screen.getByRole('region', { name: '成片预演播放' });
    await userEvent.click(await within(player).findByRole('button', { name: /导出成片预演/ }));
    await waitFor(() => expect(saved).toEqual(['E1S01-成片预演.mp4']));

    // The scene is 1 s + 2 s; the frames asked for fell in shot 1, shot 2 and shot 1 again.
    expect(exported[0]).toMatchObject({ durationS: 3, fps: 24, monochrome: false, labels: false, limits: { seconds: 600 } });
    expect(shown).toEqual([{ shot: 1, camera: 'cam-01' }, { shot: 2, camera: 'cam-02' }, { shot: 1, camera: 'cam-01' }]);
    expect((await screen.findByText(/已导出本场成片预演（3.0 秒/)).closest('[role="status"]')).toBeTruthy();
    expect((screen.getByRole('combobox', { name: '镜头' }) as HTMLSelectElement).value).toBe('1');
    // The transport is back, and nothing is left exporting.
    expect(within(player).getByRole('button', { name: /导出成片预演/ })).toBeTruthy();
    expect(within(player).queryByRole('group', { name: '成片预演导出进度' })).toBeNull();
  });

  it('says why a scene cannot be exported while a shot has no lens', async () => {
    stage = { ...stage, shots: stage.shots.map((shot, index) => (index === 1 ? { ...shot, camera_id: 'gone' } : shot)) };
    render(<DirectorDesk taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    await screen.findByTestId('desk-viewport');
    await userEvent.click(screen.getByRole('radio', { name: /成片预演/ }));
    const button = await screen.findByRole('button', { name: /导出成片预演/ }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.title).toContain('第 2 镜还没有机位');
    expect(exportClip).not.toHaveBeenCalled();
  });

  it('watches at the chosen speed in both modes', async () => {
    render(<DirectorDesk taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    await screen.findByTestId('desk-viewport');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: '播放速度' }), '2');
    await userEvent.click(screen.getByRole('radio', { name: /成片预演/ }));
    // One playhead: the speed picked on the timeline is the speed the scene plays at.
    expect((screen.getByRole('combobox', { name: '播放速度' }) as HTMLSelectElement).value).toBe('2');
  });
});
