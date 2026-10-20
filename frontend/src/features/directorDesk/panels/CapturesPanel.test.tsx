// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { LensHandle } from '../deskTypes';
import type { ClipRequest, ClipStage } from '../lib/clipExport';
import { CapturesPanel } from './CapturesPanel';

// The frame loop and the encoder have their own tests; here the panel only has to drive them and hand the file on.
const clipExport = vi.hoisted(() => ({ exportClip: vi.fn() }));
vi.mock('../lib/clipExport', () => clipExport);

const BASE = '/api/drama/t1/director-desk/scenes/E1S01/captures';
const OLD = {
  id: 'cap-old', kind: 'still', shotId: 1, cameraId: 'cam-01', url: 'http://localhost:8000/files/cap-old.png', width: 1080, height: 1920,
  durationS: 0, fps: 0, planRevision: 2, showsLimbs: false, monochrome: false, labelled: false, createdAt: '2026-09-18T10:00:00Z', stale: true,
};
// The record as it is stored: snake_case. The panel must read either spelling.
const NEW = {
  id: 'cap-new', kind: 'still', shot_id: 2, camera_id: 'cam-02', url: 'http://localhost:8000/files/cap-new.png', width: 1080, height: 1920,
  plan_revision: 3, monochrome: true, labelled: true, created_at: '2026-09-19T10:00:00Z', stale: false,
};

// The server's sentences, as the panel must show them.
const DEPTH_WARNING = '深度画面：近亮远暗的灰度图，只约束空间层次、走位与运镜，不约束颜色与材质';
const DEPTH_STILL_REFUSAL = '深度静帧不能作为首帧参考图应用到分镜；请导出深度视频作为运动参考，或截取普通静帧';

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

describe('CapturesPanel', () => {
  const fetchMock = vi.fn();
  let state: { captures: unknown[]; applied: Record<string, { still: string | null; clip: string | null }> };
  const calls = () => fetchMock.mock.calls.map(call => ({ url: String(call[0]), method: (call[1] as RequestInit | undefined)?.method || 'GET', body: (call[1] as RequestInit | undefined)?.body }));
  const capture = vi.fn(() => Promise.resolve({ blob: new Blob(['png'], { type: 'image/png' }), width: 1080, height: 1920, showsLimbs: false }));
  const renderer = () => ({}) as ReturnType<LensHandle['renderer']>;
  const release = vi.fn();
  const getClipStage = vi.fn((): ClipStage | null => ({ ...renderer(), showFrame: () => Promise.resolve({ labels: [], figures: [] }), release }));
  const panel = (props: Partial<Parameters<typeof CapturesPanel>[0]> = {}) => (
    <CapturesPanel taskId="t1" sceneId="E1S01" shotId={2} camera={PLAN.cameras[1]} cameras={PLAN.cameras} planRevision={3} saving={false} getLens={() => ({ capture, renderer })}
      aspect={9 / 16} durationS={4} fps={24} getClipStage={getClipStage} {...props}
    />
  );

  beforeEach(() => {
    state = { captures: [OLD, NEW], applied: {} };
    capture.mockClear();
    getClipStage.mockClear();
    clipExport.exportClip.mockReset();
    clipExport.exportClip.mockImplementation(async (request: ClipRequest) => {
      request.onProgress?.(0.5);
      return { blob: new Blob(['mp4'], { type: 'video/mp4' }), format: 'mp4', width: 720, height: 1280, durationS: 4, fps: 24, frames: 96, showsLimbs: true };
    });
    fetchMock.mockReset();
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method || 'GET';
      if (url.endsWith('/cap-new/apply')) state.applied = { 2: { still: 'cap-new', clip: null } };
      if (url.endsWith('/cap-new/unapply')) state.applied = {};
      if (method === 'DELETE') state.captures = state.captures.filter(item => (item as { id: string }).id !== url.split('/').pop());
      if (url.endsWith('/cap-clip/apply')) state.applied = { 2: { still: null, clip: 'cap-clip' } };
      if (method === 'POST' && url.endsWith('/captures') && (init?.body as FormData).get('kind') === 'clip') {
        const form = init?.body as FormData;
        const made = {
          id: 'cap-clip', kind: 'clip', shot_id: 2, camera_id: 'cam-02', url: 'http://localhost:8000/files/desk_clip.mp4', width: 720, height: 1280,
          duration_s: Number(form.get('duration_s')), fps: Number(form.get('fps')), plan_revision: 3, shows_limbs: form.get('shows_limbs') === 'true',
          monochrome: form.get('monochrome') === 'true', labelled: false, depth: form.get('depth') === 'true', created_at: '2026-09-20T11:00:00Z', stale: false,
          warning: form.get('depth') === 'true' ? DEPTH_WARNING : form.get('shows_limbs') === 'true' ? '白模带四肢：请在动作描述里写清分段肢体动作，否则四肢容易僵化' : '',
        };
        state.captures = [...state.captures, made];
        return json(made);
      }
      if (method === 'POST' && url.endsWith('/captures')) {
        const limbs = (init?.body as FormData).get('shows_limbs') === 'true';
        const depth = (init?.body as FormData).get('depth') === 'true';
        const made = {
          ...NEW, id: 'cap-made', created_at: '2026-09-20T10:00:00Z', monochrome: false, labelled: false, shows_limbs: limbs, depth,
          warning: depth ? DEPTH_WARNING : limbs ? '白模带四肢：请在动作描述里写清分段肢体动作，否则四肢容易僵化' : '',
        };
        state.captures = [...state.captures, made];
        return json(made);
      }
      return json({ taskId: 't1', sceneId: 'E1S01', ...state });
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('lists captures newest first with camera, revision and the stale badge', async () => {
    render(panel());
    const items = await screen.findAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText('第 2 镜 · 02 单人')).toBeTruthy();
    expect(within(items[0]).getByText(/第 3 版 · 1080×1920/)).toBeTruthy();
    expect(within(items[0]).getByText('白模色')).toBeTruthy();
    expect(within(items[0]).queryByText('过期')).toBeNull();
    expect(within(items[1]).getByText('过期')).toBeTruthy();
    // A still taken of an older blocking cannot be handed to generation.
    expect(within(items[1]).getByRole('button', { name: /应用至分镜/ })).toHaveProperty('disabled', true);
    expect(calls()[0]).toMatchObject({ url: `http://localhost:8000${BASE}`, method: 'GET' });
  });

  it('applies a still to its shot and takes it back', async () => {
    render(panel());
    await userEvent.click(await screen.findByRole('button', { name: '应用至分镜 第 2 镜 · 02 单人' }));
    expect(await screen.findByText('已应用')).toBeTruthy();
    expect(calls().some(call => call.method === 'POST' && call.url.endsWith(`${BASE}/cap-new/apply`))).toBe(true);

    await userEvent.click(screen.getByRole('button', { name: '取消应用 第 2 镜 · 02 单人' }));
    await waitFor(() => expect(screen.queryByText('已应用')).toBeNull());
    expect(calls().some(call => call.method === 'POST' && call.url.endsWith(`${BASE}/cap-new/unapply`))).toBe(true);
  });

  it('captures through the lens with the chosen options and uploads multipart', async () => {
    render(panel());
    await screen.findAllByRole('listitem');
    await userEvent.click(screen.getByLabelText('统一白模色'));
    await userEvent.click(screen.getByLabelText('烧入角色名'));
    await userEvent.click(screen.getByRole('button', { name: /截取第 2 镜画面/ }));

    expect(await screen.findByText('已截图并保存到截图库。')).toBeTruthy();
    expect(capture).toHaveBeenCalledWith({ monochrome: true, labels: true, depth: false });
    const upload = calls().find(call => call.method === 'POST' && call.url.endsWith(BASE));
    const form = upload?.body as FormData;
    expect(form).toBeInstanceOf(FormData);
    expect(Object.fromEntries([...form.entries()].filter(([key]) => key !== 'file'))).toEqual({
      kind: 'still', shot_id: '2', camera_id: 'cam-02', width: '1080', height: '1920', plan_revision: '3',
      shows_limbs: 'false', monochrome: 'true', labelled: 'true', depth: 'false',
    });
    expect(form.get('file')).toBeInstanceOf(Blob);
    expect(await screen.findAllByRole('listitem')).toHaveLength(3);
  });

  it('flags a still that shows a limbed white model and warns about it', async () => {
    capture.mockImplementationOnce(() => Promise.resolve({ blob: new Blob(['png'], { type: 'image/png' }), width: 1080, height: 1920, showsLimbs: true }));
    render(panel());
    await screen.findAllByRole('listitem');
    expect(screen.queryByText('带四肢')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: /截取第 2 镜画面/ }));

    expect(await screen.findByText('带四肢')).toBeTruthy();
    expect(screen.getByRole('note').textContent).toBe('白模带四肢：请在动作描述里写清分段肢体动作，否则四肢容易僵化');
    const form = calls().find(call => call.method === 'POST' && call.url.endsWith(BASE))?.body as FormData;
    expect(form.get('shows_limbs')).toBe('true');
  });

  it('will not capture unconfirmed blocking, and says why when there is no lens view', async () => {
    const { rerender } = render(panel({ saving: true }));
    await screen.findAllByRole('listitem');
    expect(screen.getByRole('button', { name: /截取第 2 镜画面/ })).toHaveProperty('disabled', true);
    expect(screen.getByText(/保存完成后可截图/)).toBeTruthy();

    rerender(panel({ getLens: () => null }));
    await userEvent.click(screen.getByRole('button', { name: /截取第 2 镜画面/ }));
    expect(await screen.findByText(/切到「并排」或「机位」布局/)).toBeTruthy();
    expect(calls().some(call => call.method === 'POST')).toBe(false);
  });

  it('views, downloads and deletes', async () => {
    const confirm = vi.fn(() => true);
    vi.stubGlobal('confirm', confirm);
    const createObjectURL = vi.fn(() => 'blob:capture');
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }));
    render(panel());
    await screen.findAllByRole('listitem');

    await userEvent.click(screen.getAllByRole('button', { name: '查看 第 2 镜 · 02 单人' })[0]);
    expect(within(screen.getByRole('dialog', { name: '查看截图' })).getByRole('img').getAttribute('src')).toBe(NEW.url);
    await userEvent.click(screen.getByRole('button', { name: '关闭查看' }));

    await userEvent.click(screen.getByRole('button', { name: '下载 第 2 镜 · 02 单人' }));
    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
    expect(calls().some(call => call.url === NEW.url)).toBe(true);

    await userEvent.click(screen.getByRole('button', { name: '删除 第 2 镜 · 02 单人' }));
    expect(confirm).toHaveBeenCalled();
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(1));
    expect(calls().some(call => call.method === 'DELETE' && call.url.endsWith(`${BASE}/cap-new`))).toBe(true);
  });

  it('shows the server’s reason when an action is refused', async () => {
    fetchMock.mockImplementation((_input: RequestInfo | URL, init?: RequestInit) => (
      init?.method === 'POST' ? json({ detail: '本场分镜里还没有第 2 镜，请先完成第 4 阶段分镜' }, 422) : json({ captures: [NEW], applied: {} })
    ));
    render(panel());
    await userEvent.click(await screen.findByRole('button', { name: /应用至分镜/ }));
    expect(await screen.findByText('本场分镜里还没有第 2 镜，请先完成第 4 阶段分镜')).toBeTruthy();
  });

  it('exports a blockout clip through the lens and uploads it with its length, rate and flags', async () => {
    render(panel());
    await screen.findAllByRole('listitem');
    await userEvent.click(screen.getByLabelText('统一白模色'));
    await userEvent.click(screen.getByRole('button', { name: '导出第 2 镜白模视频（4 秒 · 24 fps）' }));

    const item = (await screen.findByText(/白模视频 · 4 秒 · 24 fps/)).closest('li') as HTMLElement;
    expect(clipExport.exportClip).toHaveBeenCalledTimes(1);
    expect(clipExport.exportClip.mock.calls[0][0]).toMatchObject({ aspect: 9 / 16, durationS: 4, fps: 24, monochrome: true, labels: false });
    expect(clipExport.exportClip.mock.calls[0][0].signal).toBeInstanceOf(AbortSignal);
    const upload = calls().find(call => call.method === 'POST' && call.url.endsWith(BASE))!;
    const form = upload.body as FormData;
    expect(Object.fromEntries(['kind', 'shot_id', 'camera_id', 'width', 'height', 'duration_s', 'fps', 'plan_revision', 'shows_limbs', 'monochrome', 'labelled'].map(key => [key, form.get(key)]))).toEqual({
      kind: 'clip', shot_id: '2', camera_id: 'cam-02', width: '720', height: '1280', duration_s: '4', fps: '24', plan_revision: '3', shows_limbs: 'true', monochrome: 'true', labelled: 'false',
    });
    expect((form.get('file') as File).name).toBe('shot-2-cam-02.mp4');

    // It plays inline, and says what the server says about limbs.
    expect(within(item).getByLabelText('第 2 镜 · 02 单人 白模视频').tagName).toBe('VIDEO');
    expect(within(item).getByText('带四肢')).toBeTruthy();
    expect(within(item).getByRole('note').textContent).toContain('分段肢体动作');
    expect(screen.getByRole('status').textContent).toContain('白模视频已导出并保存');
    expect(screen.queryByRole('group', { name: '导出进度' })).toBeNull();
  });

  it('applies a clip and says what that does to stage 5', async () => {
    render(panel());
    await screen.findAllByRole('listitem');
    await userEvent.click(screen.getByRole('button', { name: /导出第 2 镜白模视频/ }));
    const item = (await screen.findByText(/白模视频 · 4 秒 · 24 fps/)).closest('li') as HTMLElement;
    await userEvent.click(within(item).getByRole('button', { name: /应用至分镜/ }));
    expect(await within(item).findByText('已应用')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toContain('按多模态使用这条白模视频，实测机位句不再写入本镜提示词');
    expect(calls().some(call => call.method === 'POST' && call.url.endsWith(`${BASE}/cap-clip/apply`))).toBe(true);
    // The explanation is there before anybody applies anything.
    expect(screen.getByText('白模视频应用到分镜后会发生什么')).toBeTruthy();
    expect(screen.getByText(/所选视频模型不支持多模态时本镜会报错/)).toBeTruthy();
    expect(screen.getByText(/实测机位句（「机位距…米、机高…米」）从本镜的站位描述和运动提示词里撤下/)).toBeTruthy();
  });

  it('shows progress, and cancelling leaves nothing behind', async () => {
    let abort: AbortSignal | undefined;
    clipExport.exportClip.mockImplementation((request: ClipRequest) => new Promise((_, reject) => {
      abort = request.signal;
      request.onProgress?.(0.25);
      request.signal?.addEventListener('abort', () => reject(new DOMException('已取消导出', 'AbortError')));
    }));
    render(panel());
    await screen.findAllByRole('listitem');
    await userEvent.click(screen.getByRole('button', { name: /导出第 2 镜白模视频/ }));
    const progress = await screen.findByRole('group', { name: '导出进度' });
    expect(within(progress).getByText('25%')).toBeTruthy();
    expect(screen.getByRole('button', { name: /截取第 2 镜画面|处理中/ })).toHaveProperty('disabled', true);

    await userEvent.click(within(progress).getByRole('button', { name: '取消' }));
    expect((await screen.findByRole('status')).textContent).toContain('已取消导出');
    expect(abort?.aborted).toBe(true);
    expect(calls().some(call => call.method === 'POST')).toBe(false);
    expect(screen.queryByRole('group', { name: '导出进度' })).toBeNull();
  });

  it('keeps stills working when the browser cannot encode video', async () => {
    clipExport.exportClip.mockRejectedValue(new Error('当前浏览器不支持 WebCodecs 视频编码，无法导出白模视频；静帧截图不受影响。'));
    render(panel());
    await screen.findAllByRole('listitem');
    await userEvent.click(screen.getByRole('button', { name: /导出第 2 镜白模视频/ }));
    expect((await screen.findByRole('status')).textContent).toContain('不支持 WebCodecs');
    await userEvent.click(screen.getByRole('button', { name: /截取第 2 镜画面/ }));
    await waitFor(() => expect(capture).toHaveBeenCalled());
  });

  it('asks for the camera view when there is no lens canvas to film through', async () => {
    getClipStage.mockReturnValueOnce(null);
    render(panel());
    await screen.findAllByRole('listitem');
    await userEvent.click(screen.getByRole('button', { name: /导出第 2 镜白模视频/ }));
    expect((await screen.findByRole('status')).textContent).toContain('请切到「并排」或「机位」布局');
    expect(clipExport.exportClip).not.toHaveBeenCalled();
  });

  it('refuses, before anything leaves the machine, what the server would refuse', async () => {
    clipExport.exportClip.mockResolvedValue({ blob: new Blob(['x'], { type: 'video/mp4' }), format: 'mp4', width: 720, height: 1280, durationS: 31, fps: 24, frames: 744, showsLimbs: false });
    render(panel());
    await screen.findAllByRole('listitem');
    await userEvent.click(screen.getByRole('button', { name: /导出第 2 镜白模视频/ }));
    expect((await screen.findByRole('status')).textContent).toContain('0 到 30 秒');
    expect(calls().some(call => call.method === 'POST')).toBe(false);
  });

  it('takes a depth still: the lens renders depth, the upload says so, and the result cannot be applied', async () => {
    render(panel());
    await screen.findAllByRole('listitem');
    await userEvent.click(screen.getByLabelText('深度画面'));
    await userEvent.click(screen.getByRole('button', { name: /截取第 2 镜画面/ }));

    expect((await screen.findByRole('status')).textContent).toContain('深度静帧不能应用为首帧');
    expect(capture).toHaveBeenCalledWith({ monochrome: false, labels: false, depth: true });
    const form = calls().find(call => call.method === 'POST' && call.url.endsWith(BASE))?.body as FormData;
    expect(form.get('depth')).toBe('true');

    const item = screen.getByText('深度').closest('li') as HTMLElement;
    const apply = within(item).getByRole('button', { name: /应用至分镜/ });
    expect(apply).toHaveProperty('disabled', true);
    expect(apply.getAttribute('title')).toBe(DEPTH_STILL_REFUSAL);
    expect(within(item).getByRole('note').textContent).toBe(DEPTH_WARNING);
  });

  it('exports a depth clip with the same checkbox, and that one applies', async () => {
    render(panel());
    await screen.findAllByRole('listitem');
    await userEvent.click(screen.getByLabelText('深度画面'));
    await userEvent.click(screen.getByRole('button', { name: /导出第 2 镜白模视频/ }));

    const item = (await screen.findByText(/白模视频 · 4 秒 · 24 fps/)).closest('li') as HTMLElement;
    expect(clipExport.exportClip.mock.calls[0][0]).toMatchObject({ depth: true });
    const form = calls().find(call => call.method === 'POST' && call.url.endsWith(BASE))?.body as FormData;
    expect(form.get('depth')).toBe('true');
    expect(within(item).getByText('深度')).toBeTruthy();
    expect(within(item).getByRole('note').textContent).toBe(DEPTH_WARNING);

    const apply = within(item).getByRole('button', { name: /应用至分镜/ });
    expect(apply).toHaveProperty('disabled', false);
    expect(apply.getAttribute('title')).toContain('深度视频');
    await userEvent.click(apply);
    expect(await within(item).findByText('已应用')).toBeTruthy();
  });

  it('shows the depth badge and refusal on a stored depth still, and drives the live depth preview', async () => {
    state.captures = [{ ...NEW, id: 'cap-depth', depth: true, warning: DEPTH_WARNING }];
    const onDepthPreview = vi.fn();
    const { rerender } = render(panel({ onDepthPreview }));
    const [item] = await screen.findAllByRole('listitem');
    expect(within(item).getByText('深度')).toBeTruthy();
    expect(within(item).getByRole('button', { name: /应用至分镜/ })).toHaveProperty('disabled', true);
    expect(within(item).getByRole('button', { name: /应用至分镜/ }).getAttribute('title')).toBe(DEPTH_STILL_REFUSAL);

    const preview = screen.getByLabelText('深度预览') as HTMLInputElement;
    expect(preview.checked).toBe(false);
    await userEvent.click(preview);
    expect(onDepthPreview).toHaveBeenCalledWith(true);
    rerender(panel({ onDepthPreview, depthPreview: true }));
    expect((screen.getByLabelText('深度预览') as HTMLInputElement).checked).toBe(true);
  });
});
