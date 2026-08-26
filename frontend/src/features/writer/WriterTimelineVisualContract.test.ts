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
  it('renders event titles and body copy at the requested compact 12px size', () => {
    expect(declarationsFor('.writer-event-line h3')).toMatch(/font-size\s*:\s*12px\s*;/);
    expect(declarationsFor('.writer-event-line p')).toMatch(/font-size\s*:\s*12px\s*;/);
  });
});
