// @vitest-environment jsdom
/// <reference types="node" />
import { cleanup, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AgentStageTabs } from './AgentStageTabs';


const workbenchStylesheet = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8');
const tabsStylesheet = readFileSync(resolve(process.cwd(), 'src/features/workbench/AgentStageTabs.css'), 'utf8');

describe('Workbench header computed style', () => {
  let stylesheet: HTMLStyleElement;

  beforeEach(() => {
    stylesheet = document.createElement('style');
    stylesheet.textContent = `${workbenchStylesheet}\n${tabsStylesheet}`;
    document.head.append(stylesheet);
  });

  afterEach(() => {
    cleanup();
    stylesheet.remove();
  });

  it('keeps the same shared eight-Agent header visible in storyboard mode', () => {
    const { container } = render(
      <div className="workbench-layout storyboard-mode">
        <main className="asset-viewer">
          <header className="asset-stage-nav">
            <div className="asset-stage-nav__identity">
              <span aria-hidden="true">▣</span>
              <h2>《乱葬坑里有人醒》 - 看板展示大厅</h2>
            </div>
            <AgentStageTabs activeStage={4} onChange={vi.fn()} />
          </header>
        </main>
      </div>,
    );

    const header = container.querySelector('.asset-stage-nav');

    expect(header).not.toBeNull();
    expect(getComputedStyle(header as Element).display).toBe('flex');
    expect(screen.getByRole('heading', { name: '《乱葬坑里有人醒》 - 看板展示大厅' })).toBeTruthy();
    expect(screen.getByRole('navigation', { name: '八种制作 Agent' }).querySelectorAll('button')).toHaveLength(8);
    expect(screen.getByRole('button', { name: '4.分镜' }).getAttribute('aria-current')).toBe('step');
  });
});
