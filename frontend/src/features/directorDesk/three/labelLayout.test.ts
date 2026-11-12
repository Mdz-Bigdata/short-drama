import { describe, expect, it } from 'vitest';

import { boardFor, createLabelBoard, estimatedEms, labelRank, LIFT_HIDDEN, MAX_LIFT, placeLabels, type LabelBoard, type LabelKind } from './labelLayout';

interface Spot {
  kind: LabelKind;
  selected?: boolean;
  x: number;
  bottom: number;
  width?: number;
  height?: number;
  depth?: number;
  onScreen?: boolean;
}

function laidOut(spots: Spot[]): number[] {
  const board: LabelBoard = createLabelBoard(spots.length);
  board.count = spots.length;
  spots.forEach((spot, index) => {
    board.x[index] = spot.x;
    board.bottom[index] = spot.bottom;
    board.width[index] = spot.width ?? 60;
    board.height[index] = spot.height ?? 20;
    board.depth[index] = spot.depth ?? 5;
    board.rank[index] = labelRank(spot.kind, spot.selected ?? false);
    board.onScreen[index] = spot.onScreen === false ? 0 : 1;
  });
  placeLabels(board);
  return Array.from(board.lift.subarray(0, spots.length));
}

describe('placeLabels', () => {
  it('stacks a recorder and a desk over the professor standing at them, the professor keeping his place', () => {
    // 录音笔 on 书案, 周教授 beside it: three names a few pixels apart in the default view.
    const lifts = laidOut([
      { kind: 'prop', x: 402, bottom: 300, depth: 6.1 },
      { kind: 'prop', x: 396, bottom: 306, depth: 6.4 },
      { kind: 'actor', x: 410, bottom: 296, depth: 6.6 },
    ]);
    expect(lifts[2]).toBe(0);
    // The nearer set piece stands on the professor's name (its top at 276), the other one on that.
    expect(lifts[0]).toBeCloseTo((300 - 276) / 20, 6);
    expect(lifts[1]).toBeCloseTo((306 - 256) / 20, 6);
  });

  it('leaves names that do not touch where they are', () => {
    expect(laidOut([
      { kind: 'prop', x: 100, bottom: 300 },
      { kind: 'actor', x: 200, bottom: 300 },
      { kind: 'camera', x: 100, bottom: 250 },
    ])).toEqual([0, 0, 0]);
  });

  it('keeps what is picked in place and moves the figure instead', () => {
    expect(laidOut([
      { kind: 'actor', x: 300, bottom: 300 },
      { kind: 'prop', selected: true, x: 300, bottom: 300 },
    ])).toEqual([1, 0]);
  });

  it('never moves a measured distance, not even for a picked name nearer the view', () => {
    // The measure tool leaves the selection alone: the picked figure's name stands over the two points just measured.
    expect(laidOut([
      { kind: 'actor', selected: true, x: 300, bottom: 300, depth: 4 },
      { kind: 'distance', selected: true, x: 300, bottom: 300, depth: 6 },
    ])).toEqual([1, 0]);
  });

  it('puts a lens under a figure and over a set piece', () => {
    expect(laidOut([
      { kind: 'prop', x: 300, bottom: 300 },
      { kind: 'camera', x: 300, bottom: 300 },
      { kind: 'actor', x: 300, bottom: 300 },
    ])).toEqual([2, 1, 0]);
  });

  it('climbs over every name in its way, not just the first', () => {
    // One height up is taken by a figure's name standing 10 px higher: the set piece goes on top of that one.
    expect(laidOut([
      { kind: 'actor', x: 300, bottom: 300 },
      { kind: 'actor', x: 300, bottom: 270, depth: 4 },
      { kind: 'prop', x: 300, bottom: 300 },
    ])).toEqual([0, 0, 2.5]);
  });

  it('gives way to a dot once it would climb more than three heights', () => {
    const lifts = laidOut(Array.from({ length: MAX_LIFT + 2 }, (_, index) => ({ kind: 'prop' as const, x: 300, bottom: 300, depth: index + 1 })));
    expect(lifts.slice(0, MAX_LIFT + 1)).toEqual([0, 1, 2, 3]);
    expect(lifts[MAX_LIFT + 1]).toBe(LIFT_HIDDEN);
  });

  it('gives way to a dot rather than climb off the top of the pane', () => {
    expect(laidOut([
      { kind: 'actor', x: 300, bottom: 30 },
      { kind: 'prop', x: 300, bottom: 30 },
    ])).toEqual([0, LIFT_HIDDEN]);
  });

  it('always shows a picked name, even with no room left', () => {
    const crowd: Spot[] = Array.from({ length: MAX_LIFT + 1 }, () => ({ kind: 'actor', selected: true, x: 300, bottom: 300 }));
    const lifts = laidOut([...crowd, { kind: 'prop', selected: true, x: 300, bottom: 300 }]);
    expect(lifts).not.toContain(LIFT_HIDDEN);
  });

  it('lets a name that gave way take no room from the ones after it', () => {
    // A wide name with no room above the figure gives way; the next set piece reaches into where it would have been, clear of the figure.
    expect(laidOut([
      { kind: 'actor', x: 300, bottom: 30 },
      { kind: 'prop', x: 300, bottom: 30, width: 200, depth: 1 },
      { kind: 'prop', x: 380, bottom: 30, depth: 2 },
    ])).toEqual([0, LIFT_HIDDEN, 0]);
  });

  it('takes no room for a name behind the view or off the pane', () => {
    expect(laidOut([
      { kind: 'actor', x: 300, bottom: 300, onScreen: false },
      { kind: 'prop', x: 300, bottom: 300 },
    ])).toEqual([0, 0]);
  });
});

describe('estimatedEms', () => {
  it('counts a Han character as one letter height and a digit as a little over half', () => {
    expect(estimatedEms('周教授')).toBe(3);
    expect(estimatedEms('12')).toBeCloseTo(1.2, 6);
    expect(estimatedEms('1.20 m')).toBeCloseTo(3.6, 6);
  });
});

describe('boardFor', () => {
  it('keeps the board while it is big enough, so a frame allocates nothing', () => {
    const board = createLabelBoard(32);
    expect(boardFor(board, 31)).toBe(board);
    const grown = boardFor(board, 40);
    expect(grown).not.toBe(board);
    expect(grown.x.length).toBeGreaterThanOrEqual(64);
  });
});
