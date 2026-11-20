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
    // The identity yields to the tools and tabs but keeps a floor wide enough to read the title.
    expect(identity).toMatch(/min-width\s*:\s*min\(\d+rem,\s*100%\)\s*;/);
    expect(identity).toMatch(/flex\s*:\s*1 1 0\s*;/);
    expect(title).toMatch(/min-width\s*:\s*0\s*;/);
    expect(title).toMatch(/white-space\s*:\s*nowrap\s*;/);
    expect(title).toMatch(/text-overflow\s*:\s*ellipsis\s*;/);
    expect(title).toMatch(/overflow\s*:\s*hidden\s*;/);
  });

  it('does not wrap the eight Agent tabs onto a second line on the desktop header', () => {
    const tabs = declarationsFor(tabsStylesheet, '.agent-stage-tabs');

    expect(tabs).toMatch(/flex-wrap\s*:\s*nowrap\s*;/);
  });

  it('scrolls the Agent tabs inside their own strip instead of widening the header', () => {
    const tabs = declarationsFor(tabsStylesheet, '.agent-stage-tabs');

    expect(tabs).toMatch(/flex-shrink\s*:\s*1\s*;/);
    expect(tabs).toMatch(/min-width\s*:\s*0\s*;/);
    expect(tabs).toMatch(/overflow-x\s*:\s*auto\s*;/);
    // A scrolling flex strip squashes its children unless each tab refuses to shrink.
    expect(tabsStylesheet).toMatch(/\.agent-stage-tab\.is-active\s*\{\s*flex\s*:\s*none\s*;/);
  });

  it('fills the viewport: no header sits above the workbench', () => {
    expect(declarationsFor(appStylesheet, '.workbench-layout')).toMatch(/height\s*:\s*100vh\s*;\s*height\s*:\s*100dvh\s*;/);
    expect(appStylesheet).not.toMatch(/100vh - 64px/);
  });

  it('keeps the top-up notice above every full-screen tool and dialog', () => {
    const notice = Number(declarationsFor(appStylesheet, '.billing-required').match(/z-index\s*:\s*(\d+)\s*;/)?.[1]);
    const overlays = [...appStylesheet.matchAll(/z-index\s*:\s*(\d+)\s*;/g)].map(match => Number(match[1]));

    expect(notice).toBe(Math.max(...overlays));
    expect(notice).toBeGreaterThan(100000);
  });

  it('never waits on a remote stylesheet before the first paint', () => {
    expect(appStylesheet).not.toMatch(/@import\s+url\(\s*['"]?https?:/);
    expect(appStylesheet).toMatch(/font-family\s*:[^;]*'PingFang SC'[^;]*'Microsoft YaHei'[^;]*sans-serif\s*;/);
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
