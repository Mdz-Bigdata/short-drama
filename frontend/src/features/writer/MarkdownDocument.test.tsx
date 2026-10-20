// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { MarkdownDocument } from './MarkdownDocument';
import { MARKDOWN_RENDER_BUDGETS } from './markdownParser';

describe('MarkdownDocument resource bounds', () => {
  afterEach(cleanup);

  it('renders only a bounded prefix of an extremely line-dense document', () => {
    const source = Array.from({ length: 20_000 }, (_, index) => `原文行 ${index + 1}`).join('\n');

    render(<MarkdownDocument source={source} ariaLabel="超长角色原文" />);

    const document = screen.getByLabelText('超长角色原文');
    expect(document.querySelectorAll('[data-markdown-line]').length)
      .toBeLessThanOrEqual(MARKDOWN_RENDER_BUDGETS.maxTextLines);
    expect(document.querySelectorAll('*').length)
      .toBeLessThanOrEqual(MARKDOWN_RENDER_BUDGETS.maxDomNodes);
    expect(document.textContent).toContain('原文行 1');
    expect(document.textContent).not.toContain('原文行 20000');
    expect(screen.getByRole('status').textContent).toContain('剩余内容已省略');
  });

  it('caps rendered table cells and exposes a visible omission notice', () => {
    const headers = Array.from({ length: 64 }, (_, index) => `字段 ${index + 1}`);
    const source = [
      `| ${headers.join(' | ')} |`,
      `| ${headers.map(() => '---').join(' | ')} |`,
      ...Array.from(
        { length: 2_000 },
        (_, rowIndex) => `| ${headers.map((_, cellIndex) => `${rowIndex + 1}-${cellIndex + 1}`).join(' | ')} |`,
      ),
    ].join('\n');

    render(<MarkdownDocument source={source} ariaLabel="高密度角色表" />);

    const document = screen.getByLabelText('高密度角色表');
    expect(document.querySelectorAll('th, td').length)
      .toBeLessThanOrEqual(MARKDOWN_RENDER_BUDGETS.maxTableCells);
    expect(document.querySelectorAll('*').length)
      .toBeLessThanOrEqual(MARKDOWN_RENDER_BUDGETS.maxDomNodes);
    expect(document.textContent).toContain('其余');
    expect(document.textContent).toContain('行已省略');
  });
});
