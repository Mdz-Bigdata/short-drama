// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { InteractiveStoryWorkspace } from './InteractiveStoryWorkspace';
import { blankChoice, blankSegment } from './graphOps';
import { StoryGraphCanvas } from './StoryGraphCanvas';
import type { MediaLibrary, PlaytestStats, StoryAnalysis, StoryGraph, StoryIssue, StoryRecord } from './storyTypes';

const BASE = 'http://localhost:8000/api/drama/t1/interactive-story';

function storyGraph(): StoryGraph {
  return {
    title: '雨夜来客', synopsis: '一封信', outline: ['开场'], start: 'a',
    variables: [{ id: 'trust', label: '信任', kind: 'number', initial: 0, min: null, max: null }],
    segments: [
      { ...blankSegment('a', 'scene', '开门', { x: 0, y: 0 }), narration: '门外有人。', choices: [
        { ...blankChoice('go', '开门', 'b'), effects: [{ var: 'trust', op: 'add', value: 2 }] },
        blankChoice('stay', '不开', 'b'),
      ] },
      { ...blankSegment('b', 'scene', '抉择', { x: 300, y: 0 }), choices: [
        { ...blankChoice('gold', '相信他', 'good'), condition: { var: 'trust', op: 'gte', value: 2 }, locked_hint: '信任不够' },
        blankChoice('leave', '离开', 'bad'),
      ] },
      { ...blankSegment('good', 'ending', '团圆', { x: 600, y: 0 }), ending_label: '好结局' },
      { ...blankSegment('bad', 'ending', '错过', { x: 600, y: 200 }), ending_label: '坏结局' },
    ],
  };
}

function analysisOf(extra: Partial<StoryAnalysis> = {}): StoryAnalysis {
  return {
    issues: [], errors: 0, warnings: 0, ready: true,
    paths: {
      paths: 3, complete_paths: 3, stuck_paths: 0, loop_cuts: 0, truncated: false, max_paths: 2000, loop_limit: 2, rate_method: 'enumeration',
      coverage: { segments_covered: 4, segments_total: 4, segments_ratio: 1, choices_covered: 4, choices_total: 4, choices_ratio: 1, endings_covered: 2, endings_total: 2, endings_ratio: 1 },
      endings: [
        { id: 'good', title: '团圆', label: '好结局', paths: 1, reach_rate: 0.25, min_minutes: 0.5, max_minutes: 0.5, avg_minutes: 0.5 },
        { id: 'bad', title: '错过', label: '坏结局', paths: 2, reach_rate: 0.75, min_minutes: 0.5, max_minutes: 0.5, avg_minutes: 0.5 },
      ],
      unfinished_rate: 0, minutes: { min: 0.5, max: 0.5, avg: 0.5 },
      routes: [{ key: 'k', ending_id: 'good', segments: ['a', 'b', 'good'], choices: ['go', 'gold'], seconds: 30, minutes: 0.5, probability: 0.25 }],
      stuck: [],
    },
    ...extra,
  };
}

const emptyStats: PlaytestStats = {
  runs: 0, completed: 0, timeouts: 0, choices: [], endings: [{ id: 'good', title: '团圆', count: 0 }, { id: 'bad', title: '错过', count: 0 }],
  endings_reached: 0, endings_total: 2, segments_played: 0, segments_total: 4, routes_played: 0, routes_total: 3, route_coverage: 0,
};

function recordOf(graph: StoryGraph | null, revision = 3): StoryRecord {
  return { revision, graph, updated_at: '', analysis: graph ? analysisOf() : null, stats: graph ? emptyStats : null };
}

type Handler = (url: string, init: RequestInit) => unknown;

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: async () => body, blob: async () => new Blob(['x']) } as unknown as Response;
}

/** Routes by "METHOD /suffix" under the story's base; the record below answers the plain GET and PUT. */
function mockApi(record: StoryRecord, overrides: Record<string, Handler> = {}) {
  const calls: Array<{ method: string; url: string; body: unknown }> = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    const method = init.method ?? 'GET';
    const suffix = (url.startsWith(BASE) ? url.slice(BASE.length) : url).split('?')[0];
    let body: unknown = init.body;
    if (typeof body === 'string') body = JSON.parse(body);
    calls.push({ method, url, body });
    const handler = overrides[`${method} ${suffix}`];
    if (handler) {
      const result = handler(url, init);
      return result instanceof Object && 'ok' in result ? result as Response : json(200, result);
    }
    if (method === 'GET' && suffix === '') return json(200, record);
    if (method === 'PUT' && suffix === '') {
      const sent = (body as { graph: StoryGraph }).graph;
      return json(200, { ...record, revision: record.revision + 1, graph: sent });
    }
    if (method === 'POST' && suffix === '/analyze') return json(200, analysisOf());
    if (method === 'POST' && suffix === '/playtest') return json(200, { ...emptyStats, runs: 1 });
    if (method === 'GET' && suffix === '/export/preview') return json(200, { ready: true, errors: [], media: [], inline_limit_bytes: 67108864 });
    return json(404, { detail: `no mock for ${method} ${suffix}` });
  });
  vi.stubGlobal('fetch', fetchMock);
  return calls;
}

const named = (calls: ReturnType<typeof mockApi>, method: string, suffix: string) => calls.filter(item => item.method === method && item.url.split('?')[0] === `${BASE}${suffix}`);

async function open(onClose = vi.fn()) {
  render(<InteractiveStoryWorkspace taskId="t1" onClose={onClose} />);
  await screen.findByRole('dialog', { name: '互动剧' });
  await waitFor(() => expect(screen.queryByText('正在加载…')).toBeNull());
  return onClose;
}

const tab = (name: string) => screen.getByRole('tab', { name: new RegExp(name) });

beforeEach(() => {
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('opening', () => {
  it('offers planning or a blank start on a project with no story', async () => {
    const calls = mockApi(recordOf(null, 0));
    await open();
    await userEvent.click(screen.getByRole('button', { name: /从空白开始/ }));
    expect(document.querySelectorAll('[data-segment]').length).toBe(2);
    expect(screen.getByText('有未保存的修改')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /保存/ }));
    await waitFor(() => expect(named(calls, 'PUT', '')).toHaveLength(1));
    expect(named(calls, 'PUT', '')[0].body).toMatchObject({ base_revision: 0, graph: { start: 's1' } });
  });

  it('shows the load failure and can retry', async () => {
    const failing = vi.fn(async () => json(500, { detail: '任务库不可用' }));
    vi.stubGlobal('fetch', failing);
    await open();
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', '任务库不可用');
    mockApi(recordOf(storyGraph()));
    await userEvent.click(screen.getByRole('button', { name: '重试' }));
    await screen.findByDisplayValue('雨夜来客');
  });

  it('asks before closing with unsaved edits, and only then', async () => {
    mockApi(recordOf(storyGraph()));
    const onClose = await open();
    await userEvent.click(screen.getByRole('button', { name: '关闭互动剧' }));
    expect(window.confirm).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByLabelText('故事标题'), { target: { value: '新名字' } });
    vi.mocked(window.confirm).mockReturnValue(false);
    await userEvent.click(screen.getByRole('button', { name: '关闭互动剧' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('renders hostile story text as text', async () => {
    const hostile = storyGraph();
    hostile.title = '<img src=x onerror=alert(1)>';
    hostile.segments[0].title = '<script>alert(1)</script>';
    hostile.segments[0].narration = '<img src=x onerror=alert(2)>';
    hostile.segments[0].choices[0].text = '<b>粗体</b>';
    mockApi(recordOf(hostile));
    await open();
    await userEvent.click(tab('试玩'));
    expect(document.querySelector('.istory img, .istory script, .istory b')).toBeNull();
    expect(within(screen.getByTestId('playtest-card')).getByText('<img src=x onerror=alert(2)>')).toBeTruthy();
  });
});

describe('editing and saving', () => {
  async function selectSegment(id: string) {
    const node = document.querySelector(`[data-segment="${id}"]`)!;
    fireEvent.pointerDown(node, { button: 0, clientX: 10, clientY: 10, pointerId: 1 });
    fireEvent.pointerUp(document.querySelector('.istory-canvas')!, { clientX: 10, clientY: 10, pointerId: 1 });
    await screen.findByLabelText('片段编辑', { selector: 'div' });
  }

  it('edits a segment and its choices, then saves against the loaded revision', async () => {
    const calls = mockApi(recordOf(storyGraph(), 7));
    await open();
    await selectSegment('a');
    const inspector = screen.getByLabelText('片段编辑', { selector: 'div' });
    fireEvent.change(within(inspector).getByLabelText('标题'), { target: { value: '敲门' } });
    fireEvent.change(within(inspector).getByLabelText('旁白 / 场景'), { target: { value: '夜很深。' } });
    fireEvent.change(within(inspector).getAllByLabelText('选项文字')[1], { target: { value: '假装不在' } });
    fireEvent.click(within(inspector).getAllByLabelText('下移')[0]);
    fireEvent.change(within(inspector).getAllByLabelText('去往')[0], { target: { value: '' } });
    await userEvent.click(screen.getByRole('button', { name: /保存/ }));
    await waitFor(() => expect(named(calls, 'PUT', '')).toHaveLength(1));
    const sent = named(calls, 'PUT', '')[0].body as { base_revision: number; graph: StoryGraph };
    expect(sent.base_revision).toBe(7);
    expect(sent.graph.segments[0]).toMatchObject({ title: '敲门', narration: '夜很深。' });
    expect(sent.graph.segments[0].choices.map(item => [item.id, item.text, item.target])).toEqual([['stay', '假装不在', null], ['go', '开门', 'b']]);
    await screen.findByText('已保存');
  });

  it('builds a condition and an effect as data', async () => {
    const calls = mockApi(recordOf(storyGraph()));
    await open();
    await selectSegment('a');
    const card = document.querySelector('[data-choice="stay"]') as HTMLElement;
    await userEvent.click(within(card).getByRole('button', { name: /添加条件/ }));
    fireEvent.change(within(card).getByLabelText('比较方式'), { target: { value: 'lt' } });
    fireEvent.change(within(card).getByLabelText('比较值'), { target: { value: '5' } });
    fireEvent.change(within(card).getByLabelText('不满足时'), { target: { value: 'hide' } });
    await userEvent.click(within(card).getByRole('button', { name: /添加效果/ }));
    fireEvent.change(within(card).getByLabelText('效果值'), { target: { value: '-3' } });
    await userEvent.click(screen.getByRole('button', { name: /保存/ }));
    await waitFor(() => expect(named(calls, 'PUT', '')).toHaveLength(1));
    const choice = (named(calls, 'PUT', '')[0].body as { graph: StoryGraph }).graph.segments[0].choices[1];
    expect(choice.condition).toEqual({ all: [{ var: 'trust', op: 'lt', value: 5 }] });
    expect(choice.when_locked).toBe('hide');
    expect(choice.effects).toEqual([{ var: 'trust', op: 'add', value: -3 }]);
  });

  it('sets a timer with a default route', async () => {
    const calls = mockApi(recordOf(storyGraph()));
    await open();
    await selectSegment('a');
    await userEvent.click(screen.getByLabelText('到时间自动选择'));
    fireEvent.change(screen.getByLabelText('秒数', { selector: 'input' }), { target: { value: '8' } });
    fireEvent.change(screen.getByLabelText('默认选项'), { target: { value: 'stay' } });
    await userEvent.click(screen.getByRole('button', { name: /保存/ }));
    await waitFor(() => expect(named(calls, 'PUT', '')).toHaveLength(1));
    expect((named(calls, 'PUT', '')[0].body as { graph: StoryGraph }).graph.segments[0].timer).toEqual({ seconds: 8, default_choice: 'stay' });
  });

  it('warns before deleting a variable something uses', async () => {
    mockApi(recordOf(storyGraph()));
    await open();
    vi.mocked(window.confirm).mockReturnValue(false);
    await userEvent.click(screen.getByRole('button', { name: '删除这个变量' }));
    expect(vi.mocked(window.confirm).mock.calls[0][0]).toContain('2');
    expect(document.querySelector('[data-variable="trust"]')).toBeTruthy();
  });

  it('re-analyses a draft shortly after an edit and shows the problem on the node', async () => {
    const issue = { code: 'dead_end', severity: 'error' as const, message: 'm', segment_id: 'b', params: { segment: '抉择' } };
    const calls = mockApi(recordOf(storyGraph()), {
      'POST /analyze': () => analysisOf({ issues: [issue], errors: 1, ready: false }),
    });
    await open();
    fireEvent.change(screen.getByLabelText('故事标题'), { target: { value: '新名字' } });
    await waitFor(() => expect(named(calls, 'POST', '/analyze').length).toBe(1), { timeout: 2000 });
    await waitFor(() => expect(document.querySelector('[data-segment="b"]')?.classList.contains('has-error')).toBe(true));
    expect(screen.getByText('有未保存的修改')).toBeTruthy();
  });

  it('a conflict keeps the edits and lets the author choose', async () => {
    let overwriteAllowed = false;
    const calls = mockApi(recordOf(storyGraph(), 3), {
      'PUT ': (_url, init) => (overwriteAllowed
        ? json(200, recordOf(JSON.parse(String(init.body)).graph as StoryGraph, 10))
        : json(409, { detail: '已在其他页面更新' })),
    });
    await open();
    fireEvent.change(screen.getByLabelText('故事标题'), { target: { value: '我的版本' } });
    await userEvent.click(screen.getByRole('button', { name: /保存/ }));
    const banner = await screen.findByText('这个故事已在其他页面更新，你的修改还没有保存。');
    expect(banner).toBeTruthy();
    expect(screen.getByDisplayValue('我的版本')).toBeTruthy();
    overwriteAllowed = true;
    await userEvent.click(screen.getByRole('button', { name: '用我的版本覆盖' }));
    await waitFor(() => expect(screen.queryByText('这个故事已在其他页面更新，你的修改还没有保存。')).toBeNull());
    const puts = named(calls, 'PUT', '');
    expect(puts).toHaveLength(2);
    expect(puts[1].body).toMatchObject({ base_revision: 3, graph: { title: '我的版本' } });
  });

  it('disconnecting an edge keeps the choice, unconnected', async () => {
    const calls = mockApi(recordOf(storyGraph()));
    await open();
    fireEvent.pointerDown(document.querySelector('[data-edge="go"] .istory-edge__hit')!, { button: 0, pointerId: 1 });
    await userEvent.click(await screen.findByRole('button', { name: /断开这条连线/ }));
    await userEvent.click(screen.getByRole('button', { name: /保存/ }));
    await waitFor(() => expect(named(calls, 'PUT', '')).toHaveLength(1));
    const choice = (named(calls, 'PUT', '')[0].body as { graph: StoryGraph }).graph.segments[0].choices[0];
    expect([choice.id, choice.text, choice.target]).toEqual(['go', '开门', null]);
    expect(choice.effects).toHaveLength(1);
  });

  it('connects from the inspector too, for anyone not dragging', async () => {
    const calls = mockApi(recordOf(storyGraph()));
    await open();
    await selectSegment('b');
    fireEvent.change(screen.getAllByLabelText('去往', { selector: 'select' })[1], { target: { value: 'good' } });
    await userEvent.click(screen.getByRole('button', { name: /保存/ }));
    await waitFor(() => expect(named(calls, 'PUT', '')).toHaveLength(1));
    expect((named(calls, 'PUT', '')[0].body as { graph: StoryGraph }).graph.segments[1].choices[1].target).toBe('good');
  });

  it('adds and deletes a segment, leaving what pointed at it unconnected', async () => {
    const calls = mockApi(recordOf(storyGraph()));
    await open();
    await userEvent.click(screen.getByRole('button', { name: /^片段$/ }));
    expect(document.querySelectorAll('[data-segment]').length).toBe(5);
    await selectSegment('good');
    await userEvent.click(screen.getAllByRole('button', { name: /删除片段/ })[0]);
    expect(document.querySelector('[data-segment="good"]')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: /保存/ }));
    await waitFor(() => expect(named(calls, 'PUT', '')).toHaveLength(1));
    expect((named(calls, 'PUT', '')[0].body as { graph: StoryGraph }).graph.segments[1].choices[0].target).toBeNull();
  });

  it('saves with the keyboard shortcut', async () => {
    const calls = mockApi(recordOf(storyGraph()));
    await open();
    fireEvent.change(screen.getByLabelText('故事标题'), { target: { value: '新' } });
    fireEvent.keyDown(window, { key: 's', metaKey: true });
    await waitFor(() => expect(named(calls, 'PUT', '')).toHaveLength(1));
  });

  it('never lets a too-long title reach the server by accident', async () => {
    mockApi(recordOf(storyGraph()));
    await open();
    expect(screen.getByLabelText('故事标题')).toHaveProperty('maxLength', 120);
  });
});

describe('the graph canvas', () => {
  function canvas(props: Partial<Parameters<typeof StoryGraphCanvas>[0]> = {}) {
    const handlers = {
      onSelect: vi.fn(), onMoveNode: vi.fn(), onConnect: vi.fn(), onAddChoice: vi.fn(), onAddAt: vi.fn(), onDeleteSelection: vi.fn(),
    };
    render(<StoryGraphCanvas graph={storyGraph()} {...handlers} {...props} />);
    return { ...handlers, root: screen.getByTestId('story-canvas') };
  }

  // The first fit runs on a timer; flush it so a test sees a settled view at a known zoom.
  async function settled(root: HTMLElement) {
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
    return Number(root.dataset.zoom);
  }

  it('draws a node per segment and an edge per connected choice', () => {
    canvas();
    expect(document.querySelectorAll('[data-segment]').length).toBe(4);
    expect(document.querySelectorAll('[data-edge]').length).toBe(4);
  });

  it('selects on click and clears on a click on nothing', () => {
    const { root, onSelect } = canvas();
    fireEvent.pointerDown(document.querySelector('[data-segment="b"]')!, { button: 0, clientX: 5, clientY: 5, pointerId: 1 });
    fireEvent.pointerUp(root, { clientX: 5, clientY: 5, pointerId: 1 });
    expect(onSelect).toHaveBeenLastCalledWith({ kind: 'segment', id: 'b' });
    fireEvent.pointerDown(root, { button: 0, clientX: 5, clientY: 5, pointerId: 2 });
    fireEvent.pointerUp(root, { clientX: 5, clientY: 5, pointerId: 2 });
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it('moves a node once on release, in world units', async () => {
    const { root, onMoveNode } = canvas();
    const zoom = await settled(root);
    fireEvent.pointerDown(document.querySelector('[data-segment="a"]')!, { button: 0, clientX: 100, clientY: 100, pointerId: 1 });
    fireEvent.pointerMove(root, { clientX: 150, clientY: 130, pointerId: 1 });
    fireEvent.pointerMove(root, { clientX: 200, clientY: 160, pointerId: 1 });
    expect(onMoveNode).not.toHaveBeenCalled();
    fireEvent.pointerUp(root, { clientX: 200, clientY: 160, pointerId: 1 });
    expect(onMoveNode).toHaveBeenCalledTimes(1);
    const [id, position] = onMoveNode.mock.calls[0];
    expect(id).toBe('a');
    expect(position.x).toBeCloseTo(100 / zoom, 0);
    expect(position.y).toBeCloseTo(60 / zoom, 0);
  });

  it('pans on empty space without selecting anything', async () => {
    const { root, onSelect } = canvas();
    await settled(root);
    const world = root.querySelector('.istory-canvas__world') as HTMLElement;
    const before = world.style.transform;
    fireEvent.pointerDown(root, { button: 0, clientX: 10, clientY: 10, pointerId: 1 });
    fireEvent.pointerMove(root, { clientX: 60, clientY: 40, pointerId: 1 });
    fireEvent.pointerUp(root, { clientX: 60, clientY: 40, pointerId: 1 });
    expect(world.style.transform).not.toBe(before);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('zooms with the wheel and the buttons, within limits', async () => {
    const { root } = canvas();
    const start = await settled(root);
    fireEvent.wheel(root, { deltaY: -200, clientX: 10, clientY: 10 });
    const wheeled = Number(root.dataset.zoom);
    expect(wheeled).toBeGreaterThan(start);
    fireEvent.click(screen.getByRole('button', { name: '缩小' }));
    expect(Number(root.dataset.zoom)).toBeLessThan(wheeled);
    for (let index = 0; index < 20; index += 1) fireEvent.wheel(root, { deltaY: 500 });
    expect(Number(root.dataset.zoom)).toBeCloseTo(0.2, 2);
    expect(screen.getByRole('button', { name: '缩小' })).toHaveProperty('disabled', true);
  });

  it('connects an existing choice by dragging its port onto a node', async () => {
    const { root, onConnect } = canvas();
    await settled(root);
    vi.spyOn(root, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 900, height: 600, right: 900, bottom: 600, x: 0, y: 0, toJSON: () => ({}) });
    fireEvent.click(screen.getByRole('button', { name: '适应画布' }));
    const zoom = Number(root.dataset.zoom);
    const transform = (root.querySelector('.istory-canvas__world') as HTMLElement).style.transform;
    const [, tx, ty] = transform.match(/translate\((-?[\d.]+)px, (-?[\d.]+)px\)/)!.map(Number);
    fireEvent.pointerDown(document.querySelector('[data-port="leave"]')!, { button: 0, clientX: 0, clientY: 0, pointerId: 1 });
    // Over the middle of "good", at world (710, 20).
    const screenX = tx + 710 * zoom;
    const screenY = ty + 20 * zoom;
    fireEvent.pointerMove(root, { clientX: screenX, clientY: screenY, pointerId: 1 });
    expect(document.querySelector('[data-segment="good"]')?.classList.contains('is-drop')).toBe(true);
    fireEvent.pointerUp(root, { clientX: screenX, clientY: screenY, pointerId: 1 });
    expect(onConnect).toHaveBeenCalledWith('b', 'leave', 'good');
    expect(document.querySelector('.istory-edge__rubber')).toBeNull();
  });

  it('dragging a port onto nothing changes nothing; a click on the add port adds a choice', async () => {
    const { root, onConnect, onAddChoice } = canvas();
    await settled(root);
    fireEvent.pointerDown(document.querySelector('[data-port="leave"]')!, { button: 0, clientX: 0, clientY: 0, pointerId: 1 });
    fireEvent.pointerMove(root, { clientX: -5000, clientY: -5000, pointerId: 1 });
    fireEvent.pointerUp(root, { clientX: -5000, clientY: -5000, pointerId: 1 });
    expect(onConnect).not.toHaveBeenCalled();
    fireEvent.pointerDown(document.querySelector('[data-add-choice="a"]')!, { button: 0, clientX: 0, clientY: 0, pointerId: 2 });
    fireEvent.pointerUp(root, { clientX: 0, clientY: 0, pointerId: 2 });
    expect(onAddChoice).toHaveBeenCalledWith('a');
  });

  it('selects an edge by its line, deletes with the keyboard', () => {
    const { onSelect, onDeleteSelection, root } = canvas({ selection: { kind: 'edge', segment: 'a', edge: 'go' } });
    fireEvent.pointerDown(document.querySelector('[data-edge="stay"] .istory-edge__hit')!, { button: 0, pointerId: 1 });
    expect(onSelect).toHaveBeenCalledWith({ kind: 'edge', segment: 'a', edge: 'stay' });
    fireEvent.keyDown(root, { key: 'Delete' });
    expect(onDeleteSelection).toHaveBeenCalled();
  });

  it('a story map has no editing affordances and shows status', () => {
    const { root, onMoveNode } = canvas({ status: id => (id === 'a' ? 'played' : 'unexplored') });
    expect(document.querySelector('[data-port]')).toBeNull();
    expect(document.querySelector('[data-add-choice]')).toBeNull();
    expect(document.querySelector('[data-segment="a"]')).toHaveProperty('dataset.status', 'played');
    fireEvent.pointerDown(document.querySelector('[data-segment="a"]')!, { button: 0, clientX: 0, clientY: 0, pointerId: 1 });
    fireEvent.pointerMove(root, { clientX: 100, clientY: 100, pointerId: 1 });
    fireEvent.pointerUp(root, { clientX: 100, clientY: 100, pointerId: 1 });
    expect(onMoveNode).not.toHaveBeenCalled();
  });
});

describe('playtest', () => {
  // Scoped to the player: the story map names the same segments.
  const play = (text: string) => within(document.querySelector('.istory-play__stage') as HTMLElement).getByRole('button', { name: new RegExp(text) });

  it('plays with text cards: choices apply effects, gated choices lock, the map keeps count', async () => {
    const calls = mockApi(recordOf(storyGraph()));
    await open();
    await userEvent.click(tab('试玩'));
    expect(within(screen.getByTestId('playtest-card')).getByText('门外有人。')).toBeTruthy();
    expect(screen.getByTestId('map-played').textContent).toBe('1');
    expect(screen.getByTestId('map-unlocked').textContent).toBe('1');
    expect(screen.getByTestId('map-endings').textContent).toBe('0/2');

    await userEvent.click(play('不开'));
    expect(screen.getByTestId('value-trust').textContent).toBe('0');
    const locked = screen.getByRole('button', { name: /相信他/ });
    expect(locked).toHaveProperty('disabled', true);
    expect(within(locked).getByText('信任不够')).toBeTruthy();

    await userEvent.click(play('从头开始'));
    await userEvent.click(play('开门'));
    expect(screen.getByTestId('value-trust').textContent).toBe('2');
    expect(screen.getByRole('button', { name: /相信他/ })).toHaveProperty('disabled', false);
    await userEvent.click(play('相信他'));
    expect(within(screen.getByTestId('playtest-card')).getByText(/好结局/)).toBeTruthy();
    expect(screen.getByTestId('map-endings').textContent).toBe('1/2');
    expect(document.querySelector('[data-segment="good"]')).toHaveProperty('dataset.status', 'current');

    await waitFor(() => expect(named(calls, 'POST', '/playtest').length).toBe(2));
    expect(named(calls, 'POST', '/playtest')[1].body).toEqual({
      steps: [{ segment: 'a', choice: null }, { segment: 'b', choice: 'go' }, { segment: 'good', choice: 'gold' }],
      ending: 'good', from_start: true, timeouts: 0,
    });
  });

  it('hides a gated choice set to hide', async () => {
    const graph = storyGraph();
    graph.segments[1].choices[0].when_locked = 'hide';
    mockApi(recordOf(graph));
    await open();
    await userEvent.click(tab('试玩'));
    await userEvent.click(play('不开'));
    expect(screen.queryByRole('button', { name: /相信他/ })).toBeNull();
  });

  it('replays from the map with the values that segment had', async () => {
    const calls = mockApi(recordOf(storyGraph()));
    await open();
    await userEvent.click(tab('试玩'));
    await userEvent.click(play('开门'));
    await userEvent.click(play('离开'));
    const map = screen.getByTestId('story-canvas');
    expect(screen.getByTestId('value-trust').textContent).toBe('2');
    fireEvent.pointerDown(map.querySelector('[data-segment="b"]')!, { button: 0, clientX: 1, clientY: 1, pointerId: 1 });
    fireEvent.pointerUp(map, { clientX: 1, clientY: 1, pointerId: 1 });
    expect(within(screen.getByTestId('playtest-card')).getByRole('heading').textContent).toBe('抉择');
    expect(screen.getByTestId('value-trust').textContent).toBe('2');
    await userEvent.click(play('相信他'));
    await waitFor(() => expect(named(calls, 'POST', '/playtest').length).toBe(2));
    expect((named(calls, 'POST', '/playtest')[1].body as { from_start: boolean }).from_start).toBe(false);
  });

  it('will not replay what has not been reached', async () => {
    mockApi(recordOf(storyGraph()));
    await open();
    await userEvent.click(tab('试玩'));
    const map = screen.getByTestId('story-canvas');
    fireEvent.pointerDown(map.querySelector('[data-segment="good"]')!, { button: 0, clientX: 1, clientY: 1, pointerId: 1 });
    fireEvent.pointerUp(map, { clientX: 1, clientY: 1, pointerId: 1 });
    expect(within(screen.getByTestId('playtest-card')).getByRole('heading').textContent).toBe('开门');
  });

  it('takes the default route when a timed choice runs out', async () => {
    const graph = storyGraph();
    graph.segments[0].timer = { seconds: 3, default_choice: 'stay' };
    const calls = mockApi(recordOf(graph));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await open();
    fireEvent.click(tab('试玩'));
    expect(screen.getByRole('timer')).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    expect(within(screen.getByTestId('playtest-card')).getByRole('heading').textContent).toBe('开门');
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(within(screen.getByTestId('playtest-card')).getByRole('heading').textContent).toBe('抉择');
    expect(screen.getByTestId('value-trust').textContent).toBe('0');
    fireEvent.click(screen.getByRole('button', { name: /离开/ }));
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect((named(calls, 'POST', '/playtest')[0].body as { timeouts: number }).timeouts).toBe(1);
  });

  it('a timer does not restart when the page re-renders around it', async () => {
    const graph = storyGraph();
    graph.segments[0].timer = { seconds: 3, default_choice: 'stay' };
    mockApi(recordOf(graph));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await open();
    fireEvent.click(tab('试玩'));
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    fireEvent.click(screen.getByLabelText('只用文字卡'));
    await act(async () => { await vi.advanceTimersByTimeAsync(1100); });
    expect(within(screen.getByTestId('playtest-card')).getByRole('heading').textContent).toBe('抉择');
  });

  it('follows an automatic route on a button, and a route can decide the ending', async () => {
    const graph = storyGraph();
    graph.segments[1] = { ...blankSegment('b', 'scene', '抉择', { x: 300, y: 0 }), routes: [
      { id: 'r1', condition: { var: 'trust', op: 'gte', value: 2 }, target: 'good' },
      { id: 'r2', condition: null, target: 'bad' },
    ] };
    mockApi(recordOf(graph));
    await open();
    await userEvent.click(tab('试玩'));
    await userEvent.click(play('开门'));
    await userEvent.click(play('继续'));
    expect(within(screen.getByTestId('playtest-card')).getByRole('heading').textContent).toBe('团圆');
  });

  it('says so when a segment has no way out', async () => {
    const graph = storyGraph();
    graph.segments[0].choices = [{ ...blankChoice('c', '上锁', 'b'), condition: { var: 'trust', op: 'gte', value: 9 } }];
    mockApi(recordOf(graph));
    await open();
    await userEvent.click(tab('试玩'));
    expect(screen.getByText('这里走不下去了：没有可选的出口。')).toBeTruthy();
    expect(screen.getByRole('button', { name: /重新开始/ })).toBeTruthy();
  });

  it('shows an unconnected choice to the author but will not take it', async () => {
    const graph = storyGraph();
    graph.segments[0].choices = [blankChoice('c', '未连', null)];
    mockApi(recordOf(graph));
    await open();
    await userEvent.click(tab('试玩'));
    expect(screen.getByRole('button', { name: /未连/ })).toHaveProperty('disabled', true);
  });

  it('does not count a draft in the statistics', async () => {
    const calls = mockApi(recordOf(storyGraph()));
    await open();
    fireEvent.change(screen.getByLabelText('故事标题'), { target: { value: '改过' } });
    await userEvent.click(tab('试玩'));
    expect(screen.getByRole('note').textContent).toContain('不计入统计');
    await userEvent.click(play('不开'));
    await userEvent.click(play('离开'));
    expect(named(calls, 'POST', '/playtest')).toHaveLength(0);
  });

  it('falls back to a text card when the media will not load', async () => {
    const graph = storyGraph();
    graph.segments[0].media = { kind: 'video', url: '/media/gone.mp4', source: 'clip', shot_uid: 1, label: '', duration_s: 5 };
    mockApi(recordOf(graph));
    await open();
    await userEvent.click(tab('试玩'));
    const card = screen.getByTestId('playtest-card');
    expect(screen.queryByRole('button', { name: /不开/ })).toBeNull();
    fireEvent.error(card.querySelector('video')!);
    expect(card.querySelector('video')).toBeNull();
    expect(within(card).getByText('媒体加载失败，改用文字卡')).toBeTruthy();
    expect(screen.getByRole('button', { name: /不开/ })).toBeTruthy();
  });

  it('text-only mode plays a story whose media does not exist yet', async () => {
    const graph = storyGraph();
    graph.segments[0].media = { kind: 'video', url: '/media/none.mp4', source: 'clip', shot_uid: 1, label: '', duration_s: 5 };
    mockApi(recordOf(graph));
    await open();
    await userEvent.click(tab('试玩'));
    await userEvent.click(screen.getByLabelText('只用文字卡'));
    expect(screen.getByTestId('playtest-card').querySelector('video')).toBeNull();
    expect(screen.getByRole('button', { name: /不开/ })).toBeTruthy();
  });
});

describe('analysis', () => {
  it('shows problems in words, coverage, reach rates and routes; a problem jumps to its segment', async () => {
    const graph = storyGraph();
    const issues: StoryIssue[] = [
      { code: 'dead_end', severity: 'error', message: 'x', segment_id: 'b', params: { segment: '抉择' } },
      { code: 'impossible_condition', severity: 'warning', message: 'x', segment_id: 'a', choice_id: 'go', params: { segment: '开门', text: '开门', possible: '' } },
      { code: 'something_new', severity: 'warning', message: '后端的原话', },
    ];
    mockApi({ ...recordOf(graph), analysis: analysisOf({ issues, errors: 1, warnings: 2, ready: false }) });
    await open();
    await userEvent.click(tab('分析'));
    expect(screen.getByText('「抉择」没有任何出口，也不是结局')).toBeTruthy();
    expect(screen.getByText('后端的原话')).toBeTruthy();
    expect(screen.getByText('好结局', { exact: false })).toBeTruthy();
    expect(screen.getAllByText('75%').length).toBeGreaterThan(0);
    expect(screen.getByText('开门 → 抉择 → 团圆')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: /「开门」的「开门」条件永远不会成立/ }));
    await waitFor(() => expect(document.querySelector('[data-choice="go"]')?.classList.contains('is-selected')).toBe(true));
  });

  it('says when rates are estimated and when routes were cut short', async () => {
    const base = analysisOf();
    mockApi({ ...recordOf(storyGraph()), analysis: { ...base, paths: { ...base.paths, truncated: true, rate_method: 'simulation', unfinished_rate: 0.1 } } });
    await open();
    await userEvent.click(tab('分析'));
    expect(screen.getByText('故事有回环或路线太多，这是随机模拟的估算值。')).toBeTruthy();
    expect(screen.getByText('路线太多，只枚举了前 2000 条')).toBeTruthy();
    expect(screen.getByText('还有 10% 的走法到不了结局。')).toBeTruthy();
  });

  it('shows playtest statistics and can clear them after asking', async () => {
    const stats: PlaytestStats = {
      ...emptyStats, runs: 4, completed: 3, timeouts: 1, endings_reached: 1,
      endings: [{ id: 'good', title: '团圆', count: 3 }, { id: 'bad', title: '错过', count: 0 }],
      choices: [{ segment_id: 'a', segment: '开门', choice_id: 'go', text: '选择开门', count: 3, share: 0.75 }],
      routes_played: 1, route_coverage: 0.3333,
    };
    const calls = mockApi({ ...recordOf(storyGraph()), stats }, { 'DELETE /playtest': () => emptyStats });
    await open();
    await userEvent.click(tab('分析'));
    expect(screen.getByText('3 次走到结局')).toBeTruthy();
    expect(screen.getByText('选择开门')).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: '清空统计' }));
    await waitFor(() => expect(named(calls, 'DELETE', '/playtest')).toHaveLength(1));
    await screen.findByText('还没有试玩记录。保存后到「试玩」走一遍就会出现在这里。');
  });
});

describe('planning', () => {
  async function planWith(handler: Handler) {
    const calls = mockApi(recordOf(null, 0), { 'POST /plan': handler });
    await open();
    await userEvent.click(screen.getAllByRole('button', { name: /AI 规划/ })[0]);
    const dialog = screen.getByRole('dialog', { name: 'AI 规划故事' });
    await userEvent.type(within(dialog).getByLabelText('故事想法'), '雨夜里的一封信');
    await userEvent.click(within(dialog).getByRole('button', { name: /开始规划/ }));
    return { calls, dialog };
  }

  it('previews a draft and saves it once adopted', async () => {
    const draft = { ...storyGraph(), segments: storyGraph().segments.map(item => ({ ...item, position: null })) };
    const { calls, dialog } = await planWith(() => ({ draft, analysis: analysisOf(), attempts: 1 }));
    await within(dialog).findByText('雨夜来客');
    expect(named(calls, 'POST', '/plan')[0].body).toEqual({ brief: '雨夜里的一封信', endings: 3, minutes: 10, use_project: true, language: 'zh' });
    expect(named(calls, 'PUT', '')).toHaveLength(0);
    expect(within(dialog).getByText('4 个片段，2 个结局，3 条完整路线，每条约 0.5 ~ 0.5 分钟。')).toBeTruthy();
    await userEvent.click(within(dialog).getByRole('button', { name: '采用这份草稿' }));
    await waitFor(() => expect(named(calls, 'PUT', '')).toHaveLength(1));
    const sent = (named(calls, 'PUT', '')[0].body as { base_revision: number; graph: StoryGraph });
    expect(sent.base_revision).toBe(0);
    expect(sent.graph.segments.every(item => item.position)).toBe(true);
    expect(document.querySelectorAll('[data-segment]').length).toBe(4);
  });

  it('shows the reason when the model gave junk', async () => {
    const { calls, dialog } = await planWith(() => json(422, { detail: '模型连续 3 次没有给出可用的分支剧情：输出不是合法 JSON' }));
    expect((await within(dialog).findByRole('alert')).textContent).toContain('没有给出可用的分支剧情');
    expect(named(calls, 'PUT', '')).toHaveLength(0);
  });

  it('asks before replacing an existing story', async () => {
    const calls = mockApi(recordOf(storyGraph()), { 'POST /plan': () => ({ draft: storyGraph(), analysis: analysisOf(), attempts: 1 }) });
    await open();
    await userEvent.click(screen.getByRole('button', { name: /AI 规划/ }));
    const dialog = screen.getByRole('dialog', { name: 'AI 规划故事' });
    await userEvent.type(within(dialog).getByLabelText('故事想法'), '雨夜里的信');
    await userEvent.click(within(dialog).getByRole('button', { name: /开始规划/ }));
    const adopt = await within(dialog).findByRole('button', { name: '采用这份草稿' });
    vi.mocked(window.confirm).mockReturnValue(false);
    await userEvent.click(adopt);
    expect(window.confirm).toHaveBeenCalled();
    expect(named(calls, 'PUT', '')).toHaveLength(0);
  });
});

describe('media', () => {
  const library: MediaLibrary = {
    shots: [
      { shot_id: 1, shot_uid: 100101, scene_id: 'E1S01', desc: '开门的一镜', image_url: '/media/s1.png', video_url: '/media/c1.mp4', candidate_urls: ['/media/c1b.mp4'], duration_s: 8, stale: false },
      { shot_id: 2, shot_uid: 100102, scene_id: 'E1S01', desc: '没出片的一镜', image_url: null, video_url: null, candidate_urls: [], duration_s: 0, stale: false },
    ],
    films: [{ label: '第一集', video_url: '/media/ep1.mp4' }],
    uploads: [],
  };

  async function pickerOnSegment(overrides: Record<string, Handler> = {}) {
    const calls = mockApi(recordOf(storyGraph()), { 'GET /media': () => library, ...overrides });
    await open();
    fireEvent.pointerDown(document.querySelector('[data-segment="a"]')!, { button: 0, clientX: 5, clientY: 5, pointerId: 1 });
    fireEvent.pointerUp(document.querySelector('.istory-canvas')!, { clientX: 5, clientY: 5, pointerId: 1 });
    await userEvent.click(await screen.findByRole('button', { name: /从项目选择/ }));
    await screen.findByText('开门的一镜');
    return calls;
  }

  it('picks a generated clip with its duration and shot', async () => {
    const calls = await pickerOnSegment();
    await userEvent.click(screen.getAllByRole('button', { name: '用视频' })[0]);
    await userEvent.click(screen.getByRole('button', { name: /保存/ }));
    await waitFor(() => expect(named(calls, 'PUT', '')).toHaveLength(1));
    expect((named(calls, 'PUT', '')[0].body as { graph: StoryGraph }).graph.segments[0].media).toEqual({
      kind: 'video', url: '/media/c1.mp4', source: 'clip', shot_uid: 100101, label: 'E1S01 #1', duration_s: 8,
    });
  });

  it('a shot with no video says where to get one and offers nothing paid', async () => {
    await pickerOnSegment();
    expect(screen.getByText('还没有视频：到镜头工作区运行第 5 阶段生成')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: /标记重做/ })).toHaveLength(1);
  });

  it('marking a redo goes through the paid confirmation, with the gate\'s estimate', async () => {
    const admission = { decision: 'admitted', shots: [], counts: { generate: 3, reuse: 1, blocked: 0, withheld: 0 }, confirmations: [], video_model: 'm', provider_family: 'f', estimate: { shots_to_generate: 3, requested_seconds: 30, priced: true, cost: 12.5, currency: 'CNY' } };
    const regenerate = vi.fn((url: string) => url && {});
    await pickerOnSegment({
      'POST http://localhost:8000/api/drama/t1/shots/admission': () => admission,
      'POST http://localhost:8000/api/drama/t1/shots/1/regenerate': regenerate,
    });
    vi.mocked(window.confirm).mockReturnValue(false);
    await userEvent.click(screen.getByRole('button', { name: /标记重做/ }));
    await waitFor(() => expect(window.confirm).toHaveBeenCalled());
    const text = vi.mocked(window.confirm).mock.calls[0][0]!;
    expect(text).toContain('付费');
    expect(text).toContain('12.50 CNY');
    expect(regenerate).not.toHaveBeenCalled();

    vi.mocked(window.confirm).mockReturnValue(true);
    await userEvent.click(screen.getByRole('button', { name: /标记重做/ }));
    await waitFor(() => expect(regenerate).toHaveBeenCalledTimes(1));
    expect(regenerate.mock.calls[0][0]).toContain('scene_id=E1S01');
  });

  it('uploads a file and uses it', async () => {
    const calls = await pickerOnSegment({
      'POST /media': () => ({ id: 'u1', kind: 'image', url: '/media/istory_x.png', label: 'x.png', size: 10, duration_s: 0 }),
    });
    const input = screen.getByLabelText('上传图片或视频') as HTMLInputElement;
    await userEvent.upload(input, new File(['x'], 'x.png', { type: 'image/png' }));
    await waitFor(() => expect(named(calls, 'POST', '/media')).toHaveLength(1));
    expect(named(calls, 'POST', '/media')[0].body).toBeInstanceOf(FormData);
    await screen.findByRole('button', { name: /移除媒体/ });
  });

  it('shows why an upload was refused', async () => {
    await pickerOnSegment({ 'POST /media': () => json(422, { detail: '文件内容不是其中任何一种' }) });
    await userEvent.upload(screen.getByLabelText('上传图片或视频') as HTMLInputElement, new File(['x'], 'x.png', { type: 'image/png' }));
    expect((await screen.findByRole('alert')).textContent).toContain('文件内容不是其中任何一种');
  });
});

describe('export', () => {
  it('downloads each format and shows what the media will do', async () => {
    const created = vi.fn(() => 'blob:x');
    const revoked = vi.fn();
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: created, revokeObjectURL: revoked }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    const calls = mockApi(recordOf(storyGraph()), {
      'GET /export/preview': () => ({ ready: true, errors: [], inline_limit_bytes: 67108864, media: [{ segment_id: 'a', title: '开门', kind: 'video', status: 'expired', size: 0 }] }),
      'GET /export.html': () => json(200, {}),
      'GET /export.zip': () => json(200, {}),
    });
    await open();
    await userEvent.click(tab('导出'));
    await screen.findByText('链接已过期，只能显示文字卡');
    await userEvent.click(screen.getByRole('button', { name: /下载 HTML/ }));
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
    await userEvent.click(screen.getByRole('button', { name: /下载 ZIP/ }));
    await waitFor(() => expect(click).toHaveBeenCalledTimes(2));
    expect(named(calls, 'GET', '/export.html')[0].url).toContain('lang=zh-CN');
    expect(revoked).toHaveBeenCalledTimes(2);
  });

  it('will not offer a download of a broken story, and says why', async () => {
    const issue = { code: 'no_ending', severity: 'error' as const, message: 'x' };
    mockApi(recordOf(storyGraph()), { 'GET /export/preview': () => ({ ready: false, errors: [issue], media: [], inline_limit_bytes: 1 }) });
    await open();
    await userEvent.click(tab('导出'));
    await screen.findByText('故事里还没有结局');
    expect(screen.getByRole('button', { name: /下载 HTML/ })).toHaveProperty('disabled', true);
    expect(screen.getByRole('button', { name: /下载 ZIP/ })).toHaveProperty('disabled', true);
  });

  it('shows a refusal that only the server could know about', async () => {
    mockApi(recordOf(storyGraph()), { 'GET /export.zip': () => json(422, { detail: '故事还有问题，导出的播放器会走不通' }) });
    await open();
    await userEvent.click(tab('导出'));
    await waitFor(() => expect(screen.getByRole('button', { name: /下载 ZIP/ })).toHaveProperty('disabled', false));
    await userEvent.click(screen.getByRole('button', { name: /下载 ZIP/ }));
    expect((await screen.findByRole('alert')).textContent).toContain('走不通');
  });

  it('warns that an unsaved draft is not what gets exported', async () => {
    mockApi(recordOf(storyGraph()));
    await open();
    fireEvent.change(screen.getByLabelText('故事标题'), { target: { value: '新' } });
    await userEvent.click(tab('导出'));
    expect(screen.getByText('有未保存的修改：导出的是上次保存的版本，请先保存。')).toBeTruthy();
  });
});
