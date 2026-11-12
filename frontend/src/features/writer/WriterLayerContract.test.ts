/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8');

function zIndexOf(stylesheet: string, selector: string) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const rule = stylesheet.match(new RegExp(`(?:^|[\\s}])${escaped}\\s*\\{([^}]*)\\}`))?.[1] ?? '';
  const value = rule.match(/z-index\s*:\s*(-?\d+)/)?.[1];
  expect(value, `Expected a z-index on ${selector}`).toBeDefined();
  return Number(value);
}

/** Every z-index the workbench shell (chat panel, stage header, resize handle, menus) sets. */
function shellLayers(stylesheet: string) {
  return [...stylesheet.matchAll(/([^{}]+)\{([^}]*)\}/g)]
    .filter(([, selector]) => /chat-sidebar|workbench|asset-stage-nav|popover-window|element-menu|account-menu/.test(selector))
    .map(([, , body]) => Number(body.match(/z-index\s*:\s*(-?\d+)/)?.[1] ?? Number.NaN))
    .filter(Number.isFinite);
}

describe('Writer full-screen layers', () => {
  it('lays the full-screen star field with the other full-screen tools, above the workbench and under the billing notice', () => {
    const app = read('../../index.css');
    const field = zIndexOf(read('./WriterAgentPage.css'), '.writer-relationship-canvas.is-fullscreen');
    const fullScreenTools = [
      zIndexOf(app, '.skill-manager-backdrop'),
      zIndexOf(read('../elements/AssetImageViewer.css'), '.asset-image-viewer__backdrop'),
      zIndexOf(read('../character/CharacterDesignerPage.css'), '.character-dialog-backdrop'),
    ];

    expect(field).toBeLessThanOrEqual(Math.max(...fullScreenTools));
    expect(field).toBeGreaterThan(Math.max(...shellLayers(app)));
    expect(field).toBeLessThan(zIndexOf(app, '.billing-required'));
  });
});

describe('Writer stat cards', () => {
  it('lets a stat note wrap onto a second line instead of cutting it to one', () => {
    // A card can still be about 190px wide (five to a row on a board just over 960px), and a
    // one-line note lost the missing-episode count of 「剧本正文仅 15 集，尚缺 15 集」.
    const rule = read('./WriterAgentPage.css').match(/^\.writer-stats small\s*\{([^}]*)\}/m)?.[1] ?? '';
    expect(rule).not.toMatch(/white-space\s*:\s*nowrap/);
    expect(rule).toMatch(/-webkit-line-clamp\s*:\s*2/);
  });
});
