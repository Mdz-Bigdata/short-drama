import { describe, expect, it } from 'vitest';

import { countCeiling, countOf, DOCK_GAP, DOCK_HEIGHT, DOCK_MARGIN, DOCK_WIDTH, dockPlacement, hasComposer, modelChoices, quoteLine, withParam } from './canvasComposer';
import type { RunAssessment, RunOptions } from './canvasTypes';

const VIEW = { x: 0, y: 0, zoom: 1 };
const SCREEN = { width: 1200, height: 800 };

const OPTIONS: RunOptions = {
  models: { image: 'seedream', video: 'seedance', audio: 'local-tts' },
  enabled: { image: ['seedream', 'other-image'], video: [], audio: [] },
  video_durations: [5, 10],
  versions: { max: 4, kinds: ['image_gen', 'video_gen'] },
  kinds: {},
};

function assessment(over: Partial<RunAssessment['nodes'][number]> = {}, estimate: Partial<RunAssessment['estimate']> = {}): RunAssessment {
  return {
    decision: 'admitted', confirmations: [],
    nodes: [{ node_id: 'n', kind: 'image_gen', label: '图', medium: 'image', model: 'seedream', quote: 'generate', paid: true, problems: [], requested_seconds: 0, scripted_seconds: 0, estimate: { priced: true, cost: 0.6, currency: 'CNY' }, ...over }],
    estimate: { items: 1, paid_items: 1, unpriced_items: 0, totals: [{ currency: 'CNY', cost: 0.6 }], ...estimate },
  };
}

describe('where the dock goes', () => {
  it('sits centred under the node', () => {
    expect(dockPlacement({ x: 400, y: 100, width: 300, height: 200 }, VIEW, SCREEN)).toEqual({ width: DOCK_WIDTH, left: 550 - DOCK_WIDTH / 2, top: 300 + DOCK_GAP });
  });

  it('follows the view: pan and zoom move it with the node', () => {
    const placed = dockPlacement({ x: 400, y: 100, width: 300, height: 200 }, { x: 100, y: 50, zoom: 0.5 }, SCREEN)!;
    expect(placed.top).toBe(50 + 150 + DOCK_GAP);
    expect(placed.left).toBe(Math.round(100 + 200 + 75 - DOCK_WIDTH / 2));
  });

  it('stays inside the view near an edge and under a node that reaches the bottom', () => {
    expect(dockPlacement({ x: 0, y: 100, width: 100, height: 100 }, VIEW, SCREEN)!.left).toBe(DOCK_MARGIN);
    expect(dockPlacement({ x: 1150, y: 100, width: 100, height: 100 }, VIEW, SCREEN)!.left).toBe(SCREEN.width - DOCK_WIDTH - DOCK_MARGIN);
    expect(dockPlacement({ x: 400, y: 500, width: 300, height: 290 }, VIEW, SCREEN)!.top).toBe(SCREEN.height - DOCK_HEIGHT - DOCK_MARGIN);
  });

  it('narrows on a narrow view and is not drawn for a node out of sight or a sliver of a view', () => {
    expect(dockPlacement({ x: 10, y: 10, width: 100, height: 100 }, VIEW, { width: 400, height: 800 })!.width).toBe(400 - DOCK_MARGIN * 2);
    expect(dockPlacement({ x: 5000, y: 10, width: 100, height: 100 }, VIEW, SCREEN)).toBeNull();
    expect(dockPlacement({ x: 10, y: -900, width: 100, height: 100 }, VIEW, SCREEN)).toBeNull();
    expect(dockPlacement({ x: 10, y: 10, width: 100, height: 100 }, VIEW, { width: 200, height: 800 })).toBeNull();
  });
});

describe('what the dock offers', () => {
  it('is drawn for the kinds that generate from a prompt', () => {
    expect(['image_gen', 'video_gen', 'audio_gen'].every(kind => hasComposer({ kind: kind as 'image_gen' }))).toBe(true);
    expect(['note', 'media', 'tool', 'group', 'previz', 'video_compose'].some(kind => hasComposer({ kind: kind as 'note' }))).toBe(false);
  });

  it('lists the enabled models with the project\'s own among them', () => {
    expect(modelChoices({ kind: 'image_gen' }, OPTIONS)).toEqual({ fallback: 'seedream', models: ['seedream', 'other-image'] });
    expect(modelChoices({ kind: 'video_gen' }, OPTIONS)).toEqual({ fallback: 'seedance', models: ['seedance'] });
    expect(modelChoices({ kind: 'image_gen' }, null)).toBeNull();
  });

  it('offers a count only where the server does', () => {
    expect(countCeiling({ kind: 'image_gen' }, OPTIONS)).toBe(4);
    expect(countCeiling({ kind: 'audio_gen' }, OPTIONS)).toBe(1);
    expect(countCeiling({ kind: 'image_gen' }, { ...OPTIONS, versions: undefined })).toBe(1);
    expect(countCeiling({ kind: 'image_gen' }, null)).toBe(1);
  });

  it('holds the count between one and the ceiling', () => {
    expect(countOf({ count: 3 }, 4)).toBe(3);
    expect(countOf({ count: 9 }, 4)).toBe(4);
    expect(countOf({ count: 0 }, 4)).toBe(1);
    expect(countOf({ count: 'x' as unknown as number }, 4)).toBe(1);
    expect(countOf(undefined, 4)).toBe(1);
  });

  it('drops a parameter that is back at its default', () => {
    expect(withParam({ size: '1x1' }, 'count', 3, 1)).toEqual({ size: '1x1', count: 3 });
    expect(withParam({ size: '1x1', count: 3 }, 'count', 1, 1)).toEqual({ size: '1x1' });
    expect(withParam({ model: 'm' }, 'model', '')).toEqual({});
  });
});

describe('the quote line', () => {
  it('says the cost, with the seconds and the number of results when there are any', () => {
    expect(quoteLine(assessment(), 'n')).toEqual({ text: '参考费用约 0.6 CNY', tone: 'cost' });
    expect(quoteLine(assessment({ versions: 3, requested_seconds: 5 }), 'n').text).toBe('参考费用约 0.6 CNY · 5 秒 · 3 个结果');
  });

  it('says so when nothing is priced or nothing is paid', () => {
    expect(quoteLine(assessment({}, { unpriced_items: 1, totals: [] }), 'n')).toEqual({ text: '未定价', tone: 'cost' });
    expect(quoteLine(assessment({ paid: false }, { paid_items: 0, totals: [] }), 'n').tone).toBe('free');
  });

  it('gives the first thing that stops the run instead of a price', () => {
    const blocked = assessment({ problems: [{ code: 'hint', message: '提示', blocking: false }, { code: 'no_prompt', message: '还没有提示词', blocking: true }] });
    expect(quoteLine(blocked, 'n')).toEqual({ text: '还没有提示词', tone: 'blocked' });
  });
});
