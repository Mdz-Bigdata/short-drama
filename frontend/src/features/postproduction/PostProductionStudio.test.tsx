// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PostProductionStudio } from './PostProductionStudio';
import type { StudioResponse } from './postProduction';

vi.mock('../workbench/TimelinePanel', () => ({ TimelinePanel: () => <p>完整剪辑台</p> }));

function clip(shot_uid: number, patch: Record<string, unknown> = {}) {
  return {
    shot_id: shot_uid, shot_uid, scene_id: shot_uid < 3 ? 'S1' : 'S2', video_url: `/media/c${shot_uid}.mp4`, candidates: [], duration: 4,
    in: 0, out: null, muted: false, subtitle: `第${shot_uid}句。`, voice_path: null, transition_in: null,
    review: { decision: 'pending', note: '', decided_at: null }, audio_source: 'native', native_available: true, ...patch,
  };
}

function studio(patch: Partial<StudioResponse> = {}): StudioResponse {
  return {
    task_id: 't1',
    timeline: {
      title: { text: '雪夜', seconds: 2.6 }, revision: 4, episode: 2,
      clips: [clip(1), clip(2, { audio_source: 'tts', native_available: false, voice_path: '/srv/media/v2.mp3' }), clip(3)],
      bgm: { source: 'generated', path: '/srv/bgm.mp3', url: '/media/bgm.mp3', library_id: null, name: null, volume: 0.16, duck: true, start: 0 },
    } as StudioResponse['timeline'],
    summary: { clips: 3, included: 3, seconds: 14.6, revision: 4, audio_sources: { native: 2, tts: 1, none: 0 } },
    bgm_library: [
      { id: 'a', name: '宫墙暗涌', mood: '古风 紧张', seconds: 60, source: 'upload', match: 0.86, tags: ['紧张悬疑', '古风'] },
      { id: 'b', name: '轻快日常', mood: '欢快', seconds: 40, source: 'upload', match: 0.41, tags: ['轻快'] },
    ],
    acceptance: [],
    post: {
      settings: { transitions: true, dialogue: true, subtitles: true, title_card: true, name_cards: true },
      tension: [
        { shot_uid: 1, shot_id: 1, scene_id: 'S1', t: 2.6, seconds: 4, tension: 0.8 },
        { shot_uid: 2, shot_id: 2, scene_id: 'S1', t: 6.6, seconds: 4, tension: 0.5 },
        { shot_uid: 3, shot_id: 3, scene_id: 'S2', t: 10.6, seconds: 4, tension: 0.2 },
      ],
      scene_markers: [{ scene_id: 'S1', t: 2.6 }, { scene_id: 'S2', t: 10.6 }],
      estimated_bytes: 8_500_000,
      music_versions: [
        { url: '/media/bgm.mp3', created_at: '2026-11-11T08:00:00+00:00' },
        { url: '/media/bgm_old.mp3', created_at: '2026-11-10T08:00:00+00:00' },
      ],
      film_versions: [
        { url: '/media/film_b.mp4', revision: 4, rendered_at: '2026-11-11T08:00:00+00:00', compose_mode: 'm', seconds: 14.6, bytes: 9_437_184 },
        { url: '/media/film_a.mp4', revision: 2, rendered_at: '2026-11-10T08:00:00+00:00', compose_mode: 'm', seconds: 12, bytes: null },
      ],
      shots: [
        { shot_uid: 1, image_url: '/media/f1.png', draft: false, audio_source: 'native', native_available: true },
        { shot_uid: 2, image_url: null, draft: true, audio_source: 'tts', native_available: false },
        { shot_uid: 3, image_url: null, draft: false, audio_source: 'native', native_available: true },
      ],
    },
    ...patch,
  };
}

const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => data }) as Response;

function mockApi(initial = studio()) {
  let current = initial;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith('/timeline/ops')) {
      const body = JSON.parse(String(init?.body));
      if (body.operation === 'settings') current = { ...current, post: { ...current.post!, settings: { ...current.post!.settings, ...body.settings } } };
      return ok(current);
    }
    if (url.endsWith('/timeline/render')) return ok({ final_video_url: '/media/film_c.mp4' });
    if (url.includes('/hd?')) return ok({});
    return ok(current);
  });
  vi.stubGlobal('fetch', fetchMock);
  const posted = (operation: string) => fetchMock.mock.calls
    .filter(([url]) => String(url).endsWith('/timeline/ops'))
    .map(([, init]) => JSON.parse(String(init?.body)))
    .filter(body => body.operation === operation);
  return { fetchMock, posted };
}

function show(props: Partial<Parameters<typeof PostProductionStudio>[0]> = {}) {
  const handlers = { onRegenerateSound: vi.fn(), onCompose: vi.fn(), onRendered: vi.fn() };
  render(<PostProductionStudio taskId="t1" filmUrl="/media/film_b.mp4" filmKey="k" audioModel="eleven_multilingual_v2"
    sound={{ music_prompt: 'cinematic score', ambience_prompt: null, dialogue_directions: [{ shot_id: 2, speaker: '苏晚', verbatim_text: '苏晚：{你敢？}（冷）', emotion: '怒' }] }}
    {...handlers} {...props} />);
  return handlers;
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('PostProductionStudio', () => {
  it('lays out the bay: header, player, film strip, settings, music and the footer', async () => {
    mockApi();
    show();
    const page = await screen.findByRole('region', { name: '剪辑合成师' });
    expect(within(page).getByRole('heading', { name: '后期制作 · 第 2 集' })).toBeTruthy();
    expect(within(page).getByText('3 个镜头')).toBeTruthy();
    expect(within(page).getByText('原声 2 · 配音 1 · 无人声 0')).toBeTruthy();
    expect(page.querySelectorAll('video')).toHaveLength(1);
    expect(page.querySelector('video')?.getAttribute('src')).toBe('/media/film_b.mp4');
    expect(within(page).getAllByRole('switch')).toHaveLength(5);   // 转场、对白、字幕、片名卡、人物出场字幕
    expect(within(page).getByRole('list', { name: '镜头胶片条' }).querySelectorAll('li')).toHaveLength(3);
    expect(within(page).getByText('匹配度 86%')).toBeTruthy();
    expect(within(page).getByText('配乐模型').parentElement?.textContent).toBe('配乐模型ElevenLabs Music');
    expect(within(page).getByText('0:15')).toBeTruthy();
    // The film on screen has a measured size, so it is not an estimate.
    expect(within(page).getByText('9.0 MB')).toBeTruthy();
    expect(within(page).getByRole('link', { name: '下载视频' }).getAttribute('href')).toBe('/media/film_b.mp4');
  });

  it('sends each basic switch as a settings edit', async () => {
    const { posted } = mockApi();
    show();
    const subtitles = await screen.findByRole('switch', { name: '嵌入字幕' });
    expect(subtitles.getAttribute('aria-checked')).toBe('true');
    await userEvent.click(subtitles);
    await waitFor(() => expect(posted('settings')).toEqual([{ operation: 'settings', settings: { subtitles: false } }]));
    await waitFor(() => expect(screen.getByRole('switch', { name: '嵌入字幕' }).getAttribute('aria-checked')).toBe('false'));
  });

  it('lets one shot use its own sound, a dub or nothing, and never its own sound when it has none', async () => {
    const { posted } = mockApi();
    show();
    await userEvent.click(await screen.findByRole('button', { name: 'S1 镜头 2，配音' }));
    const group = screen.getByRole('radiogroup', { name: '人声来源' });
    expect((within(group).getByRole('radio', { name: '原声' }) as HTMLButtonElement).disabled).toBe(true);
    expect(within(group).getByRole('radio', { name: '配音' }).getAttribute('aria-checked')).toBe('true');
    expect(screen.getByLabelText('这一镜的配音').getAttribute('src')).toBe('http://localhost:8000/media/v2.mp3');

    await userEvent.click(screen.getByRole('button', { name: 'S1 镜头 1，原声' }));
    await userEvent.click(within(screen.getByRole('radiogroup', { name: '人声来源' })).getByRole('radio', { name: '配音' }));
    await waitFor(() => expect(posted('audio_source')).toEqual([{ operation: 'audio_source', shot_id: 1, shot_uid: 1, audio_source: 'tts' }]));
  });

  it('swaps the music for a library track and places it on release', async () => {
    const { posted } = mockApi();
    show();
    const library = await screen.findByRole('list', { name: '配乐库推荐' });
    await userEvent.click(within(library).getAllByRole('button', { name: '换上' })[0]);
    await waitFor(() => expect(posted('bgm')).toEqual([{ operation: 'bgm', source: 'library', library_id: 'a' }]));

    const placement = screen.getByRole('slider', { name: '音乐定位' });
    fireEvent.change(placement, { target: { value: '6' } });
    expect(screen.getByText('从 0:06 进')).toBeTruthy();
    expect(posted('bgm')).toHaveLength(1);
    fireEvent.pointerUp(placement);
    await waitFor(() => expect(posted('bgm')[1]).toEqual({ operation: 'bgm', bgm_start: 6 }));
  });

  it('puts an earlier generated music version back on', async () => {
    const { posted } = mockApi();
    show();
    const select = await screen.findByRole('combobox', { name: '配乐版本' });
    expect((select as HTMLSelectElement).value).toBe('/media/bgm.mp3');
    await userEvent.selectOptions(select, '/media/bgm_old.mp3');
    await waitFor(() => expect(posted('bgm')).toEqual([{ operation: 'bgm', source: 'generated', music_version: '/media/bgm_old.mp3' }]));
    expect(within(select).getByRole('option', { name: '生成 V1' })).toBeTruthy();
  });

  it('plays an earlier version and estimates its size', async () => {
    mockApi();
    show();
    const select = await screen.findByRole('combobox', { name: '成片版本' });
    expect(within(select).getAllByRole('option')).toHaveLength(2);
    await userEvent.selectOptions(select, '/media/film_a.mp4');
    expect(document.querySelector('video')?.getAttribute('src')).toBe('/media/film_a.mp4');
    expect(screen.getByText('大小（预估）')).toBeTruthy();
  });

  it('upscales the draft shots locally after asking, then re-renders on request', async () => {
    const { fetchMock } = mockApi();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const { onRendered } = show();
    await userEvent.click(await screen.findByRole('button', { name: /生成高清片段 \(1\)/ }));
    expect(confirm).toHaveBeenCalled();
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/shots/2/hd?scene_id=S1&shot_uid=2'))).toBe(true));
    await screen.findByText('已放大 1 个镜头，重新合成后成片用高清片段。');

    await userEvent.click(screen.getByRole('button', { name: '重新合成' }));
    await waitFor(() => expect(onRendered).toHaveBeenCalled());
  });

  it('asks before regenerating the sound and shows the prompts it used', async () => {
    mockApi();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    const { onRegenerateSound } = show();
    const button = await screen.findByRole('button', { name: '一键重新生成音效配乐' });
    await userEvent.click(button);
    expect(onRegenerateSound).not.toHaveBeenCalled();
    await userEvent.click(button);
    expect(onRegenerateSound).toHaveBeenCalledTimes(1);
    expect(confirm).toHaveBeenCalledTimes(2);

    await userEvent.click(screen.getByRole('button', { name: '查看提示词' }));
    const dialog = screen.getByRole('dialog', { name: '提示词' });
    expect(within(dialog).getByText('cinematic score')).toBeTruthy();
    expect(within(dialog).getByText(/你敢？/).textContent).not.toContain('冷）');
    await userEvent.click(within(dialog).getByRole('button', { name: '关闭' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('lists the films still in an old voice and renders the chosen episode', async () => {
    const { fetchMock } = mockApi();
    show({ voiceRerender: [1, 2] });
    const alert = await screen.findByRole('group', { name: '换了音色，要重新合成的成片' });
    await userEvent.click(within(alert).getByRole('button', { name: '重新合成第 1 集' }));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/timeline/render'));
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ episode: 1 });
    });
    expect(await screen.findByText('已重新合成第 1 集。')).toBeTruthy();
    // Episode 2 is the one on the timeline: rendered the default way, which also refreshes the current film.
    await userEvent.click(within(alert).getByRole('button', { name: '重新合成第 2 集' }));
    await waitFor(() => {
      const bodies = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/timeline/render')).map(([, init]) => JSON.parse(String(init?.body)));
      expect(bodies[1]).toEqual({});
    });
  });

  describe('episode switch', () => {
    const episodes = [{ number: 1, clips: 2, film_url: '/media/film_e1.mp4' }, { number: 2, clips: 3, film_url: null }];
    const second = () => studio({ episodes, live_episode: 2 });
    const first = () => studio({
      episodes, live_episode: 2,
      timeline: { ...studio().timeline, episode: 1, clips: [studio().timeline.clips[0]] },
      post: { ...studio().post!, film_versions: [{ url: '/media/film_e1.mp4', revision: 1, rendered_at: '2026-11-09T08:00:00+00:00', compose_mode: 'm', seconds: 9, bytes: 1_000_000 }] },
    });
    /** Answers with episode 1's cut when asked for it, by query on reads and by body on edits. */
    function mockEpisodes() {
      const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith('/timeline/render')) return ok({ final_video_url: '/media/film_e1_new.mp4' });
        if (url.endsWith('/timeline/ops')) return ok(JSON.parse(String(init?.body)).episode === 1 ? first() : second());
        return ok(url.endsWith('?episode=1') ? first() : second());
      });
      vi.stubGlobal('fetch', fetchMock);
      const bodies = (suffix: string) => fetchMock.mock.calls.filter(([url]) => String(url).endsWith(suffix)).map(([, init]) => JSON.parse(String(init?.body)));
      return { fetchMock, bodies };
    }

    it('is not shown for a project made in one run', async () => {
      mockApi();
      show();
      await screen.findByRole('list', { name: '镜头胶片条' });
      expect(screen.queryByRole('combobox', { name: '剪辑哪一集' })).toBeNull();
    });

    it('opens a finished episode: its clips, its film, its edits and its render', async () => {
      const { fetchMock, bodies } = mockEpisodes();
      const { onRegenerateSound } = show({ filmUrl: null, episode: 2 });
      const picker = await screen.findByRole('combobox', { name: '剪辑哪一集' }) as HTMLSelectElement;
      expect(picker.value).toBe('2');
      expect(within(picker).getByRole('option', { name: '第 1 集 · 已出成片' })).toBeTruthy();
      expect(within(picker).getByRole('option', { name: '第 2 集 · 制作中' })).toBeTruthy();

      await userEvent.selectOptions(picker, '1');
      await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/timeline?episode=1'))).toBe(true));
      await waitFor(() => expect(screen.getByRole('list', { name: '镜头胶片条' }).querySelectorAll('li')).toHaveLength(1));
      expect(screen.getByRole('heading', { name: /后期制作 · 第 1 集/ })).toBeTruthy();
      expect(document.querySelector('.pp video')?.getAttribute('src')).toBe('/media/film_e1.mp4');

      // An edit and a render both name the episode on screen.
      await userEvent.click(screen.getByRole('switch', { name: '嵌入字幕' }));
      await waitFor(() => expect(bodies('/timeline/ops')).toEqual([{ operation: 'settings', settings: { subtitles: false }, episode: 1 }]));
      await userEvent.click(screen.getByRole('button', { name: '重新合成第 1 集' }));
      await waitFor(() => expect(bodies('/timeline/render')).toEqual([{ episode: 1 }]));

      // What belongs to the episode in production waits until the editor is back on it.
      const regenerate = screen.getByRole('button', { name: '一键重新生成音效配乐' }) as HTMLButtonElement;
      expect(regenerate.disabled).toBe(true);
      expect((screen.getByRole('button', { name: '剪辑室' }) as HTMLButtonElement).disabled).toBe(true);
      expect(onRegenerateSound).not.toHaveBeenCalled();
    });

    it('goes back to the episode in production without naming it', async () => {
      const { fetchMock, bodies } = mockEpisodes();
      show({ filmUrl: null, episode: 2 });
      const picker = await screen.findByRole('combobox', { name: '剪辑哪一集' });
      await userEvent.selectOptions(picker, '1');
      await waitFor(() => expect(screen.getByRole('list', { name: '镜头胶片条' }).querySelectorAll('li')).toHaveLength(1));
      await userEvent.selectOptions(picker, '2');
      await waitFor(() => expect(screen.getByRole('list', { name: '镜头胶片条' }).querySelectorAll('li')).toHaveLength(3));
      expect(String(fetchMock.mock.calls.at(-1)?.[0]).endsWith('/timeline')).toBe(true);

      await userEvent.click(screen.getByRole('switch', { name: '嵌入字幕' }));
      await waitFor(() => expect(bodies('/timeline/ops')).toEqual([{ operation: 'settings', settings: { subtitles: false } }]));
      expect((screen.getByRole('button', { name: '剪辑室' }) as HTMLButtonElement).disabled).toBe(false);
    });

    it('falls back to the episode in production when the chosen one cannot be read', async () => {
      const fetchMock = vi.fn(async (input: RequestInfo | URL) => (String(input).endsWith('?episode=1')
        ? ({ ok: false, status: 422, json: async () => ({ detail: '第 1 集没有片段' }) }) as Response
        : ok(second())));
      vi.stubGlobal('fetch', fetchMock);
      show({ filmUrl: null, episode: 2 });
      const picker = await screen.findByRole('combobox', { name: '剪辑哪一集' }) as HTMLSelectElement;
      await userEvent.selectOptions(picker, '1');
      await waitFor(() => expect(picker.value).toBe('2'));
      expect(screen.getByRole('list', { name: '镜头胶片条' }).querySelectorAll('li')).toHaveLength(3);
      expect(document.querySelector('.pp-notice')?.textContent).toContain('第 1 集没有片段');
    });
  });

  it('opens the full edit room on demand', async () => {
    mockApi();
    show();
    await userEvent.click(await screen.findByRole('button', { name: '剪辑室' }));
    expect(await screen.findByText('完整剪辑台')).toBeTruthy();
  });

  it('offers to compose when the sound is done and there is no film yet', async () => {
    mockApi(studio({ post: { ...studio().post!, film_versions: [] } }));
    const { onCompose } = show({ filmUrl: null });
    await userEvent.click(await screen.findByRole('button', { name: '合成成片' }));
    expect(onCompose).toHaveBeenCalled();
    expect(screen.queryByRole('link', { name: '下载视频' })).toBeNull();
  });
});
