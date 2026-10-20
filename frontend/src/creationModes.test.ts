import { describe, expect, it } from 'vitest';

import { CREATION_MODE_OPTIONS, EMPTY_AD_BRIEF } from './types';

describe('creation modes', () => {
  it('offers the three kinds the backend accepts, drama first as the default', () => {
    // backend app/schema/drama.py: creation_mode: Literal["drama", "narration", "ad"]
    expect(CREATION_MODE_OPTIONS.map(option => option.id)).toEqual(['drama', 'narration', 'ad']);
    expect(CREATION_MODE_OPTIONS.every(option => option.label && option.hint)).toBe(true);
  });

  it('starts an ad brief with every field the request schema names, all empty', () => {
    // backend AdBrief: product, selling_points, audience, call_to_action (camelCase on the wire)
    expect(EMPTY_AD_BRIEF).toEqual({ product: '', sellingPoints: '', audience: '', callToAction: '' });
  });
});
