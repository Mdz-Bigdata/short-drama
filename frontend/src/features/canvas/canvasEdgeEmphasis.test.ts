import { describe, expect, it } from 'vitest';

import { EDGE_MARKERS, edgeEmphasis, edgeMarker } from './canvasEdgeEmphasis';

const edge = { id: 'e1', source: 'a', target: 'b' };
const none: ReadonlySet<string> = new Set();

describe('edge emphasis', () => {
  it('draws every connection as usual while no node is selected', () => {
    expect(edgeEmphasis(edge, none, none)).toBe('plain');
    expect(edgeEmphasis(edge, none, new Set(['e1']))).toBe('plain');
  });

  it('lifts the connections into and out of a selected node', () => {
    expect(edgeEmphasis(edge, new Set(['a']), none)).toBe('linked');
    expect(edgeEmphasis(edge, new Set(['b']), none)).toBe('linked');
    expect(edgeEmphasis(edge, new Set(['a', 'b', 'z']), none)).toBe('linked');
  });

  it('lets the rest recede, except a connection picked by hand', () => {
    expect(edgeEmphasis(edge, new Set(['z']), none)).toBe('dim');
    expect(edgeEmphasis(edge, new Set(['z']), new Set(['e1']))).toBe('plain');
  });
});

describe('edge arrowheads', () => {
  it('has one arrowhead per colour a line may take, and names only those', () => {
    const named = [
      edgeMarker('reference', false), edgeMarker('dependency', false), edgeMarker('lineage', false),
      edgeMarker('variant', false), edgeMarker('continuity', false), edgeMarker('reference', true), edgeMarker('lineage', true),
    ];
    expect(new Set(named)).toEqual(new Set(EDGE_MARKERS));
    expect(edgeMarker('dependency', true)).toBe('cn-arrow-selected');
  });
});
