/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const appStylesheet = readFileSync(new URL('../../index.css', import.meta.url), 'utf8');
const tabsStylesheet = readFileSync(new URL('./AgentStageTabs.css', import.meta.url), 'utf8');

function declarationsFor(stylesheet: string, selector: string) {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = stylesheet.match(new RegExp(`(?:^|\\n)\\s*${escapedSelector}\\s*\\{([^}]*)\\}`));

  expect(match, `Expected a CSS rule for ${selector}`).not.toBeNull();
  return match?.[1] ?? '';
}

describe('Workbench header visual contract', () => {
  it('keeps the screenplay identity and Agent navigation in one compact row', () => {
    const header = declarationsFor(appStylesheet, '.asset-stage-nav');
    const identity = declarationsFor(appStylesheet, '.asset-stage-nav > div:first-child');
    const title = declarationsFor(appStylesheet, '.asset-stage-nav h2');

    expect(header).toMatch(/flex-wrap\s*:\s*nowrap\s*;/);
    expect(header).toMatch(/gap\s*:/);
    expect(identity).toMatch(/min-width\s*:\s*0\s*;/);
    expect(title).toMatch(/white-space\s*:\s*nowrap\s*;/);
    expect(title).toMatch(/text-overflow\s*:\s*ellipsis\s*;/);
    expect(title).toMatch(/overflow\s*:\s*hidden\s*;/);
  });

  it('does not wrap the eight Agent tabs onto a second line on the desktop header', () => {
    const tabs = declarationsFor(tabsStylesheet, '.agent-stage-tabs');

    expect(tabs).toMatch(/flex-wrap\s*:\s*nowrap\s*;/);
    expect(tabs).toMatch(/flex-shrink\s*:\s*0\s*;/);
  });

  it('keeps the screenplay identity inside the narrow mobile workbench', () => {
    const mobileIdentity = declarationsFor(
      appStylesheet,
      '.workbench-layout:not(.storyboard-mode) .asset-stage-nav__identity',
    );

    expect(mobileIdentity).toMatch(/width\s*:\s*100%\s*;/);
    expect(mobileIdentity).toMatch(/max-width\s*:\s*100%\s*;/);
  });

  it('stacks the storyboard shell before its 980px minimum grid width can clip the sidebar', () => {
    expect(appStylesheet).toMatch(
      /@media\s*\(max-width:\s*980px\)[\s\S]*?\.workbench-layout\.storyboard-mode\s*\{[^}]*display\s*:\s*block\s*;/,
    );
  });
});
