// @vitest-environment jsdom
import { useEffect } from 'react';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { StagePlan } from '../../spatial/spatialTypes';
import type { CompareRendererProps } from '../three/CompareRenderer';
import { CameraComparePanel } from './CameraComparePanel';

// The canvas is three.js; here a stand-in hands the panel a renderer whose pictures are strings.
const renderer = vi.hoisted(() => ({
  renderThumbnails: vi.fn(),
  cancel: vi.fn(),
  mounted: vi.fn(),
}));
vi.mock('../three/CompareRenderer', () => ({
  default: function MockCompareRenderer({ plan, shot, aspect, onReady }: CompareRendererProps) {
    useEffect(() => {
      renderer.mounted({ revision: plan.revision, shotId: shot?.shot_id, aspect });
      onReady?.({ renderThumbnails: renderer.renderThumbnails, cancel: renderer.cancel });
      return () => onReady?.(null);
    }, [aspect, onReady, plan.revision, shot?.shot_id]);
    return null;
  },
}));

const ALT = { ...PLAN.cameras[0], id: 'alt-01-01', label: '01 建立 · 过肩', lens_mm: 50 };
const ALT2 = { ...PLAN.cameras[0], id: 'alt-01-02', label: '01 建立 · 俯拍', lens_mm: 35 };
const WITH_CANDIDATES: StagePlan = {
  ...PLAN,
  cameras: [...PLAN.cameras, ALT, ALT2],
  shots: [{ ...PLAN.shots[0], alt_camera_ids: ['alt-01-01', 'alt-01-02'] }, PLAN.shots[1]],
};

const sleep = (ms: number) => new Promise(resolve => { setTimeout(resolve, ms); });
const names = (strip: HTMLElement) => within(strip).getAllByRole('listitem').map(card => card.querySelector('strong')?.textContent);

describe('CameraComparePanel', () => {
  const onCommit = vi.fn();
  const onSelect = vi.fn();
  const onAddPreset = vi.fn();
  const onClose = vi.fn();
  const panel = (props: Partial<Parameters<typeof CameraComparePanel>[0]> = {}) => (
    <CameraComparePanel
      plan={WITH_CANDIDATES} shot={WITH_CANDIDATES.shots[0]} hidden={[]} revision={3} selection={[]} editable
      onCommit={onCommit} onSelect={onSelect} onAddPreset={onAddPreset} onClose={onClose} {...props}
    />
  );

  beforeEach(() => {
    onCommit.mockClear();
    onSelect.mockClear();
    onAddPreset.mockClear();
    onClose.mockClear();
    renderer.mounted.mockClear();
    renderer.cancel.mockClear();
    renderer.renderThumbnails.mockReset();
    renderer.renderThumbnails.mockImplementation((cameras: Array<{ id: string }>, onEach?: (id: string, url: string) => void) => {
      const made = Object.fromEntries(cameras.map(camera => [camera.id, `data:image/jpeg;base64,${camera.id}`]));
      cameras.forEach(camera => onEach?.(camera.id, made[camera.id]));
      return Promise.resolve(made);
    });
  });

  afterEach(cleanup);

  it('lists the filming lens first, then the candidates, each with its badge, focal length and picture', async () => {
    render(panel());
    const strip = screen.getByRole('region', { name: '机位对比' });
    expect(within(strip).getByRole('heading').textContent).toContain('第 1 镜 · 3 个机位');
    expect(names(strip)).toEqual(['01 建立', '01 建立 · 过肩', '01 建立 · 俯拍']);
    const cards = within(strip).getAllByRole('listitem');
    expect(within(cards[0]).getByText('主机位')).toBeTruthy();
    expect(within(cards[0]).getByText('28mm')).toBeTruthy();
    expect(within(cards[1]).getByText('候选')).toBeTruthy();
    expect(within(cards[1]).getByText('50mm')).toBeTruthy();
    // The canvas arrives lazily; once it has, the cards say they are waiting for it.
    expect(await within(cards[0]).findByText('生成中…')).toBeTruthy();

    // One request, with the cameras in the order they are shown; the pictures land on their cards.
    await waitFor(() => expect(renderer.renderThumbnails).toHaveBeenCalledTimes(1));
    expect((renderer.renderThumbnails.mock.calls[0][0] as Array<{ id: string }>).map(camera => camera.id)).toEqual(['cam-01', 'alt-01-01', 'alt-01-02']);
    expect((await within(cards[1]).findByRole('img', { name: '01 建立 · 过肩 的画面' })).getAttribute('src')).toBe('data:image/jpeg;base64,alt-01-01');
    expect(within(strip).getByRole('status').textContent).toBe('');
    // The renderer draws the frame that would be filmed: the plan's delivery aspect.
    expect(renderer.mounted).toHaveBeenCalledWith({ revision: 3, shotId: 1, aspect: 9 / 16 });
  });

  it('promotes, removes and selects from the cards; the filming lens cannot be promoted or removed', async () => {
    render(panel());
    const cards = within(screen.getByRole('region', { name: '机位对比' })).getAllByRole('listitem');
    expect(within(cards[0]).queryByRole('button', { name: /使用此机位/ })).toBeNull();
    expect(within(cards[0]).queryByRole('button', { name: /^删除/ })).toBeNull();

    await userEvent.click(within(cards[2]).getByRole('button', { name: '使用此机位 01 建立 · 俯拍' }));
    expect(onCommit).toHaveBeenCalledWith({ label: '设为主机位', operations: [{ op: 'use_camera', shot_id: 1, camera_id: 'alt-01-02' }] });
    await userEvent.click(within(cards[1]).getByRole('button', { name: '删除 01 建立 · 过肩' }));
    expect(onCommit).toHaveBeenCalledWith({ label: '删除候选机位', operations: [{ op: 'remove_camera', camera_id: 'alt-01-01' }], barrier: true });
    await userEvent.click(within(cards[1]).getByRole('button', { name: '选中 01 建立 · 过肩' }));
    expect(onSelect).toHaveBeenCalledWith({ kind: 'camera', id: 'alt-01-01' }, false);
    await userEvent.click(screen.getByRole('button', { name: '关闭机位对比' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('marks the selected lens and keeps the edit buttons off while the stage is read-only', () => {
    render(panel({ selection: [{ kind: 'camera-target', id: 'alt-01-01' }], editable: false }));
    const cards = within(screen.getByRole('region', { name: '机位对比' })).getAllByRole('listitem');
    expect(cards[1].getAttribute('aria-current')).toBe('true');
    expect(within(cards[1]).getByRole('button', { name: /^选中/ }).getAttribute('aria-pressed')).toBe('true');
    expect(within(cards[1]).getByRole('button', { name: /使用此机位/ })).toHaveProperty('disabled', true);
    expect(within(cards[1]).getByRole('button', { name: /^删除/ })).toHaveProperty('disabled', true);
    expect(within(screen.getByRole('group', { name: '快速添加候选机位' })).getByRole('button', { name: '正面' })).toHaveProperty('disabled', true);
  });

  it('asks for thumbnails once per revision and shot, and cancels a run the plan has overtaken', async () => {
    const { rerender } = render(panel());
    await waitFor(() => expect(renderer.renderThumbnails).toHaveBeenCalledTimes(1));

    // The playhead redraws the plan without a new revision: no new pictures.
    rerender(panel({ plan: { ...WITH_CANDIDATES, actors: [...WITH_CANDIDATES.actors] } }));
    await sleep(450);
    expect(renderer.renderThumbnails).toHaveBeenCalledTimes(1);

    rerender(panel({ revision: 4 }));
    expect(renderer.cancel).toHaveBeenCalled();
    await waitFor(() => expect(renderer.renderThumbnails).toHaveBeenCalledTimes(2));

    // A quick pair of edits is one redraw, after the last of them.
    rerender(panel({ revision: 5 }));
    rerender(panel({ revision: 6 }));
    await waitFor(() => expect(renderer.renderThumbnails).toHaveBeenCalledTimes(3));
    await sleep(450);
    expect(renderer.renderThumbnails).toHaveBeenCalledTimes(3);

    rerender(panel({ revision: 6, shot: WITH_CANDIDATES.shots[1] }));
    await waitFor(() => expect(renderer.renderThumbnails).toHaveBeenCalledTimes(4));
    expect((renderer.renderThumbnails.mock.calls[3][0] as Array<{ id: string }>).map(camera => camera.id)).toEqual(['cam-02']);
  });

  it('says what went wrong when the renderer cannot draw, but stays usable', async () => {
    renderer.renderThumbnails.mockImplementation(() => Promise.reject(new Error('图形上下文已中断')));
    render(panel());
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('图形上下文已中断'));
    const cards = within(screen.getByRole('region', { name: '机位对比' })).getAllByRole('listitem');
    expect(within(cards[0]).getByText('暂无缩略图')).toBeTruthy();
    expect(within(cards[1]).getByRole('button', { name: /使用此机位/ })).toHaveProperty('disabled', false);
  });

  it('explains candidates and offers the quick angles when the shot has none', async () => {
    render(panel({ plan: PLAN, shot: PLAN.shots[0] }));
    const strip = screen.getByRole('region', { name: '机位对比' });
    expect(names(strip)).toEqual(['01 建立']);
    expect(within(strip).getByText(/候选机位是同一镜的备选镜头/)).toBeTruthy();
    const quick = within(strip).getByRole('group', { name: '快速添加候选机位' });
    expect(within(quick).getAllByRole('button').map(button => button.textContent)).toEqual(['正面', '侧面', '过肩', '俯拍', '仰拍', '特写']);
    await userEvent.click(within(quick).getByRole('button', { name: '过肩' }));
    expect(onAddPreset).toHaveBeenCalledWith('over_shoulder');
  });

  it('has nothing to compare without a shot', () => {
    render(panel({ shot: undefined }));
    expect(screen.getByText('本场还没有镜头。')).toBeTruthy();
    expect(screen.queryByRole('list')).toBeNull();
    expect(renderer.mounted).not.toHaveBeenCalled();
  });
});
