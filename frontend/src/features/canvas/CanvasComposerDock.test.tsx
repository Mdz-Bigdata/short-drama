// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CanvasComposerDock } from './CanvasComposerDock';
import { CanvasComposerHost } from './CanvasComposerHost';
import { CanvasContext, type CanvasActions } from './canvasContext';
import type { SurfaceHandle } from './CanvasSurface';
import type { CanvasNode, RunAssessment, RunOptions } from './canvasTypes';

const assessRun = vi.hoisted(() => vi.fn());
vi.mock('./canvasApi', () => ({ assessRun }));

const OPTIONS: RunOptions = {
  models: { image: 'seedream', video: 'seedance', audio: 'local-tts' },
  enabled: { image: ['seedream', 'other-image'], video: ['seedance'], audio: [] },
  video_durations: [5, 10],
  versions: { max: 4, kinds: ['image_gen', 'video_gen'] },
  kinds: { image_gen: { runnable: true, reason: '' }, video_gen: { runnable: true, reason: '' }, audio_gen: { runnable: true, reason: '', modes: { speech: true, music: false, sfx: false } } },
};

const ASSESSMENT: RunAssessment = {
  decision: 'admitted', confirmations: [],
  nodes: [{ node_id: 'n', kind: 'image_gen', label: '图', medium: 'image', model: 'seedream', quote: 'generate', paid: true, problems: [], requested_seconds: 0, scripted_seconds: 0, estimate: { priced: true, cost: 1.8, currency: 'CNY' }, versions: 3 }],
  estimate: { items: 1, paid_items: 1, unpriced_items: 0, totals: [{ currency: 'CNY', cost: 1.8 }] },
};

function node(kind: CanvasNode['kind'], payload: CanvasNode['payload'] = {}): CanvasNode {
  return { id: 'n', kind, track: 'freezone', x: 100, y: 100, width: 300, height: 320, artifact_id: null, payload: { label: '雨夜', ...payload } };
}

function actions(over: Partial<CanvasActions> = {}): CanvasActions {
  return {
    taskId: 't', options: OPTIONS, shots: [], deskToken: 0, patch: vi.fn(), run: vi.fn(), cancel: vi.fn(), upload: vi.fn(), openDesk: vi.fn(), layOutBeats: vi.fn(), ...over,
  };
}

const PLACEMENT = { left: 20, top: 400, width: 560 };

function dock(target: CanvasNode, value: CanvasActions, props: Partial<Parameters<typeof CanvasComposerDock>[0]> = {}) {
  return render(
    <CanvasContext.Provider value={value}>
      <CanvasComposerDock node={target} quote={null} placement={PLACEMENT} collapsed={false} onToggle={vi.fn()} {...props} />
    </CanvasContext.Provider>,
  );
}

afterEach(cleanup);

describe('the composer dock', () => {
  it('edits the node\'s own prompt, as one undo step per run of typing', () => {
    const value = actions();
    dock(node('image_gen', { prompt: '雨夜的街' }), value);
    const prompt = screen.getByLabelText('生成栏：提示词') as HTMLTextAreaElement;
    expect(prompt.value).toBe('雨夜的街');
    fireEvent.change(prompt, { target: { value: '雨夜的街，霓虹' } });
    expect(value.patch).toHaveBeenCalledWith('n', { prompt: '雨夜的街，霓虹' }, 'prompt:n');
  });

  it('picks a model, a size and a count for a picture, keeping the other parameters', () => {
    const value = actions();
    dock(node('image_gen', { params: { size: '1024x1024' } }), value);
    fireEvent.change(screen.getByLabelText('生成栏：模型'), { target: { value: 'other-image' } });
    expect(value.patch).toHaveBeenLastCalledWith('n', { params: { size: '1024x1024', model: 'other-image' } }, undefined);
    fireEvent.change(screen.getByLabelText('生成栏：一次出几个'), { target: { value: '3' } });
    expect(value.patch).toHaveBeenLastCalledWith('n', { params: { size: '1024x1024', count: 3 } }, undefined);
    expect(within(screen.getByLabelText('生成栏：一次出几个')).getAllByRole('option')).toHaveLength(4);
  });

  it('offers the durations the clip model can render, and no count for a sound', () => {
    const value = actions();
    const { unmount } = dock(node('video_gen', { params: { durationSeconds: 5 } }), value);
    fireEvent.change(screen.getByLabelText('生成栏：时长'), { target: { value: '10' } });
    expect(value.patch).toHaveBeenLastCalledWith('n', { params: { durationSeconds: 10 } }, undefined);
    unmount();
    dock(node('audio_gen'), value);
    expect(screen.queryByLabelText('生成栏：一次出几个')).toBeNull();
    expect(screen.getByLabelText('生成栏：要合成的文本')).toBeTruthy();
    expect((within(screen.getByLabelText('生成栏：音频类型')).getByRole('option', { name: '配乐' }) as HTMLOptionElement).disabled).toBe(true);
  });

  it('runs the node from the button and from ⌘/Ctrl + Enter, and says how many it will make', () => {
    const value = actions();
    dock(node('image_gen', { prompt: '雨夜', params: { count: 3 } }), value);
    fireEvent.click(screen.getByRole('button', { name: '生成 3 个' }));
    fireEvent.keyDown(screen.getByLabelText('生成栏：提示词'), { key: 'Enter', ctrlKey: true });
    fireEvent.keyDown(screen.getByLabelText('生成栏：提示词'), { key: 'Enter' });
    expect(value.run).toHaveBeenCalledTimes(2);
    expect(value.run).toHaveBeenLastCalledWith(['n']);
  });

  it('cannot start a second run while one is going, shows the progress, and can withdraw a queued one', () => {
    const value = actions();
    const latest = { run_id: 'r', status: 'queued' as const, error: null, batch_id: 'b', versions: { total: 3, done: 1, failed: 0 } };
    dock(node('image_gen'), value, { latest });
    expect((screen.getByRole('button', { name: '生成' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('排队中 1/3')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '生成栏：取消排队' }));
    expect(value.cancel).toHaveBeenCalledWith(latest);
  });

  it('shows the quote it is given and folds to a small button', () => {
    const onToggle = vi.fn();
    const value = actions();
    const { rerender } = dock(node('image_gen'), value, { quote: { text: '参考费用约 1.8 CNY · 3 个结果', tone: 'cost', pending: false }, onToggle });
    expect(screen.getByRole('status').textContent).toBe('参考费用约 1.8 CNY · 3 个结果');
    fireEvent.click(screen.getByRole('button', { name: '收起生成栏' }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    rerender(
      <CanvasContext.Provider value={value}>
        <CanvasComposerDock node={node('image_gen')} quote={null} placement={PLACEMENT} collapsed onToggle={onToggle} />
      </CanvasContext.Provider>,
    );
    expect(screen.queryByLabelText('生成栏：提示词')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '展开生成栏' }));
    expect(onToggle).toHaveBeenCalledTimes(2);
  });
});

describe('the dock under the selected node', () => {
  const view = { view: { x: 0, y: 0, zoom: 1 }, size: { width: 1200, height: 800 } };
  const surface = { current: { subscribe: (listener: (view: typeof view.view, size: typeof view.size) => void) => { listener(view.view, view.size); return () => undefined; } } as unknown as SurfaceHandle };

  function host(target: CanvasNode | null, props: Partial<Parameters<typeof CanvasComposerHost>[0]> = {}) {
    return (
      <CanvasContext.Provider value={actions()}>
        <CanvasComposerHost surface={surface} node={target} projectId="p" canvasId="main" version={3} settled {...props} />
      </CanvasContext.Provider>
    );
  }

  beforeEach(() => {
    vi.useFakeTimers();
    assessRun.mockReset();
    assessRun.mockResolvedValue(ASSESSMENT);
    window.localStorage.clear();
  });
  afterEach(() => vi.useRealTimers());

  it('is drawn for one selected generator node, with the server\'s quote once the canvas is saved', async () => {
    render(host(node('image_gen', { prompt: '雨夜', params: { count: 3 } })));
    expect(screen.getByRole('group', { name: '生成栏：雨夜' })).toBeTruthy();
    expect(screen.getByRole('status').textContent).toBe('估价中…');
    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
    expect(assessRun).toHaveBeenCalledWith('p', 'main', ['n']);
    expect(screen.getByRole('status').textContent).toBe('参考费用约 1.8 CNY · 3 个结果');
  });

  it('waits for the save before it quotes, and asks again after the next one', async () => {
    const target = node('image_gen', { prompt: '雨夜' });
    const { rerender } = render(host(target, { settled: false }));
    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
    expect(assessRun).not.toHaveBeenCalled();
    expect(screen.getByRole('status').textContent).toBe('保存后估价');
    rerender(host(target, { settled: true, version: 4 }));
    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
    expect(assessRun).toHaveBeenCalledTimes(1);
    rerender(host(target, { settled: true, version: 5 }));
    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
    expect(assessRun).toHaveBeenCalledTimes(2);
  });

  it('is not drawn for a note, for no selection, or for a node out of sight', () => {
    const { rerender } = render(host(node('note')));
    expect(screen.queryByRole('group')).toBeNull();
    rerender(host(null));
    expect(screen.queryByRole('group')).toBeNull();
    rerender(host({ ...node('image_gen'), x: 9000 }));
    expect(screen.queryByRole('group')).toBeNull();
    expect(assessRun).not.toHaveBeenCalled();
  });

  it('remembers being folded, and asks for no quote while it is', async () => {
    const target = node('image_gen', { prompt: '雨夜' });
    const { unmount } = render(host(target));
    fireEvent.click(screen.getByRole('button', { name: '收起生成栏' }));
    unmount();
    assessRun.mockClear();
    render(host(target));
    expect(screen.getByRole('button', { name: '展开生成栏' })).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
    expect(assessRun).not.toHaveBeenCalled();
  });
});
