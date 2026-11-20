// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CanvasBatchTable } from './CanvasBatchTable';
import { CanvasBeefAppearancePanel } from './CanvasBeefAppearancePanel';
import { CanvasBeefConflictActions } from './CanvasBeefConflictActions';
import { CanvasBeefPromptEditor } from './CanvasBeefPromptEditor';
import { CanvasBeefReferencePanel } from './CanvasBeefReferencePanel';
import { CanvasBeefVersionPreview } from './CanvasBeefVersionPreview';
import { DEFAULT_APPEARANCE } from './canvasBeefAppearance';
import { applySuggestions } from './canvasBeefReferences';
import type { CanvasEdge, CanvasNode, RunAssessment } from './canvasTypes';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
const refuse = (status: number, detail: string) => ({ ok: false, status, json: async () => ({ detail }) }) as Response;
const node = (id: string, kind: CanvasNode['kind'], x = 0, payload: CanvasNode['payload'] = {}): CanvasNode => ({
  id, kind, track: 'freezone', x, y: 0, width: 100, height: 80, artifact_id: null, payload,
});
const OPTIONS = { modes: [{ id: 'expand', label: '扩展想法' }, { id: 'refine', label: '精修已有提示词' }, { id: 'references', label: '结合参考' }], text_models: ['deepseek-flash', 'qwen-max'], default_text_model: 'deepseek-flash' };
const RESULT = { prompt: '雨夜码头，林夏提灯，冷蓝主光', avoid: ['水印'], changes: ['补了光线'], assumptions: [], alternatives: ['另一版'], mode: 'expand', text_model: 'qwen-max' };

describe('CanvasBeefPromptEditor and optimizer', () => {
  it('edits, optimizes with the chosen model and adopts only on 采用', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => (init?.method === 'POST' ? ok(RESULT) : ok(OPTIONS)));
    const onApply = vi.fn();
    render(<CanvasBeefPromptEditor nodeId="n1" taskId="t1" medium="image" text="林夏 码头" onApply={onApply} onClose={() => undefined} />);
    const box = screen.getByRole('textbox', { name: '提示词' }) as HTMLTextAreaElement;
    expect(box.value).toBe('林夏 码头');
    fireEvent.click(screen.getByRole('button', { name: /优化/ }));
    const panel = await screen.findByRole('dialog', { name: '提示词优化' });
    await waitFor(() => expect(within(panel).getAllByRole('radio').length).toBe(3));
    expect((within(panel).getByRole('radio', { name: '结合参考' }) as HTMLInputElement).disabled).toBe(true);
    fireEvent.change(within(panel).getByRole('combobox'), { target: { value: 'qwen-max' } });
    fireEvent.click(within(panel).getByRole('button', { name: '开始优化' }));
    const edited = await within(panel).findByRole('textbox', { name: '优化后的提示词（可以再改）' }) as HTMLTextAreaElement;
    expect(edited.value).toBe(RESULT.prompt);
    expect(box.value).toBe('林夏 码头');
    const sent = JSON.parse(String(fetchMock.mock.calls.find(call => call[1]?.method === 'POST')![1]!.body));
    expect(sent).toMatchObject({ prompt: '林夏 码头', medium: 'image', mode: 'expand', text_model: 'qwen-max' });
    fireEvent.click(within(panel).getByRole('button', { name: '另一版' }));
    expect(edited.value).toBe('另一版');
    fireEvent.click(within(panel).getByRole('button', { name: '采用' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '提示词优化' })).toBeNull());
    expect(box.value).toBe('另一版');
    fireEvent.click(screen.getByRole('button', { name: '完成' }));
    expect(onApply).toHaveBeenCalledWith('另一版');
  });

  it('a failed optimization leaves the prompt as it was', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => (init?.method === 'POST' ? refuse(422, '模型的回答不是要求的格式，原提示词没有改动') : ok(OPTIONS)));
    render(<CanvasBeefPromptEditor nodeId="n1" taskId="t1" medium="video" text="追车" onApply={() => undefined} onClose={() => undefined} />);
    fireEvent.click(screen.getByRole('button', { name: /优化/ }));
    const panel = await screen.findByRole('dialog', { name: '提示词优化' });
    await waitFor(() => expect((within(panel).getByRole('button', { name: '开始优化' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(within(panel).getByRole('button', { name: '开始优化' }));
    expect((await within(panel).findByRole('alert')).textContent).toContain('原提示词没有改动');
    expect((within(panel).getByRole('button', { name: '采用' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('textbox', { name: '提示词' }) as HTMLTextAreaElement).value).toBe('追车');
  });

  it('grows from its corner with the arrow keys and starts again at the default size for another node', () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok(OPTIONS));
    const { rerender } = render(<CanvasBeefPromptEditor nodeId="n1" taskId="t1" medium="image" text="" onApply={() => undefined} onClose={() => undefined} />);
    const handle = screen.getByRole('slider', { name: '调整编辑框大小' });
    const before = handle.getAttribute('aria-valuetext');
    fireEvent.keyDown(handle, { key: 'ArrowDown' });
    expect(handle.getAttribute('aria-valuetext')).not.toBe(before);
    rerender(<CanvasBeefPromptEditor nodeId="n2" taskId="t1" medium="image" text="" onApply={() => undefined} onClose={() => undefined} />);
    expect(screen.getByRole('slider', { name: '调整编辑框大小' }).getAttribute('aria-valuetext')).toBe(before);
  });
});

describe('CanvasBatchTable', () => {
  const assessment = (decision: RunAssessment['decision'] = 'admitted') => ({
    decision, confirmations: [],
    nodes: [{ node_id: 'n1', label: '图片', problems: [], quote: 'generate' }],
    estimate: { items: 1, paid_items: 1, unpriced_items: 0, totals: [{ currency: 'CNY', cost: 0.25 }] },
  }) as unknown as RunAssessment;

  const props = () => {
    let id = 0;
    return {
      models: { image: ['seedream'], video: ['seedance'] }, defaults: { image: 'seedream', video: 'seedance' }, durations: [5, 10], maxCount: 4,
      originOf: () => ({ x: 0, y: 0 }), makeId: () => `n${++id}`,
      onCreate: vi.fn(async () => undefined), assess: vi.fn(async () => assessment()),
      start: vi.fn(async () => ({ status: 'started' as const, batch_id: 'b1' })), onClose: vi.fn(),
    };
  };

  it('closes on Escape', () => {
    const p = props();
    render(<CanvasBatchTable {...p} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(p.onClose).toHaveBeenCalledTimes(1);
  });

  it('creates only, without spending', async () => {
    const p = props();
    render(<CanvasBatchTable {...p} />);
    const create = screen.getByRole('button', { name: '只放上画布' }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);
    fireEvent.change(screen.getByRole('textbox', { name: '第 1 行 提示词' }), { target: { value: '雨夜码头' } });
    fireEvent.click(create);
    expect((await screen.findByRole('status')).textContent).toBe('已放上画布 1 个节点，还没有生成');
    expect(p.onCreate).toHaveBeenCalledTimes(1);
    expect(p.assess).not.toHaveBeenCalled();
    expect(p.start).not.toHaveBeenCalled();
  });

  it('pastes rows, shows the total and runs only after the confirmation', async () => {
    const p = props();
    render(<CanvasBatchTable {...p} />);
    fireEvent.change(screen.getByRole('textbox', { name: '从表格粘贴' }), { target: { value: '雨夜码头\t开场\t视频\t10\n灯下的脸' } });
    fireEvent.click(screen.getByRole('button', { name: '粘贴成行' }));
    expect(screen.getAllByRole('row')).toHaveLength(3);
    fireEvent.click(screen.getByRole('button', { name: '放上画布并生成' }));
    const confirm = await screen.findByRole('group', { name: '确认生成' });
    expect(within(confirm).getByText('预计合计 0.25 CNY')).toBeTruthy();
    const created = (p.onCreate.mock.calls[0] as unknown as [CanvasNode[]])[0];
    expect(created.map(item => [item.kind, item.payload.prompt, item.payload.params?.durationSeconds])).toEqual([['video_gen', '雨夜码头', 10], ['image_gen', '灯下的脸', undefined]]);
    expect(p.start).not.toHaveBeenCalled();
    fireEvent.click(within(confirm).getByRole('button', { name: '确认生成' }));
    expect((await screen.findByRole('status')).textContent).toBe('已开始生成 2 个节点');
    expect(p.start).toHaveBeenCalledWith(['n1', 'n2'], []);
  });
});

describe('CanvasBeefReferencePanel', () => {
  it('suggests first and last frames and applies them', () => {
    const clip = node('v', 'video_gen', 500);
    const nodes = [clip, node('a', 'image_gen', 0, { title: '开场图' }), node('b', 'image_gen', 200, { title: '结尾图' })];
    const edges: CanvasEdge[] = [
      { id: 'e1', source: 'a', target: 'v', kind: 'reference', payload: {} },
      { id: 'e2', source: 'b', target: 'v', kind: 'reference', payload: {} },
    ];
    const onApply = vi.fn();
    render(<CanvasBeefReferencePanel target={clip} nodes={nodes} edges={edges} limits={{ images: 9, videos: 3, audios: 3 }} onApply={onApply} />);
    expect(screen.getByText('「开场图」：参考图 → 首帧')).toBeTruthy();
    expect(screen.getByText('「结尾图」：参考图 → 尾帧')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '按建议设置' }));
    expect(applySuggestions(edges, onApply.mock.calls[0][0]).map((item: CanvasEdge) => item.payload.role)).toEqual(['first_frame', 'last_frame']);
  });

  it('stays out of the way when there is nothing to say', () => {
    const { container } = render(<CanvasBeefReferencePanel target={node('v', 'video_gen')} nodes={[]} edges={[]} limits={{ images: 9, videos: 3, audios: 3 }} onApply={() => undefined} />);
    expect(container.innerHTML).toBe('');
  });
});

describe('CanvasBeefVersionPreview', () => {
  it('reads the version, shows what restoring would change and restores only on request', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok({
      project_id: 'p1', version: 3, created_at: '', nodes: [node('a', 'note'), node('d', 'note', 300)], edges: [],
    }));
    const onRestore = vi.fn();
    render(<CanvasBeefVersionPreview projectId="p1" canvasId="main" version={3} current={{ nodes: [node('a', 'note'), node('c', 'note')], edges: [] }}
      onRestore={onRestore} onClose={() => undefined} />);
    expect(await screen.findByText('恢复后会多出 1 个现在没有的节点')).toBeTruthy();
    expect(screen.getByText('会去掉 1 个现在才有的节点')).toBeTruthy();
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/studio/projects/p1/canvas/versions/3?canvas_id=main');
    expect(onRestore).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '恢复这一版' }));
    expect(onRestore).toHaveBeenCalledWith(3);
  });

  it('closes on Escape', () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok({ project_id: 'p1', version: 2, created_at: '', nodes: [], edges: [] }));
    const onClose = vi.fn();
    render(<CanvasBeefVersionPreview projectId="p1" canvasId="main" version={2} current={{ nodes: [], edges: [] }} onRestore={() => undefined} onClose={onClose} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('CanvasBeefConflictActions', () => {
  it('says what an overwrite replaces and saves against that version', async () => {
    const calls: Array<{ method: string; body?: unknown }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => {
      calls.push({ method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (init?.method === 'PUT') return ok({ project_id: 'p1', version: 8, created_at: '', nodes: [], edges: [] });
      return ok({ project_id: 'p1', version: 7, created_at: '', nodes: [node('x', 'note'), node('y', 'note')], edges: [] });
    });
    const onOverwritten = vi.fn();
    render(<CanvasBeefConflictActions projectId="p1" canvasId="main" mine={{ nodes: [node('m', 'note')], edges: [] }} onOverwritten={onOverwritten} />);
    fireEvent.click(screen.getByRole('button', { name: '用我的覆盖' }));
    const ask = await screen.findByRole('group', { name: '确认覆盖' });
    expect(ask.textContent).toContain('将用我的 1 个节点替换服务器上的第 7 版（2 个节点）');
    fireEvent.click(within(ask).getByRole('button', { name: '确认覆盖' }));
    await waitFor(() => expect(onOverwritten).toHaveBeenCalled());
    const put = calls.find(call => call.method === 'PUT');
    expect(put?.body).toMatchObject({ expected_version: 7 });
  });
});

describe('CanvasBeefAppearancePanel', () => {
  it('applies a custom colour once it is a valid HEX and saves a default for new canvases', () => {
    const onChange = vi.fn();
    const { rerender } = render(<CanvasBeefAppearancePanel canvasId="b1" accountId="u1" value={DEFAULT_APPEARANCE} onChange={onChange} />);
    fireEvent.click(screen.getByRole('radio', { name: '自定义' }));
    const custom = onChange.mock.calls[0][0];
    expect(custom.theme).toBe('custom');
    rerender(<CanvasBeefAppearancePanel canvasId="b1" accountId="u1" value={custom} onChange={onChange} />);
    const hex = screen.getAllByRole('textbox')[0] as HTMLInputElement;
    fireEvent.change(hex, { target: { value: '#12' } });
    expect(onChange).toHaveBeenCalledTimes(1);
    fireEvent.change(hex, { target: { value: '123' } });
    expect(onChange.mock.calls[1][0].custom).toMatchObject({ background: '#112233', brightness: 0 });
    expect(JSON.parse(localStorage.getItem('canvas.appearance.b1')!).custom.background).toBe('#112233');
    fireEvent.click(screen.getByRole('button', { name: '保存为默认' }));
    expect(screen.getByRole('status').textContent).toBe('新建的画布会用这套外观');
    expect(localStorage.getItem('canvas.appearance.default.u1')).toBeTruthy();
  });
});
