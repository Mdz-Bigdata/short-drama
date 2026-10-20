import { describe, expect, it } from 'vitest';

import { groupEpisodeGaps, normalizeMissingEpisodes } from './episodeGaps';

describe('episode gap labels', () => {
  it('groups only consecutive gaps and retains separated episode numbers', () => {
    expect(groupEpisodeGaps([25, 17, 3, 16, 18])).toEqual([
      { first: 3, last: 3, label: '3' },
      { first: 16, last: 18, label: '16–18' },
      { first: 25, last: 25, label: '25' },
    ]);
  });

  it('ignores invalid and duplicate legacy numbers without mutating inputs', () => {
    const numbers = [25, 16, 16, -1, 0, 2.5, NaN, 201];
    const before = [...numbers];
    expect(normalizeMissingEpisodes(numbers)).toEqual([16, 25]);
    expect(numbers).toEqual(before);
  });
});
