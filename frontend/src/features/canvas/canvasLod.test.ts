import { describe, expect, it } from 'vitest';

import { SHELL_ZOOM } from './canvasGeometry';
import { lodFor, overviewMode, OVERVIEW_ENTER_ZOOM, OVERVIEW_LEAVE_ZOOM } from './canvasLod';

const card = { id: 'n', kind: 'media' as const };

describe('canvas level of detail', () => {
  it('enters overview below 0.23 and leaves it only at 0.27', () => {
    expect(OVERVIEW_ENTER_ZOOM).toBeLessThan(OVERVIEW_LEAVE_ZOOM);
    expect(OVERVIEW_LEAVE_ZOOM).toBeLessThan(SHELL_ZOOM);
    expect(overviewMode(0.05, false)).toBe(true);
    expect(overviewMode(0.24, false)).toBe(false);
    expect(overviewMode(0.24, true)).toBe(true);
    expect(overviewMode(0.26, true)).toBe(true);
    expect(overviewMode(0.27, true)).toBe(false);
  });

  it('keeps the same detail while the zoom wobbles inside the hysteresis band', () => {
    let was = false;
    const seen: string[] = [];
    for (const zoom of [0.3, 0.22, 0.25, 0.26, 0.24, 0.28, 0.25]) {
      seen.push(lodFor(card, { zoom, inView: true, inEnter: true, overviewWas: was }));
      was = overviewMode(zoom, was);
    }
    expect(seen).toEqual(['preview', 'shell', 'shell', 'shell', 'shell', 'preview', 'preview']);
  });

  it('draws on-screen nodes full above SHELL_ZOOM and a preview below it, full again on attention', () => {
    expect(lodFor(card, { zoom: 1, inView: true, inEnter: true })).toBe('full');
    expect(lodFor(card, { zoom: SHELL_ZOOM - 0.01, inView: true, inEnter: true })).toBe('preview');
    expect(lodFor(card, { zoom: 0.3, inView: true, inEnter: true, hovered: true })).toBe('full');
    expect(lodFor(card, { zoom: 0.3, inView: true, inEnter: true, active: true })).toBe('full');
  });

  it('never mounts thousands of editors in overview, yet keeps the one being edited', () => {
    const levels = Array.from({ length: 5000 }, (_, i) => lodFor(card, { zoom: 0.05, inView: true, inEnter: true, overviewWas: true, editing: i === 23 }));
    expect(levels.filter(level => level === 'full')).toHaveLength(1);
    expect(levels.filter(level => level === 'shell')).toHaveLength(4999);
    expect(lodFor(card, { zoom: 0.05, inView: true, inEnter: true, hovered: true })).toBe('preview');
  });

  it('drops off-screen nodes to a preview in the buffer and a shell beyond it', () => {
    expect(lodFor(card, { zoom: 1, inView: false, inEnter: true })).toBe('preview');
    expect(lodFor(card, { zoom: 1, inView: false, inEnter: false })).toBe('shell');
    expect(lodFor(card, { zoom: 0.1, inView: false, inEnter: true })).toBe('shell');
    expect(lodFor(card, { zoom: 1, inView: false, inEnter: false, active: true })).toBe('preview');
    expect(lodFor(card, { zoom: 1, inView: false, inEnter: false, editing: true })).toBe('full');
    expect(lodFor({ id: 'g', kind: 'group' }, { zoom: 1, inView: false, inEnter: true })).toBe('shell');
  });
});
