// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { FilmPreview } from './canvasFilmApi';
import { CanvasFilmDialog } from './CanvasFilmDialog';

const api = vi.hoisted(() => ({ previewFilm: vi.fn(), buildFilm: vi.fn() }));
vi.mock('./canvasFilmApi', async importOriginal => ({ ...await importOriginal<typeof import('./canvasFilmApi')>(), ...api }));

const PREVIEW: FilmPreview = {
  version: 4,
  shots: [
    { node_id: 'c1', label: 'E1S01 镜1 视频', scene: 'E1S01', shot: 1, seconds: 5, lines: '林晚：有人吗？' },
    { node_id: 'c2', label: 'E1S01 镜2 视频', scene: 'E1S01', shot: 2, seconds: 8, lines: '' },
  ],
  voiced: 1, music: false, music_available: true,
  missing: { frames: 1, clips: 2, voices: 1, music: 0 }, to_run: 5,
};

function open(props: Partial<Parameters<typeof CanvasFilmDialog>[0]> = {}) {
  const handlers = { prepare: vi.fn(async () => 4), onBuilt: vi.fn(), onClose: vi.fn() };
  render(<CanvasFilmDialog projectId="p" canvasId="main" clientId="w1" selectedClips={[]} {...handlers} {...props} />);
  return handlers;
}

afterEach(() => {
  cleanup();
  api.previewFilm.mockReset();
  api.buildFilm.mockReset();
});

describe('one-click film', () => {
  it('saves the canvas, then lists the shots in order with what is still to make', async () => {
    api.previewFilm.mockResolvedValue(PREVIEW);
    const { prepare } = open();
    await screen.findByText('2 个镜头，约 13 秒');
    expect(prepare).toHaveBeenCalled();
    expect(screen.getAllByRole('listitem').map(item => item.textContent)).toEqual(['E1S01 镜1 视频 5 秒林晚：有人吗？', 'E1S01 镜2 视频 8 秒']);
    expect(screen.getByText('还要生成：首帧 1 个、视频 2 个、配音 1 条、配乐 0 条，最后合成成片。')).toBeTruthy();
    expect(api.previewFilm).toHaveBeenLastCalledWith('p', 'main', { nodeIds: [], voices: true, music: false, musicPrompt: '' }, expect.anything());
  });

  it('asks again when an option changes, and can use only the selected clips', async () => {
    api.previewFilm.mockResolvedValue(PREVIEW);
    open({ selectedClips: ['c2'] });
    await screen.findByText('2 个镜头，约 13 秒');
    expect(api.previewFilm.mock.calls.at(-1)?.[2].nodeIds).toEqual(['c2']);
    fireEvent.click(screen.getByLabelText('只用选中的 1 个视频节点'));
    fireEvent.click(screen.getByLabelText('加配乐'));
    fireEvent.change(screen.getByLabelText('配乐要求'), { target: { value: '悬疑弦乐' } });
    await waitFor(() => expect(api.previewFilm.mock.calls.at(-1)?.[2]).toEqual({ nodeIds: [], voices: true, music: true, musicPrompt: '悬疑弦乐' }));
  });

  it('builds the film on the saved version and hands the nodes to run back', async () => {
    api.previewFilm.mockResolvedValue(PREVIEW);
    const built = { version: 5, compose: 'f', run: ['i1', 'c1', 'c2', 'v1', 'f'], shots: 2, voiced: 1, music: false, missing: PREVIEW.missing, created: ['f', 'v1'] };
    api.buildFilm.mockResolvedValue(built);
    const { onBuilt } = open();
    fireEvent.click(await screen.findByRole('button', { name: '搭好并估价（5 个节点）' }));
    await waitFor(() => expect(onBuilt).toHaveBeenCalled());
    expect(api.buildFilm).toHaveBeenCalledWith('p', 'main', { nodeIds: [], voices: true, music: false, musicPrompt: '' }, 4, 'w1');
    expect(onBuilt).toHaveBeenCalledWith(built);
  });

  it('keeps the music on when the film already has music, until the person turns it off', async () => {
    api.previewFilm.mockResolvedValue({ ...PREVIEW, had_music: true });
    open();
    await waitFor(() => expect((screen.getByRole('checkbox', { name: /加配乐/ }) as HTMLInputElement).checked).toBe(true));
    await waitFor(() => expect(api.previewFilm.mock.calls.at(-1)?.[2].music).toBe(true));
    fireEvent.click(screen.getByRole('checkbox', { name: /加配乐/ }));
    await waitFor(() => expect(api.previewFilm.mock.calls.at(-1)?.[2].music).toBe(false));
    expect((screen.getByRole('checkbox', { name: /加配乐/ }) as HTMLInputElement).checked).toBe(false);
  });

  it('offers no music without a provider and shows why a film cannot be made', async () => {
    api.previewFilm.mockResolvedValue({ ...PREVIEW, music_available: false });
    open();
    await screen.findByText('2 个镜头，约 13 秒');
    expect((screen.getByRole('checkbox', { name: /加配乐/ }) as HTMLInputElement).disabled).toBe(true);
    cleanup();
    api.previewFilm.mockImplementation(async () => { throw new Error('画布上还没有视频节点'); });
    open();
    await screen.findByText('画布上还没有视频节点');
    expect((screen.getByRole('button', { name: /搭好并估价/ }) as HTMLButtonElement).disabled).toBe(true);
  });
});
