// @vitest-environment jsdom
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ScriptOutline } from './ScriptOutline';
import type { WriterScene } from './types';

const scenes: WriterScene[] = [
  {
    scene_id: 'E1S01',
    duration: '8s',
    content: '谢云谣：住手。\n旁白：夜色渐深。\n谢云谣（内心独白）：不能退。',
    characters: ['谢云谣'],
  },
];

describe('ScriptOutline dialogue tag variants', () => {
  afterEach(() => {
    cleanup();
  });

  it('renders each dialogue kind with its own variant class', () => {
    const { container } = render(<ScriptOutline scenes={scenes} />);
    const tags = [...container.querySelectorAll('.writer-outline__tag')];
    const byKind = new Map(tags.map(tag => [tag.textContent, tag]));

    const spoken = byKind.get('台词');
    const narration = byKind.get('旁白');
    const monologue = byKind.get('内心独白');
    expect(spoken).toBeTruthy();
    expect(narration).toBeTruthy();
    expect(monologue).toBeTruthy();

    // 台词是基础样式，不带任何 is-* 变体类。
    expect(spoken!.className).toBe('writer-outline__tag');
    // 旁白 / 内心独白 各自带专属变体类，且互不串位。
    expect(narration!.classList.contains('is-narration')).toBe(true);
    expect(narration!.classList.contains('is-monologue')).toBe(false);
    expect(monologue!.classList.contains('is-monologue')).toBe(true);
    expect(monologue!.classList.contains('is-narration')).toBe(false);
  });
});
