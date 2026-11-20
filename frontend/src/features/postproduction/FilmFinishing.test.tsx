// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { FilmFinishing } from './FilmFinishing';
import { defaultMoment, isNeutralGrade, lastMoment, neutralGrade, signed, type FinishingView } from './finishingSettings';
import { PostProductionStudio } from './PostProductionStudio';
import type { StudioClip, StudioResponse } from './postProduction';

vi.mock('../workbench/TimelinePanel', () => ({ TimelinePanel: () => <p>完整剪辑台</p> }));

function clip(shot_uid: number, patch: Record<string, unknown> = {}): StudioClip {
  return {
    shot_id: shot_uid, shot_uid, scene_id: shot_uid < 3 ? 'S1' : 'S2', video_url: `/media/c${shot_uid}.mp4`, candidates: [], duration: 4,
    in: 0, out: null, muted: false, subtitle: '', voice_path: null, transition_in: null,
    review: { decision: 'pending', note: '', decided_at: null }, audio_source: 'native', native_available: true, ...patch,
  } as StudioClip;
}

function finishing(patch: Partial<FinishingView['value']> = {}, teaser = ''): FinishingView {
  return {
    value: {
      title: { animation: 'fade', background: null },
      subtitle: { size: 'medium', color: 'white', position: 'bottom', outline: 'normal' },
      color: { preset: 'none', brightness: 0, contrast: 0, saturation: 0, warmth: 0 },
      ending: { enabled: false, text: '' },
      ...patch,
    },
    options: {
      title_animations: ['fade', 'zoom', 'reveal'],
      subtitle: {
        sizes: ['small', 'medium', 'large'], positions: ['bottom', 'raised'], outlines: ['none', 'normal', 'bold'],
        colors: [{ id: 'white', rgb: [255, 255, 255] }, { id: 'pale_yellow', rgb: [255, 236, 150] }, { id: 'pale_cyan', rgb: [190, 236, 255] }],
      },
      color: {
        limit: 100, sliders: ['brightness', 'contrast', 'saturation', 'warmth'],
        presets: [
          { id: 'none', brightness: 0, contrast: 0, saturation: 0, warmth: 0 },
          { id: 'film', brightness: -4, contrast: 14, saturation: -12, warmth: 8 },
        ],
      },
      ending: { max_chars: 80, seconds: 3 },
    },
    ending_teaser: teaser,
  };
}

const CLIPS = [clip(1), clip(2), clip(3, { review: { decision: 'rejected', note: '', decided_at: null } })];

function show(view = finishing(), props: Partial<Parameters<typeof FilmFinishing>[0]> = {}) {
  const onChange = vi.fn();
  render(<div className="pp"><FilmFinishing view={view} clips={CLIPS} titleCard subtitles busy={false} onChange={onChange} {...props} /></div>);
  return onChange;
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('finishing sums', () => {
  it('knows a neutral grade, how to get back to one, and how a slider reads', () => {
    const sliders = finishing().options.color.sliders;
    expect(isNeutralGrade(finishing().value.color, sliders)).toBe(true);
    expect(isNeutralGrade({ ...finishing().value.color, warmth: -3 }, sliders)).toBe(false);
    expect(neutralGrade(sliders)).toEqual({ brightness: 0, contrast: 0, saturation: 0, warmth: 0 });
    expect([signed(12), signed(0), signed(-30)]).toEqual(['+12', '0', '-30']);
  });

  it('starts a title frame in the middle of the clip and stops short of its end', () => {
    expect([defaultMoment(4), defaultMoment(5.25), defaultMoment(null)]).toEqual([2, 2.6, 0]);
    expect([lastMoment(4), lastMoment(0.05), lastMoment(null)]).toEqual([3.9, 0, 0]);
  });
});

describe('FilmFinishing', () => {
  it('shows the four groups with today’s look as the starting point', () => {
    show();
    const panel = screen.getByRole('region', { name: '成片精修' });
    for (const name of ['片名卡', '字幕样式', '全片调色', '片尾卡']) expect(within(panel).getByRole('group', { name })).toBeTruthy();
    expect(within(panel).getByRole('radio', { name: '淡入' }).getAttribute('aria-checked')).toBe('true');
    expect((within(panel).getByLabelText('底图') as HTMLSelectElement).value).toBe('');
    expect((within(panel).getByLabelText('字号') as HTMLSelectElement).value).toBe('medium');
    expect((within(panel).getByLabelText('位置') as HTMLSelectElement).value).toBe('bottom');
    expect(within(panel).getByRole('button', { name: '原片' }).getAttribute('aria-pressed')).toBe('true');
    for (const name of ['亮度', '对比度', '饱和度', '冷暖']) expect((within(panel).getByRole('slider', { name: new RegExp(name) }) as HTMLInputElement).value).toBe('0');
    expect((within(panel).getByRole('button', { name: '重置' }) as HTMLButtonElement).disabled).toBe(true);
    expect(within(panel).getByRole('switch', { name: '片尾卡' }).getAttribute('aria-checked')).toBe('false');
    expect(panel.querySelector('video')).toBeNull();
  });

  it('sends the chosen title animation', async () => {
    const onChange = show();
    await userEvent.click(screen.getByRole('radio', { name: '逐字出现' }));
    expect(onChange).toHaveBeenCalledWith({ title: { animation: 'reveal' } }, '片名卡');
    await userEvent.click(screen.getByRole('radio', { name: '淡入' }));
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it('offers the shots in the cut as the title frame and starts in the middle of the one picked', async () => {
    const onChange = show();
    const picker = screen.getByLabelText('底图') as HTMLSelectElement;
    expect([...picker.options].map(option => option.textContent)).toEqual(['默认深色底', 'S1 · 镜头 1', 'S1 · 镜头 2']);
    await userEvent.selectOptions(picker, '2');
    expect(onChange).toHaveBeenCalledWith({ title: { background: { shot_id: 2, shot_uid: 2, at: 2 } } }, '片名卡');
  });

  it('shows the picked frame, lets the moment be moved by keyboard, and goes back to the plain card', async () => {
    const onChange = show(finishing({ title: { animation: 'zoom', background: { shot_uid: 2, shot_id: 2, at: 1.5 } } }));
    const panel = screen.getByRole('region', { name: '成片精修' });
    const preview = panel.querySelector('video') as HTMLVideoElement;
    expect(preview.getAttribute('src')).toMatch(/\/media\/c2\.mp4$/);
    expect(preview.currentTime).toBe(1.5);
    const moment = within(panel).getByRole('slider', { name: /取这一镜的第几秒/ }) as HTMLInputElement;
    expect([moment.value, moment.max]).toEqual(['1.5', '3.9']);
    fireEvent.change(moment, { target: { value: '2.4' } });
    expect(within(panel).getByText('2.4 秒')).toBeTruthy();
    expect(preview.currentTime).toBe(2.4);
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.keyUp(moment, { key: 'ArrowRight' });
    expect(onChange).toHaveBeenCalledWith({ title: { background: { shot_id: 2, shot_uid: 2, at: 2.4 } } }, '片名卡');
    await userEvent.selectOptions(within(panel).getByLabelText('底图'), '');
    expect(onChange).toHaveBeenLastCalledWith({ title: { background: null } }, '片名卡');
  });

  it('says so when the title card or the subtitles are switched off', () => {
    show(finishing(), { titleCard: false, subtitles: false });
    expect(screen.getByText(/片名卡现在是关的/)).toBeTruthy();
    expect(screen.getByText(/嵌入字幕现在是关的/)).toBeTruthy();
  });

  it('sends one subtitle choice at a time', async () => {
    const onChange = show();
    await userEvent.selectOptions(screen.getByLabelText('颜色'), 'pale_yellow');
    expect(onChange).toHaveBeenLastCalledWith({ subtitle: { color: 'pale_yellow' } }, '字幕样式');
    await userEvent.selectOptions(screen.getByLabelText('位置'), 'raised');
    expect(onChange).toHaveBeenLastCalledWith({ subtitle: { position: 'raised' } }, '字幕样式');
    await userEvent.selectOptions(screen.getByLabelText('描边'), 'bold');
    expect(onChange).toHaveBeenLastCalledWith({ subtitle: { outline: 'bold' } }, '字幕样式');
    expect([...(screen.getByLabelText('字号') as HTMLSelectElement).options].map(option => option.textContent)).toEqual(['小', '中', '大']);
  });

  it('applies a preset, commits a slider when it is let go, and resets the grade', async () => {
    const onChange = show(finishing({ color: { preset: 'custom', brightness: 0, contrast: 20, saturation: 0, warmth: -10 } }));
    expect(screen.getByText('+20')).toBeTruthy();
    expect(screen.getByText('-10')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: '电影感' }));
    expect(onChange).toHaveBeenLastCalledWith({ color: { preset: 'film' } }, '全片调色');
    const saturation = screen.getByRole('slider', { name: /饱和度/ });
    fireEvent.change(saturation, { target: { value: '-35' } });
    expect(screen.getByText('-35')).toBeTruthy();
    expect(onChange).toHaveBeenCalledTimes(1);
    fireEvent.pointerUp(saturation);
    expect(onChange).toHaveBeenLastCalledWith({ color: { saturation: -35 } }, '全片调色');
    const reset = screen.getByRole('button', { name: '重置' }) as HTMLButtonElement;
    expect(reset.disabled).toBe(false);
    await userEvent.click(reset);
    expect(onChange).toHaveBeenLastCalledWith({ color: { brightness: 0, contrast: 0, saturation: 0, warmth: 0 } }, '全片调色');
  });

  it('pre-fills the ending card from the teaser the first time it is switched on, by keyboard too', async () => {
    const onChange = show(finishing({}, '宫门紧闭，她一个人回来了。'));
    const toggle = screen.getByRole('switch', { name: '片尾卡' });
    toggle.focus();
    await userEvent.keyboard(' ');
    expect(onChange).toHaveBeenLastCalledWith({ ending: { enabled: true, text: '宫门紧闭，她一个人回来了。' } }, '片尾卡');
  });

  it('keeps the user’s own line, saves an edit when the field is left, and never adds wording of its own', async () => {
    const onChange = show(finishing({ ending: { enabled: true, text: '明晚见' } }, '宫门紧闭，她一个人回来了。'));
    const field = screen.getByLabelText('片尾文字') as HTMLInputElement;
    expect(field.value).toBe('明晚见');
    expect(field.maxLength).toBe(80);
    await userEvent.clear(field);
    await userEvent.type(field, '  周五见  ');
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.tab();
    expect(onChange).toHaveBeenLastCalledWith({ ending: { text: '周五见' } }, '片尾卡');
    await userEvent.click(screen.getByRole('button', { name: '填入下集预告' }));
    expect(onChange).toHaveBeenLastCalledWith({ ending: { text: '宫门紧闭，她一个人回来了。' } }, '片尾卡');
    await userEvent.click(screen.getByRole('switch', { name: '片尾卡' }));
    expect(onChange).toHaveBeenLastCalledWith({ ending: { enabled: false } }, '片尾卡');
  });

  it('has no ending line and no teaser button when the episode has no teaser', () => {
    show();
    expect((screen.getByLabelText('片尾文字') as HTMLInputElement).value).toBe('');
    expect(screen.queryByRole('button', { name: '填入下集预告' })).toBeNull();
  });

  it('holds every control while an edit is being saved', () => {
    show(finishing(), { busy: true });
    const panel = screen.getByRole('region', { name: '成片精修' });
    const controls = [...panel.querySelectorAll<HTMLButtonElement | HTMLInputElement | HTMLSelectElement>('button, input, select')];
    expect(controls.length).toBeGreaterThan(12);
    expect(controls.every(control => control.disabled)).toBe(true);
  });
});

describe('FilmFinishing in the studio', () => {
  const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => data }) as Response;

  function studio(post: Partial<NonNullable<StudioResponse['post']>> = {}): StudioResponse {
    return {
      task_id: 't1',
      timeline: {
        title: { text: '雪夜', seconds: 2.6 }, revision: 4, clips: CLIPS,
        bgm: { source: 'none', path: null, url: null, library_id: null, name: null, volume: 0.16, duck: true, start: 0 },
      } as StudioResponse['timeline'],
      summary: { clips: 3, included: 2, seconds: 10.6, revision: 4 },
      bgm_library: [],
      acceptance: [],
      post: {
        settings: { transitions: true, dialogue: true, subtitles: true, title_card: true },
        tension: [], scene_markers: [], estimated_bytes: 1000, film_versions: [], shots: [], ...post,
      },
    };
  }

  function open(data: StudioResponse) {
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(async () => ok(data));
    vi.stubGlobal('fetch', fetchMock);
    render(<PostProductionStudio taskId="t1" filmUrl="/media/film.mp4" filmKey="k" onRegenerateSound={vi.fn()} onCompose={vi.fn()} onRendered={vi.fn()} />);
    return fetchMock;
  }

  it('saves a finishing edit through the same settings operation as the switches', async () => {
    const fetchMock = open(studio({ finishing: finishing() }));
    await userEvent.click(await screen.findByRole('radio', { name: '缓慢推近' }));
    await waitFor(() => {
      const edits = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/timeline/ops')).map(([, init]) => JSON.parse(String(init?.body)));
      expect(edits).toEqual([{ operation: 'settings', settings: { finishing: { title: { animation: 'zoom' } } } }]);
    });
    expect(await screen.findByText('片名卡已更新，重新合成后生效。')).toBeTruthy();
    expect(screen.getAllByRole('switch')).toHaveLength(6);
  });

  it('is left out when the backend sends no finishing', async () => {
    open(studio());
    await screen.findByRole('region', { name: '剪辑合成师' });
    expect(screen.queryByRole('region', { name: '成片精修' })).toBeNull();
    expect(screen.getAllByRole('switch')).toHaveLength(5);
  });
});
