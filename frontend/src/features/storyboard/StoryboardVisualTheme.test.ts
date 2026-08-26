/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { STORYBOARD_VISUAL_THEME } from './storyboardTheme';

const workspaceStylesheet = readFileSync(new URL('./StoryboardWorkspace.css', import.meta.url), 'utf8');

describe('StoryboardWorkspace visual theme', () => {
  it('uses the project dark surfaces and cyan accent without the legacy purple palette', () => {
    expect(STORYBOARD_VISUAL_THEME).toEqual({
      id: 'agent-dark-cyan',
      background: '#05080c',
      surface: '#08101a',
      accent: '#00f2fe',
    });
  });

  it('extends the dark-cyan theme through the workbench shell and chat sidebar', () => {
    expect(workspaceStylesheet).toContain('.workbench-layout.storyboard-mode');
    expect(workspaceStylesheet).toContain('.storyboard-mode .chat-sidebar');
    expect(workspaceStylesheet).toContain('.storyboard-mode .chat-bubble.ai');
    expect(workspaceStylesheet).toContain('.storyboard-mode .chat-sidebar .cyber-btn');
    expect(workspaceStylesheet).not.toMatch(/#(?:7654c3|9f8ad0|8e75c8)/i);
  });
});
