/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const writerStylesheet = readFileSync(new URL('./WriterAgentPage.css', import.meta.url), 'utf8');

function declarationsFor(selector: string) {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = writerStylesheet.match(new RegExp(`${escapedSelector}\\s*\\{([^}]*)\\}`));

  expect(match, `Expected a CSS rule for ${selector}`).not.toBeNull();
  return match?.[1] ?? '';
}

describe('Writer timeline visual contract', () => {
  it('renders event cards with readable font sizes and clamped body copy', () => {
    const heading = declarationsFor('.writer-event-line h3');
    expect(heading).toMatch(/font-size\s*:\s*0\.82rem\s*;/);
    expect(heading).toMatch(/-webkit-line-clamp\s*:\s*2\s*;/);

    const body = declarationsFor('.writer-event-line p');
    expect(body).toMatch(/font-size\s*:\s*0\.72rem\s*;/);
    expect(body).toMatch(/-webkit-line-clamp\s*:\s*3\s*;/);
  });

  it('keeps axis beat titles readable and clamped to two lines', () => {
    const beatTitle = declarationsFor('.writer-axis__content strong');
    expect(beatTitle).toMatch(/font-size\s*:\s*0\.73rem\s*;/);
    expect(beatTitle).toMatch(/-webkit-line-clamp\s*:\s*2\s*;/);
  });
});
