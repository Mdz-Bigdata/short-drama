import { describe, expect, it } from 'vitest';

import { ASPECT_PRESETS, centerCross, fitFrame, letterboxBars, parseAspectRatio, safeFrame, thirdsLines } from './compositionGeometry';

describe('parseAspectRatio', () => {
  it('reads every preset and a custom W:H', () => {
    expect(ASPECT_PRESETS.map(parseAspectRatio)).toEqual([9 / 16, 16 / 9, 1, 4 / 3, 3 / 4, 21 / 9, 2.39]);
    expect(parseAspectRatio('1080x1920')).toBe(1080 / 1920);
    expect(parseAspectRatio(' 16：9 ')).toBe(16 / 9);
  });

  it('refuses what is not a ratio', () => {
    ['', '16', '16:0', '-4:3', 'a:b', '1:2:3', '1000:1'].forEach(value => expect(parseAspectRatio(value)).toBeNull());
  });
});

describe('fitFrame and letterboxBars', () => {
  it('pillar-boxes a portrait frame in a landscape view', () => {
    const frame = fitFrame(1600, 900, 9 / 16);
    expect(frame).toEqual({ x: (1600 - 506.25) / 2, y: 0, width: 506.25, height: 900 });
    const bars = letterboxBars(1600, 900, frame);
    expect(bars).toHaveLength(2);
    expect(bars.every(bar => bar.height === 900 && bar.width === frame.x)).toBe(true);
  });

  it('letter-boxes a scope frame in a portrait view', () => {
    const frame = fitFrame(900, 1600, 2.39);
    expect(frame.width).toBe(900);
    expect(frame.height).toBeCloseTo(900 / 2.39, 6);
    const bars = letterboxBars(900, 1600, frame);
    expect(bars).toHaveLength(2);
    expect(bars[0].height + bars[1].height + frame.height).toBeCloseTo(1600, 6);
  });

  it('needs no bars when the view already has the aspect, and survives an empty view', () => {
    expect(letterboxBars(1600, 900, fitFrame(1600, 900, 16 / 9))).toEqual([]);
    expect(fitFrame(0, 900, 1)).toEqual({ x: 0, y: 0, width: 0, height: 0 });
  });
});

describe('guides', () => {
  const frame = { x: 100, y: 50, width: 900, height: 600 };

  it('puts thirds on the frame, not on the view', () => {
    const lines = thirdsLines(frame);
    expect(lines).toHaveLength(4);
    expect(lines[0]).toEqual({ x1: 400, y1: 50, x2: 400, y2: 650 });
    expect(lines[3]).toEqual({ x1: 100, y1: 450, x2: 1000, y2: 450 });
  });

  it('insets the safe frame by 9% on every side', () => {
    const safe = safeFrame(frame);
    expect(safe.x).toBeCloseTo(181, 6);
    expect(safe.y).toBeCloseTo(104, 6);
    expect(safe.width).toBeCloseTo(738, 6);
    expect(safe.height).toBeCloseTo(492, 6);
  });

  it('centres the cross with equal arms', () => {
    const [horizontal, vertical] = centerCross(frame);
    expect((horizontal.x1 + horizontal.x2) / 2).toBe(550);
    expect((vertical.y1 + vertical.y2) / 2).toBe(350);
    expect(horizontal.x2 - horizontal.x1).toBe(vertical.y2 - vertical.y1);
  });
});
