// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { PlanMarkdown } from './PlanMarkdown';

afterEach(cleanup);

describe('PlanMarkdown', () => {
  it('renders headings, tables, lists, quotes and inline marks instead of raw symbols', () => {
    const { container } = render(<PlanMarkdown text={[
      '# 《冒牌皇帝》总导演定调方案',
      '**交付物**：导演宪法 / `高光地图`',
      '---',
      '## 一、输入来源',
      '| 来源 | 内容 |',
      '|---|---|',
      '| 项目任务书 | **剧名**《冒牌皇帝》 |',
      '- 单句不超过 15 个汉字',
      '- 禁止心理描写',
      '> 若假设被否，须重签。',
      '<script>alert(1)</script>',
    ].join('\n')} />);

    expect(screen.getByRole('heading', { level: 3 }).textContent).toBe('《冒牌皇帝》总导演定调方案');
    expect(screen.getByRole('heading', { level: 4 }).textContent).toBe('一、输入来源');
    const table = screen.getByRole('table');
    expect(within(table).getAllByRole('columnheader').map(cell => cell.textContent)).toEqual(['来源', '内容']);
    expect(within(table).getAllByRole('row')).toHaveLength(2);
    expect(within(table).getByText('剧名').tagName).toBe('STRONG');
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    expect(container.querySelector('blockquote')?.textContent).toBe('若假设被否，须重签。');
    expect(container.querySelector('hr')).toBeTruthy();
    expect(container.querySelector('code')?.textContent).toBe('高光地图');
    expect(container.textContent).not.toMatch(/\*\*|^#|\|---/);
    // Text is never interpreted as HTML.
    expect(container.querySelector('script')).toBeNull();
    expect(container.textContent).toContain('<script>alert(1)</script>');
  });
});
