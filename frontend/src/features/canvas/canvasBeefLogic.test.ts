// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';

import { boardAppearance, lightness, normaliseAppearance, normaliseHex, resolveAppearance, saveBoardAppearance, saveDefaultAppearance, DEFAULT_APPEARANCE } from './canvasBeefAppearance';
import { MAX_BATCH_ROWS, newRow, nodesFromRows, rowProblems, rowsFromPaste, totalsOf } from './canvasBeefBatchTable';
import { clampEditorSize, defaultEditorSize, EDITOR_MIN_HEIGHT } from './canvasBeefEditorSize';
import { applySuggestions, checkReferences } from './canvasBeefReferences';
import { pressPans, toolForKey } from './canvasBeefTool';
import { boundsOf, diffVersions } from './canvasBeefVersionDiff';
import type { CanvasEdge, CanvasNode, RunAssessment } from './canvasTypes';

const node = (id: string, kind: CanvasNode['kind'], x = 0, y = 0, payload: CanvasNode['payload'] = {}): CanvasNode => ({
  id, kind, track: 'freezone', x, y, width: 100, height: 80, artifact_id: null, payload,
});
const edge = (id: string, source: string, target: string, role?: string): CanvasEdge => ({ id, source, target, kind: 'reference', payload: role ? { role } : {} });
const LIMITS = { images: 3, videos: 1, audios: 1 };

afterEach(() => localStorage.clear());

describe('smart reference', () => {
  const clip = node('v', 'video_gen', 500, 0);

  it('makes the only picture the first frame, and with two the left one opens and the right one closes', () => {
    const one = checkReferences(clip, [clip, node('a', 'image_gen', 0, 0)], [edge('e1', 'a', 'v')], LIMITS);
    expect(one.suggestions).toEqual([{ edgeId: 'e1', sourceId: 'a', from: 'ref_image', to: 'first_frame', reason: 'only_picture' }]);
    const nodes = [clip, node('b', 'media', 300, 0, { medium: 'image' }), node('a', 'image_gen', 0, 50), node('c', 'image_gen', 150, 0)];
    const edges = [edge('e1', 'a', 'v'), edge('e2', 'b', 'v'), edge('e3', 'c', 'v')];
    const three = checkReferences(clip, nodes, edges, LIMITS);
    expect(three.roles).toEqual({ e1: 'first_frame', e2: 'last_frame', e3: 'ref_image' });
    const applied = applySuggestions(edges, three.suggestions);
    expect(applied.map(item => item.payload.role)).toEqual(['first_frame', 'last_frame', undefined]);
    expect(applied[2]).toBe(edges[2]);
  });

  it('never changes a role the person set, nor suggests a first frame for a continued clip', () => {
    const nodes = [clip, node('a', 'image_gen', 0, 0), node('b', 'image_gen', 200, 0)];
    expect(checkReferences(clip, nodes, [edge('e1', 'a', 'v', 'ref_image'), edge('e2', 'b', 'v', 'last_frame')], LIMITS).suggestions).toEqual([]);
    const continued = checkReferences(clip, [...nodes, node('p', 'video_gen', 0, 300)],
      [edge('e1', 'a', 'v'), edge('e0', 'p', 'v', 'continue_from')], LIMITS);
    expect(continued.suggestions).toEqual([]);
    expect(checkReferences(node('i', 'image_gen'), nodes, [edge('e1', 'a', 'i')], LIMITS).suggestions).toEqual([]);
  });

  it('names counts over the caps and impossible combinations', () => {
    const nodes = [clip, ...['a', 'b', 'c', 'd'].map((id, index) => node(id, 'image_gen', index * 10)), node('p', 'video_gen'), node('q', 'video_gen')];
    const found = checkReferences(clip, nodes, [
      edge('e1', 'a', 'v', 'first_frame'), edge('e2', 'b', 'v', 'first_frame'), edge('e3', 'c', 'v'), edge('e4', 'd', 'v'),
      edge('e5', 'p', 'v', 'continue_from'), edge('e6', 'q', 'v'),
    ], LIMITS);
    expect(found.problems.map(problem => problem.code)).toEqual(['too_many_images', 'too_many_videos', 'first_and_continue', 'two_firsts']);
    const lonely = checkReferences(clip, [clip, node('a', 'image_gen')], [edge('e1', 'a', 'v', 'last_frame')], LIMITS);
    expect(lonely.problems.map(problem => problem.code)).toEqual(['last_without_first']);
  });
});

describe('batch table', () => {
  it('reads pasted spreadsheet rows', () => {
    const rows = rowsFromPaste('雨夜码头\t开场\t视频\t8\n\n灯下的脸\t\t图片\n只有提示词');
    expect(rows.map(row => [row.prompt, row.title, row.kind, row.durationSeconds])).toEqual([
      ['雨夜码头', '开场', 'video_gen', 8], ['灯下的脸', '', 'image_gen', undefined], ['只有提示词', '', 'image_gen', undefined],
    ]);
    expect(rowsFromPaste(Array.from({ length: MAX_BATCH_ROWS + 5 }, (_, index) => `第${index}条`).join('\n'))).toHaveLength(MAX_BATCH_ROWS);
  });

  it('says what keeps a row back and lays the rows out as nodes in order', () => {
    expect(rowProblems(newRow('image_gen', { prompt: ' ' }), 4)).toEqual(['empty_prompt']);
    expect(rowProblems(newRow('image_gen', { prompt: 'x', count: 5 }), 4)).toEqual(['count']);
    let id = 0;
    const nodes = nodesFromRows([
      newRow('image_gen', { prompt: ' 一 ', title: '甲', model: 'seedream', count: 2 }),
      newRow('video_gen', { prompt: '二', durationSeconds: 8 }),
      newRow('image_gen', { prompt: '三' }),
    ], { x: 100, y: 50 }, () => `n${++id}`, 2);
    expect(nodes.map(item => [item.id, item.kind, item.x, item.y])).toEqual([['n1', 'image_gen', 100, 50], ['n2', 'video_gen', 460, 50], ['n3', 'image_gen', 100, 430]]);
    expect(nodes[0].payload).toEqual({ prompt: '一', params: { count: 2, model: 'seedream' }, title: '甲' });
    expect(nodes[1].payload.params).toEqual({ count: 1, durationSeconds: 8 });
  });

  it('totals the assessment the confirmation shows', () => {
    const assessment = {
      decision: 'admitted', confirmations: [],
      nodes: [{ quote: 'generate' }, { quote: 'blocked' }],
      estimate: { items: 2, paid_items: 1, unpriced_items: 1, totals: [{ currency: 'CNY', cost: 3.2 }] },
    } as unknown as RunAssessment;
    expect(totalsOf(assessment)).toEqual({ totals: [{ currency: 'CNY', cost: 3.2 }], unpriced: 1, blocked: 1, items: 2 });
  });
});

describe('hand tool', () => {
  it('picks a tool from V and H only outside text fields and shortcuts', () => {
    const field = document.createElement('input');
    expect(toolForKey({ key: 'h', metaKey: false, ctrlKey: false, altKey: false, target: document.body })).toBe('hand');
    expect(toolForKey({ key: 'V', metaKey: false, ctrlKey: false, altKey: false, target: document.body })).toBe('select');
    expect(toolForKey({ key: 'h', metaKey: false, ctrlKey: false, altKey: false, target: field })).toBeNull();
    expect(toolForKey({ key: 'v', metaKey: true, ctrlKey: false, altKey: false, target: document.body })).toBeNull();
  });

  it('pans on a left press with the hand or space, and always on the middle button', () => {
    expect(pressPans('hand', { button: 0 })).toBe(true);
    expect(pressPans('select', { button: 0 })).toBe(false);
    expect(pressPans('select', { button: 0 }, true)).toBe(true);
    expect(pressPans('select', { button: 1 })).toBe(true);
    expect(pressPans('hand', { button: 2 })).toBe(false);
  });
});

describe('version preview', () => {
  it('says what restoring would bring back, take away and change', () => {
    const current = { nodes: [node('a', 'note', 0, 0, { text: '新' }), node('b', 'note'), node('c', 'note')], edges: [edge('e1', 'a', 'b')] };
    const older = { nodes: [node('a', 'note', 0, 0, { text: '旧' }), node('b', 'note'), node('d', 'note', 300, 200)], edges: [edge('e2', 'b', 'd')] };
    const diff = diffVersions(current, older);
    expect(diff.added.map(item => item.id)).toEqual(['d']);
    expect(diff.removed.map(item => item.id)).toEqual(['c']);
    expect(diff.changed.map(item => item.id)).toEqual(['a']);
    expect([diff.edgesAdded, diff.edgesRemoved]).toEqual([1, 1]);
    expect(boundsOf(older.nodes)).toEqual({ x: 0, y: 0, width: 400, height: 280 });
    expect(boundsOf([])).toEqual({ x: 0, y: 0, width: 1, height: 1 });
  });
});

describe('canvas appearance', () => {
  it('reads three- and six-digit colours with or without # and nothing else', () => {
    expect(normaliseHex('abc')).toBe('#aabbcc');
    expect(normaliseHex('#A1B2C3')).toBe('#a1b2c3');
    expect(normaliseHex('#12345')).toBeNull();
    expect(normaliseHex('red')).toBeNull();
  });

  it('turns any stored value into a well-formed appearance', () => {
    expect(normaliseAppearance(null)).toEqual(DEFAULT_APPEARANCE);
    const odd = normaliseAppearance({ theme: 'neon', grid: 'lines', custom: { background: 'fff', brightness: 9, gridStrength: -1, grid: 'x' } });
    expect(odd.theme).toBe('follow');
    expect(odd.grid).toBe('lines');
    expect(odd.custom).toMatchObject({ background: '#ffffff', brightness: 0.5, gridStrength: 0, grid: DEFAULT_APPEARANCE.custom.grid });
  });

  it('follows the workspace unless the board chose, and a custom colour is shown exactly until brightness moves', () => {
    expect(resolveAppearance(DEFAULT_APPEARANCE, 'dark').mode).toBe('dark');
    expect(resolveAppearance({ ...DEFAULT_APPEARANCE, theme: 'light' }, 'dark').mode).toBe('light');
    const custom = { ...DEFAULT_APPEARANCE, theme: 'custom' as const, custom: { ...DEFAULT_APPEARANCE.custom, background: '#202020' } };
    expect(resolveAppearance(custom, 'light')).toMatchObject({ background: '#202020', mode: 'dark' });
    expect(resolveAppearance({ ...custom, custom: { ...custom.custom, brightness: 0.2 } }, 'light').background).toContain('oklch(from #202020');
    expect(lightness('#ffffff')).toBeCloseTo(1);
  });

  it('keeps a board its own appearance, else the account default for new boards, else following', () => {
    expect(boardAppearance('b1', 'u1')).toEqual(DEFAULT_APPEARANCE);
    saveDefaultAppearance('u1', { ...DEFAULT_APPEARANCE, theme: 'dark' });
    expect(boardAppearance('b2', 'u1').theme).toBe('dark');
    expect(boardAppearance('b2', 'u2').theme).toBe('follow');
    saveBoardAppearance('b1', { ...DEFAULT_APPEARANCE, grid: 'blank' });
    expect(boardAppearance('b1', 'u1')).toMatchObject({ theme: 'follow', grid: 'blank' });
  });
});

describe('editor size', () => {
  it('opens at min(1200px, 92vw) and never below the minimum height', () => {
    expect(defaultEditorSize({ width: 2000, height: 1000 })).toEqual({ width: 1200, height: 600 });
    expect(defaultEditorSize({ width: 800, height: 200 })).toEqual({ width: 736, height: EDITOR_MIN_HEIGHT });
    expect(clampEditorSize({ width: 10, height: 10 }, { width: 1000, height: 800 })).toEqual({ width: 360, height: 200 });
    expect(clampEditorSize({ width: 5000, height: 5000 }, { width: 1000, height: 800 })).toEqual({ width: 984, height: 680 });
  });
});
