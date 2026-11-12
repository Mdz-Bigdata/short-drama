import { describe, expect, it } from 'vitest';

import { applySelection, marqueeHits, marqueeMode, selectionPreview, selectionStrategy } from './canvasSelectionModes';
import type { CanvasNode } from './canvasTypes';

const node = (id: string, x: number, y: number, width = 100, height = 100, kind: CanvasNode['kind'] = 'note'): CanvasNode => ({
  id, kind, track: 'freezone', x, y, width, height, artifact_id: null, payload: {},
});

describe('selection modes', () => {
  it('reads the marquee mode from the drag direction', () => {
    expect(marqueeMode(0, 100)).toBe('contain');
    expect(marqueeMode(100, 100)).toBe('contain');
    expect(marqueeMode(100, 0)).toBe('intersect');
  });

  it('maps modifiers to replace, add, toggle and subtract', () => {
    expect(selectionStrategy({})).toBe('replace');
    expect(selectionStrategy({ shift: true })).toBe('add');
    expect(selectionStrategy({ meta: true })).toBe('toggle');
    expect(selectionStrategy({ ctrl: true })).toBe('toggle');
    expect(selectionStrategy({ alt: true, meta: true, shift: true })).toBe('subtract');
    expect(selectionStrategy({ meta: true, shift: true })).toBe('toggle');
  });

  it('applies each strategy against the selection the gesture began with', () => {
    const current = new Set(['a', 'b']);
    const hits = ['b', 'c'];
    expect([...applySelection(current, hits, {})]).toEqual(['b', 'c']);
    expect([...applySelection(current, hits, { shift: true })]).toEqual(['a', 'b', 'c']);
    expect([...applySelection(current, hits, { meta: true })]).toEqual(['a', 'c']);
    expect([...applySelection(current, hits, { alt: true })]).toEqual(['a']);
    expect([...applySelection(current, hits, 'toggle')]).toEqual(['a', 'c']);
    expect([...current]).toEqual(['a', 'b']);
  });

  it('previews what a marquee would add and drop', () => {
    const preview = selectionPreview(new Set(['a', 'b']), new Set(['b', 'c']), {});
    expect(preview).toEqual({ adding: new Set(['c']), removing: new Set(['a']) });
    expect(selectionPreview(new Set(['a', 'b']), new Set(['b', 'c']), { alt: true })).toEqual({ adding: new Set(), removing: new Set(['b']) });
  });

  it('hits wholly held nodes in contain mode and touched ones in intersect mode', () => {
    const nodes = [node('in', 10, 10, 50, 50), node('edge', 80, 80, 50, 50), node('out', 400, 400)];
    const rect = { x: 0, y: 0, width: 100, height: 100 };
    expect(marqueeHits(nodes, rect, 'contain')).toEqual(['in']);
    expect(marqueeHits(nodes, rect, 'intersect')).toEqual(['in', 'edge']);
  });

  it('counts a group only when wholly inside, in either mode', () => {
    const nodes = [node('g', 0, 0, 500, 400, 'group'), node('a', 20, 60, 80, 80)];
    const inner = { x: 10, y: 50, width: 120, height: 120 };
    expect(marqueeHits(nodes, inner, 'intersect')).toEqual(['a']);
    expect(marqueeHits(nodes, inner, 'contain')).toEqual(['a']);
    expect(marqueeHits(nodes, { x: -10, y: -10, width: 600, height: 600 }, 'intersect')).toEqual(['g', 'a']);
  });

  it('skips hidden members and accepts an index', () => {
    const nodes = [node('a', 0, 0), node('b', 10, 10)];
    const rect = { x: -5, y: -5, width: 200, height: 200 };
    expect(marqueeHits(nodes, rect, 'contain', new Set(['b']))).toEqual(['a']);
    const index = { candidates: () => [nodes[1]] };
    expect(marqueeHits(index, rect, 'contain')).toEqual(['b']);
  });
});
