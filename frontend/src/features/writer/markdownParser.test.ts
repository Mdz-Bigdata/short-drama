import { describe, expect, it } from 'vitest';

import { MARKDOWN_PARSE_BUDGETS, paginateMarkdown, parseMarkdownBlocks } from './markdownParser';

describe('markdownParser resource bounds', () => {
  it('bounds adversarial table counts and rows while paging large tables', () => {
    const manyTables = Array.from(
      { length: 500 },
      (_, index) => `| 表${index} | 值 |\n|---|---|\n| ${index} | 内容 |`,
    ).join('\n');
    const tableBlocks = parseMarkdownBlocks(manyTables).filter(block => block.kind === 'table');
    expect(tableBlocks.length).toBeLessThanOrEqual(200);

    const hugeTable = [
      '| 编号 | 内容 |',
      '|---|---|',
      ...Array.from({ length: 6_000 }, (_, index) => `| ${index} | 场景内容 |`),
    ].join('\n');
    const parsed = parseMarkdownBlocks(hugeTable).filter(block => block.kind === 'table');
    expect(parsed.reduce((total, block) => total + block.rows.length, 0)).toBeLessThanOrEqual(5_001);

    const pages = paginateMarkdown(hugeTable);
    const largestRenderedTable = Math.max(
      ...pages.flatMap(page => page
        .filter(block => block.kind === 'table')
        .map(block => block.rows.length)),
    );
    expect(largestRenderedTable).toBeLessThanOrEqual(100);

    const manyRowTables = Array.from(
      { length: 5 },
      (_, tableIndex) => [
        `| 表 ${tableIndex} | 值 |`,
        '|---|---|',
        ...Array.from({ length: 100 }, (_, rowIndex) => `| ${rowIndex} | 内容 |`),
      ].join('\n'),
    ).join('\n\n');
    paginateMarkdown(manyRowTables).forEach(page => {
      const renderedRows = page.reduce(
        (total, block) => total + (block.kind === 'table' ? block.rows.length : 0),
        0,
      );
      expect(renderedRows).toBeLessThanOrEqual(100);
    });
  });

  it('caps adversarially wide tables before creating DOM-sized row arrays', () => {
    const header = Array.from({ length: 1_000 }, (_, index) => `字段${index}`);
    const divider = header.map(() => '---');
    const row = header.map((_, index) => `值${index}`);
    const source = [
      `|${header.join('|')}|`,
      `|${divider.join('|')}|`,
      `|${row.join('|')}|`,
    ].join('\n');

    const table = parseMarkdownBlocks(source).find(block => block.kind === 'table');
    expect(table?.kind).toBe('table');
    if (table?.kind === 'table') {
      expect(table.headers.length).toBeLessThanOrEqual(64);
      expect(table.rows.every(cells => cells.length <= 64)).toBe(true);
    }
  });

  it('caps total parsed table cells while retaining the existing row and column ceilings', () => {
    const headers = Array.from({ length: 64 }, (_, index) => `字段${index}`);
    const source = [
      `|${headers.join('|')}|`,
      `|${headers.map(() => '---').join('|')}|`,
      ...Array.from(
        { length: 5_000 },
        (_, rowIndex) => `|${headers.map((_, cellIndex) => `${rowIndex}-${cellIndex}`).join('|')}|`,
      ),
    ].join('\n');

    const tables = parseMarkdownBlocks(source).filter(block => block.kind === 'table');
    const parsedCells = tables.reduce(
      (total, table) => total + table.rows.reduce((rowTotal, row) => rowTotal + row.length, 0),
      0,
    );
    expect(parsedCells).toBeLessThanOrEqual(MARKDOWN_PARSE_BUDGETS.maxTotalTableCells);
    expect(tables.some(table => (table.omittedRows || 0) > 0)).toBe(true);

    paginateMarkdown(source).forEach(page => {
      const pageCells = page.reduce(
        (total, block) => total + (block.kind === 'table'
          ? block.headers.length + block.rows.reduce((sum, row) => sum + row.length, 0)
          : 0),
        0,
      );
      expect(pageCells).toBeLessThanOrEqual(MARKDOWN_PARSE_BUDGETS.maxTableCellsPerPage);
    });
  });

  it('chunks line-dense text during parsing without losing pagination content', () => {
    const source = Array.from({ length: 20_000 }, (_, index) => `x${index}`).join('\n');
    const blocks = parseMarkdownBlocks(source);

    expect(blocks.length).toBeGreaterThan(1);
    blocks.filter(block => block.kind === 'text').forEach(block => {
      expect(block.source.split('\n').length)
        .toBeLessThanOrEqual(MARKDOWN_PARSE_BUDGETS.maxTextLinesPerBlock);
    });

    const pagedText = paginateMarkdown(source)
      .flat()
      .filter(block => block.kind === 'text')
      .map(block => block.source)
      .join('\n');
    expect(pagedText).toContain('x0');
    expect(pagedText).toContain('x19999');
  });
});
