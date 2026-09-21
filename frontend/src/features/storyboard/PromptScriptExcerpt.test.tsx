// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { PromptScriptExcerpt } from './PromptScriptExcerpt';
import { scriptReadingView } from './storyboardPromptSummary';
import type { StoryboardPromptDetail } from './storyboardPromptTypes';

const source = `第1集 血碑 场景1：天文台 沈砚划出三道血痕。 场景2：宫门 贺兰霆走远。 第2集 朝会 场景1：大殿 ${'皇帝凝视群臣。'.repeat(100)}全剧原文最后一句。`;
const detail = {
  episode: '第1集', shot_number: 'E1S01', scene_number: 1,
  foundation: { script_text: source },
} as StoryboardPromptDetail;

describe('PromptScriptExcerpt', () => {
  afterEach(cleanup);

  it('keeps emoji code points intact at a reading paragraph boundary', () => {
    const unicodeSource = '甲'.repeat(239) + '😀' + '乙'.repeat(240);
    const view = scriptReadingView({ ...detail, foundation: { ...detail.foundation, script_text: unicodeSource } });
    expect(view.sourceParagraphs[0]).toContain('😀');
    expect(view.sourceParagraphs.join('')).toBe(unicodeSource);
  });

  it('shows the current scene and a bounded preview instead of every episode by default', () => {
    render(<PromptScriptExcerpt detail={detail} />);

    expect(screen.getByRole('heading', { name: '第1集 · E1S01' })).toBeTruthy();
    expect(screen.getByText(/沈砚划出三道血痕/)).toBeTruthy();
    expect(screen.queryByText(/皇帝凝视群臣/)).toBeNull();
    expect(screen.getByTestId('script-preview').className).toContain('prompt-script__preview');
    expect(screen.getByRole('button', { name: '展开完整剧本原文' }).getAttribute('aria-expanded')).toBe('false');
  });

  it('expands the entire untruncated source in a keyboard-scrollable region and can collapse it', async () => {
    const user = userEvent.setup();
    render(<PromptScriptExcerpt detail={detail} />);

    await user.click(screen.getByRole('button', { name: '展开完整剧本原文' }));
    const region = screen.getByRole('region', { name: '完整剧本原文' });
    expect(region.getAttribute('tabindex')).toBe('0');
    expect(within(region).getByText(/全剧原文最后一句/)).toBeTruthy();
    expect(region.textContent).toBe(source);
    expect(screen.getByRole('button', { name: '收起完整剧本原文' }).getAttribute('aria-expanded')).toBe('true');

    await user.click(screen.getByRole('button', { name: '收起完整剧本原文' }));
    expect(screen.queryByRole('region', { name: '完整剧本原文' })).toBeNull();
  });
});
