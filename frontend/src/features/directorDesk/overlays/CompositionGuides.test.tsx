// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { CompositionGuides } from './CompositionGuides';

const ALL = { aspect: '', frame: true, thirds: true, safe: true, cross: true };

describe('CompositionGuides', () => {
  afterEach(cleanup);

  it('draws every guide on the delivery frame, with no mask when the aspects agree', () => {
    render(<CompositionGuides deliveryAspect={9 / 16} guides={ALL} />);
    const overlay = screen.getByRole('img', { name: '构图辅助线' });
    expect(overlay.querySelectorAll('[data-guide="mask"]')).toHaveLength(0);
    expect(overlay.querySelectorAll('[data-guide="thirds"]')).toHaveLength(4);
    expect(overlay.querySelectorAll('[data-guide="cross"]')).toHaveLength(2);
    expect(overlay.querySelector('[data-guide="safe"]')?.getAttribute('x')).toBe('90');
  });

  it('masks a wide frame inside a portrait delivery and honours the toggles', () => {
    render(<CompositionGuides deliveryAspect={9 / 16} guides={{ ...ALL, aspect: '16:9', thirds: false, cross: false, safe: false }} />);
    const overlay = screen.getByRole('img', { name: '构图辅助线' });
    expect(overlay.querySelectorAll('[data-guide="mask"]')).toHaveLength(2);
    expect(Number(overlay.querySelector('[data-guide="frame"]')?.getAttribute('height'))).toBeCloseTo(562.5, 3);
    expect(overlay.querySelectorAll('[data-guide="thirds"], [data-guide="cross"], [data-guide="safe"]')).toHaveLength(0);
  });

  it('falls back to the delivery aspect on a custom ratio that does not parse', () => {
    render(<CompositionGuides deliveryAspect={16 / 9} guides={{ ...ALL, aspect: 'abc' }} />);
    expect(screen.getByRole('img', { name: '构图辅助线' }).querySelectorAll('[data-guide="mask"]')).toHaveLength(0);
  });
});
