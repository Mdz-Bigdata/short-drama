// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { TimelinePanel, type Timeline } from './TimelinePanel';

function timeline(overrides: Partial<Timeline> = {}): Timeline {
  return {
    title: { text: '暗室回声', seconds: 2.6 },
    clips: [
      { shot_id: 1, video_url: '/media/c1.mp4', candidates: ['/media/c1.mp4', '/media/c1b.mp4'], duration: 8, in: 0, out: null, muted: false, subtitle: '你到底瞒了什么？', voice_path: '/tmp/v1.mp3', transition_in: null, review: { decision: 'pending', note: '', decided_at: null } },
      { shot_id: 3, video_url: '/media/c3.mp4', candidates: ['/media/c3.mp4'], duration: 6, in: 0, out: null, muted: false, subtitle: '现在回头还来得及', voice_path: null, transition_in: { type: 'crossfade', duration: 0.22 }, review: { decision: 'approved', note: '', decided_at: 'now' } },
    ],
    bgm: { source: 'generated', path: '/tmp/bgm.mp3', url: null, library_id: null, name: '阶段 6 生成', volume: 0.16, duck: true },
    revision: 2,
    ...overrides,
  };
}

function response(current: Timeline) {
  return {
    task_id: 't1', timeline: current,
    summary: { clips: 2, included: current.clips.filter(c => c.review.decision !== 'rejected').length, review: { pending: 1, approved: 1, rejected: 0 }, seconds: 16.6, bgm: current.bgm.source, revision: current.revision },
    transitions: ['hard_cut', 'match_cut', 'crossfade', 'dip_to_black', 'neutral_bridge'],
    bgm_library: [{ id: 'bgm-1', name: '夜雨', mood: 'tense', seconds: 30, source: 'upload' }],
  };
}

describe('TimelinePanel', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('shows the cut, applies a trim, reviews a clip, picks library music and renders', async () => {
    let current = timeline();
    const posts: Array<{ url: string; body: unknown }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/timeline/ops') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        posts.push({ url: '/timeline/ops', body });
        if (body.operation === 'trim') current = { ...current, clips: current.clips.map(c => c.shot_id === body.shot_id ? { ...c, in: Number(body.start), out: body.end as number | null } : c) };
        if (body.operation === 'review') current = { ...current, clips: current.clips.map(c => c.shot_id === body.shot_id ? { ...c, review: { decision: body.decision as 'rejected', note: String(body.note ?? ''), decided_at: 'now' } } : c) };
        if (body.operation === 'bgm') current = { ...current, bgm: { ...current.bgm, source: 'library', library_id: 'bgm-1', name: '夜雨' } };
        return { ok: true, json: async () => response(current) } as Response;
      }
      if (url.endsWith('/timeline/render') && init?.method === 'POST') {
        posts.push({ url: '/timeline/render', body: null });
        return { ok: true, json: async () => ({ final_video_url: '/media/film.mp4' }) } as Response;
      }
      if (url.endsWith('/timeline')) return { ok: true, json: async () => response(current) } as Response;
      throw new Error(`unexpected fetch ${url}`);
    });
    vi.stubGlobal('prompt', () => '人物面部崩坏');
    const onRendered = vi.fn<(url: string) => void>();

    render(<TimelinePanel taskId="t1" onRendered={onRendered} />);

    const panel = await screen.findByRole('region', { name: '剪辑时间线' });
    expect(within(panel).getByText(/2\/2 镜入片/)).toBeTruthy();
    expect(within(panel).getAllByText('通过')[0]).toBeTruthy();
    expect(within(panel).getByText('用这条')).toBeTruthy();
    expect(within(panel).getByRole('link', { name: /下载剪映草稿/ }).getAttribute('href')).toContain('/api/drama/t1/timeline/jianying.zip');

    await userEvent.clear(within(panel).getByLabelText('镜头 1 出点'));
    await userEvent.type(within(panel).getByLabelText('镜头 1 出点'), '6');
    await userEvent.click(within(panel).getAllByRole('button', { name: '应用裁剪' })[0]);
    await waitFor(() => expect(posts[0]?.body).toEqual({ operation: 'trim', shot_id: 1, start: 0, end: 6 }));

    await userEvent.click(within(panel).getByRole('button', { name: '打回镜头 3' }));
    await waitFor(() => expect(posts[1]?.body).toEqual({ operation: 'review', shot_id: 3, decision: 'rejected', note: '人物面部崩坏' }));
    expect(await within(panel).findByText('审看备注：人物面部崩坏')).toBeTruthy();
    expect(within(panel).getByText(/1\/2 镜入片/)).toBeTruthy();

    await userEvent.click(within(panel).getByRole('button', { name: '用这条' }));
    await waitFor(() => expect(posts[2]?.body).toEqual({ operation: 'bgm', source: 'library', library_id: 'bgm-1' }));
    expect(await within(panel).findByText(/当前：夜雨/)).toBeTruthy();

    await userEvent.click(within(panel).getByRole('button', { name: /按时间线重新合成/ }));
    await waitFor(() => expect(onRendered).toHaveBeenCalledWith('/media/film.mp4'));
    expect(await within(panel).findByText('已按时间线重新合成成片。')).toBeTruthy();
  });

  it('offers the sound offset on a cut and says what the last render did with it', async () => {
    const base = timeline();
    const current = timeline({
      clips: base.clips.map((clip, index) => index === 1 ? { ...clip, sound_in: { join: 'j_cut', result: { applied: false, reason: '下一镜没有配音，没有声音可以提前' } } } : clip),
    });
    const posts: unknown[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/timeline/ops')) {
        posts.push(JSON.parse(String(init?.body)));
        return { ok: true, json: async () => response(current) } as Response;
      }
      return { ok: true, json: async () => response(current) } as Response;
    }));
    render(<TimelinePanel taskId="t1" />);

    const second = current.clips[1].shot_id;
    const select = await screen.findByRole('combobox', { name: `镜头 ${second} 声音错开` }) as HTMLSelectElement;
    expect(select.value).toBe('j_cut');
    expect(screen.queryByRole('combobox', { name: `镜头 ${current.clips[0].shot_id} 声音错开` })).toBeNull();
    expect(screen.getByText(/下一镜没有配音/)).toBeTruthy();

    await userEvent.selectOptions(screen.getByRole('combobox', { name: `镜头 ${second} 错开秒数` }), '0.8');
    expect(posts).toContainEqual({ operation: 'sound_join', shot_id: second, join: 'j_cut', seconds: 0.8 });
    await userEvent.selectOptions(select, '');
    expect(posts).toContainEqual({ operation: 'sound_join', shot_id: second, join: '' });
  });

  it('edits the clip of the right scene when two scenes both have a shot 1', async () => {
    const base = timeline();
    let current = timeline({
      clips: [
        { ...base.clips[0], shot_id: 1, shot_uid: 100101, scene_id: 'E1S01', subtitle: '第一场' },
        { ...base.clips[1], shot_id: 1, shot_uid: 100201, scene_id: 'E1S02', subtitle: '第二场', review: { decision: 'pending', note: '', decided_at: null } },
      ],
    });
    const posts: Array<Record<string, unknown>> = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/timeline/ops')) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        posts.push(body);
        if (body.operation === 'review') current = { ...current, clips: current.clips.map(c => c.shot_uid === body.shot_uid ? { ...c, review: { decision: 'approved', note: '', decided_at: 'now' } } : c) };
      }
      return { ok: true, json: async () => response(current) } as Response;
    }));
    render(<TimelinePanel taskId="t1" />);

    expect(await screen.findByText('E1S02 · 镜头 1')).toBeTruthy();
    await userEvent.type(screen.getByLabelText('E1S02 · 镜头 1 入点'), '2');
    expect((screen.getByLabelText('E1S01 · 镜头 1 入点') as HTMLInputElement).value).toBe('0');

    await userEvent.click(screen.getByRole('button', { name: '通过E1S02 · 镜头 1' }));
    await waitFor(() => expect(posts).toEqual([{ operation: 'review', shot_id: 1, shot_uid: 100201, decision: 'approved' }]));
    const rows = screen.getAllByRole('listitem').filter(row => row.querySelector('video'));
    await waitFor(() => expect(rows.map(row => row.className)).toEqual(['is-pending', 'is-approved']));
  });

  it('leaves the clip alone when the reject prompt is cancelled', async () => {
    const current = timeline();
    const posts: unknown[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/timeline/ops')) posts.push(JSON.parse(String(init?.body)));
      return { ok: true, json: async () => response(current) } as Response;
    }));
    vi.stubGlobal('prompt', () => null);
    render(<TimelinePanel taskId="t1" />);

    await userEvent.click(await screen.findByRole('button', { name: '打回镜头 1' }));
    await userEvent.click(screen.getByRole('button', { name: '通过镜头 1' }));

    expect(posts).toEqual([{ operation: 'review', shot_id: 1, decision: 'approved' }]);
  });

  it('keeps what was typed and not saved when another edit comes back from the server', async () => {
    let current = timeline();
    const posts: Array<Record<string, unknown>> = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/timeline/ops')) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        posts.push(body);
        if (body.operation === 'trim') current = { ...current, clips: current.clips.map(c => c.shot_id === body.shot_id ? { ...c, in: Number(body.start), out: body.end as number | null } : c) };
        if (body.operation === 'title') current = { ...current, title: { ...current.title, text: String(body.text) } };
        current = { ...current, revision: current.revision + 1 };
      }
      return { ok: true, json: async () => response(current) } as Response;
    }));
    render(<TimelinePanel taskId="t1" />);

    const title = await screen.findByLabelText('片头标题') as HTMLInputElement;
    await userEvent.clear(title);
    await userEvent.type(title, '回声');
    const out = screen.getByLabelText('镜头 3 出点') as HTMLInputElement;
    await userEvent.type(out, '4');
    const trim = screen.getAllByRole('button', { name: '应用裁剪' })[1];
    expect(trim.className).toContain('is-unsaved');

    await userEvent.click(screen.getAllByRole('checkbox', { name: '本镜配音静音' })[0]);
    await waitFor(() => expect(posts.map(post => post.operation)).toEqual(['mute']));
    expect(title.value).toBe('回声');
    expect(out.value).toBe('4');

    await userEvent.click(trim);
    await waitFor(() => expect(posts[1]).toEqual({ operation: 'trim', shot_id: 3, start: 0, end: 4 }));
    await waitFor(() => expect(trim.className).not.toContain('is-unsaved'));
    expect(out.value).toBe('4');
    expect(title.value).toBe('回声');

    await userEvent.click(screen.getByRole('button', { name: '保存片头' }));
    await waitFor(() => expect(posts[2]).toEqual({ operation: 'title', text: '回声' }));
    await waitFor(() => expect((screen.getByRole('button', { name: '保存片头' }) as HTMLButtonElement).disabled).toBe(true));
  });

  it('sends the music volume once, when the slider is let go', async () => {
    let current = timeline();
    const posts: Array<Record<string, unknown>> = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/timeline/ops')) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        posts.push(body);
        current = { ...current, bgm: { ...current.bgm, volume: Number(body.volume) } };
      }
      return { ok: true, json: async () => response(current) } as Response;
    }));
    render(<TimelinePanel taskId="t1" />);

    const slider = await screen.findByLabelText('配乐音量') as HTMLInputElement;
    fireEvent.change(slider, { target: { value: '0.3' } });
    fireEvent.change(slider, { target: { value: '0.42' } });
    fireEvent.change(slider, { target: { value: '0.5' } });
    expect(posts).toEqual([]);
    expect(slider.value).toBe('0.5');
    expect(screen.getByText(/音量 50%/)).toBeTruthy();

    fireEvent.pointerUp(slider);
    fireEvent.blur(slider);
    await waitFor(() => expect(posts).toEqual([{ operation: 'bgm', source: 'generated', library_id: null, volume: 0.5 }]));
    await waitFor(() => expect(slider.disabled).toBe(false));
    expect(slider.value).toBe('0.5');

    // 没改动就松手，不发请求。
    fireEvent.keyUp(slider, { key: 'Tab' });
    fireEvent.blur(slider);
    expect(posts).toHaveLength(1);
  });

  it('uploads a music file into the library and puts it on the timeline', async () => {
    const current = timeline();
    const calls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/api/library/bgm') && init?.method === 'POST') {
        calls.push('upload');
        expect(init.body).toBeInstanceOf(FormData);
        expect((init.body as FormData).get('name')).toBe('雨夜');
        return { ok: true, json: async () => ({ id: 'bgm-9', name: '雨夜', mood: '', seconds: 12, source: 'upload' }) } as Response;
      }
      if (url.endsWith('/timeline/ops')) {
        calls.push(`ops:${(JSON.parse(String(init?.body)) as { library_id: string }).library_id}`);
        return { ok: true, json: async () => response(current) } as Response;
      }
      if (url.endsWith('/timeline')) return { ok: true, json: async () => response(current) } as Response;
      throw new Error(`unexpected fetch ${url}`);
    });

    render(<TimelinePanel taskId="t1" />);
    const panel = await screen.findByRole('region', { name: '剪辑时间线' });
    await userEvent.type(within(panel).getByLabelText('配乐名称'), '雨夜');
    const file = new File([new Uint8Array([0x49, 0x44, 0x33, 0, 0])], 'night.mp3', { type: 'audio/mpeg' });
    await userEvent.upload(within(panel).getByLabelText('上传配乐文件'), file);

    await waitFor(() => expect(calls).toEqual(['upload', 'ops:bgm-9']));
  });
});
