import type { ReactNode } from 'react';

import './MarkdownDocument.css';
import { MARKDOWN_RENDER_BUDGETS, parseMarkdownBlocks, type MarkdownBlock } from './markdownParser';

export interface MarkdownDocumentProps {
  source: string;
  ariaLabel?: string;
  className?: string;
}

function cleanInline(value: string): string {
  return value.replace(/\*\*/g, '').replace(/`/g, '').trim();
}

function TextContent({ source }: { source: string }) {
  const lines = source.split('\n');
  const output: ReactNode[] = [];
  let listItems: string[] = [];

  const flushList = () => {
    if (!listItems.length) return;
    output.push(
      <ul key={`list-${output.length}`}>
        {listItems.map((item, index) => <li data-markdown-line key={`${item}-${index}`}>{cleanInline(item)}</li>)}
      </ul>,
    );
    listItems = [];
  };

  lines.forEach((line, index) => {
    const heading = line.trim().match(/^(#{1,6})\s+(.+)$/);
    const list = line.trim().match(/^[-*]\s+(.+)$/);
    if (list) {
      listItems.push(list[1]);
      return;
    }
    flushList();
    if (!line.trim()) {
      output.push(<span className="writer-markdown-document__space" data-markdown-line key={`space-${index}`} aria-hidden="true" />);
    } else if (heading) {
      output.push(<h3 data-markdown-line key={`heading-${index}`}>{cleanInline(heading[2])}</h3>);
    } else if (/^\s*---+\s*$/.test(line)) {
      output.push(<hr data-markdown-line key={`rule-${index}`} />);
    } else if (line.trim().startsWith('>')) {
      output.push(<blockquote data-markdown-line key={`quote-${index}`}>{cleanInline(line.trim().slice(1))}</blockquote>);
    } else {
      output.push(<p data-markdown-line key={`paragraph-${index}`}>{cleanInline(line)}</p>);
    }
  });
  flushList();
  return <>{output}</>;
}

export function MarkdownBlocks({ blocks }: { blocks: MarkdownBlock[] }) {
  const bounded = boundMarkdownBlocks(blocks);
  return <>{bounded.blocks.map((block, blockIndex) => {
    if (block.kind === 'text') {
      return <TextContent source={block.source} key={`text-${blockIndex}`} />;
    }
    return (
      <div
        className="writer-markdown-table-scroll"
        role="region"
        aria-label={`可横向滚动：${block.caption}`}
        tabIndex={0}
        key={`table-${block.caption}-${blockIndex}`}
      >
        <table aria-label={block.caption}>
          <caption>{block.caption}</caption>
          <thead>
            <tr>{block.headers.map((header, index) => <th scope="col" key={`${header}-${index}`}>{cleanInline(header) || `字段 ${index + 1}`}</th>)}</tr>
          </thead>
          <tbody>
            {block.rows.length > 0 ? block.rows.map((row, rowIndex) => (
              <tr key={`row-${rowIndex}`}>
                {row.map((cell, cellIndex) => <td key={`cell-${rowIndex}-${cellIndex}`}>{cleanInline(cell) || '—'}</td>)}
              </tr>
            )) : (
              <tr><td colSpan={block.headers.length}>暂无表格记录</td></tr>
            )}
          </tbody>
        </table>
        {(block.omittedRows || 0) > 0 && (
          <p className="writer-markdown-document__table-notice" role="status">
            为保持页面流畅，其余 {block.omittedRows?.toLocaleString('zh-CN')} 行已省略。
          </p>
        )}
      </div>
    );
  })}
  {bounded.truncated && (
    <p className="writer-markdown-document__limit-notice" role="status">
      为保持页面流畅，仅显示文档前段，剩余内容已省略。
      {bounded.omissionSummary ? `（${bounded.omissionSummary}）` : ''}
    </p>
  )}</>;
}

export function MarkdownDocument({ source, ariaLabel = 'Markdown 文档', className = '' }: MarkdownDocumentProps) {
  const blocks = parseMarkdownBlocks(source);
  return (
    <div className={`writer-markdown-document ${className}`.trim()} aria-label={ariaLabel}>
      {blocks.length > 0
        ? <MarkdownBlocks blocks={blocks} />
        : <p className="writer-markdown-document__empty">暂无可显示内容。</p>}
    </div>
  );
}

interface BoundedMarkdownBlocks {
  blocks: MarkdownBlock[];
  truncated: boolean;
  omissionSummary: string;
}

function boundMarkdownBlocks(blocks: MarkdownBlock[]): BoundedMarkdownBlocks {
  const visibleBlocks: MarkdownBlock[] = [];
  let remainingTextLines = MARKDOWN_RENDER_BUDGETS.maxTextLines;
  let remainingTableCells = MARKDOWN_RENDER_BUDGETS.maxTableCells;
  let remainingContentUnits = MARKDOWN_RENDER_BUDGETS.maxContentUnits;
  let omittedTextLines = 0;
  let omittedTableRows = 0;
  let omittedBlocks = 0;

  for (let blockIndex = 0; blockIndex < blocks.length; blockIndex += 1) {
    const block = blocks[blockIndex];
    if (visibleBlocks.length >= MARKDOWN_RENDER_BUDGETS.maxBlocks || remainingContentUnits <= 0) {
      omittedBlocks += blocks.length - blockIndex;
      break;
    }

    if (block.kind === 'text') {
      const lineLimit = Math.min(remainingTextLines, remainingContentUnits);
      const prefix = takeTextLinePrefix(block.source, lineLimit);
      if (prefix.renderedLines > 0) {
        visibleBlocks.push({ kind: 'text', source: prefix.source });
        remainingTextLines -= prefix.renderedLines;
        remainingContentUnits -= prefix.renderedLines;
      }
      omittedTextLines += prefix.omittedLines;
      if (prefix.omittedLines > 0) {
        omittedBlocks += blocks.length - blockIndex - 1;
        break;
      }
      continue;
    }

    const availableCells = Math.min(remainingTableCells, remainingContentUnits);
    if (block.headers.length > availableCells) {
      omittedBlocks += blocks.length - blockIndex;
      break;
    }

    let usedCells = block.headers.length;
    let visibleRowCount = 0;
    while (
      visibleRowCount < block.rows.length
      && usedCells + block.rows[visibleRowCount].length <= availableCells
    ) {
      usedCells += block.rows[visibleRowCount].length;
      visibleRowCount += 1;
    }
    const rowsOmittedByRender = block.rows.length - visibleRowCount;
    visibleBlocks.push({
      ...block,
      rows: block.rows.slice(0, visibleRowCount),
      omittedRows: (block.omittedRows || 0) + rowsOmittedByRender || undefined,
    });
    remainingTableCells -= usedCells;
    remainingContentUnits -= usedCells;
    omittedTableRows += rowsOmittedByRender;
    if (rowsOmittedByRender > 0) {
      omittedBlocks += blocks.length - blockIndex - 1;
      break;
    }
  }

  const summary = [
    omittedTextLines > 0 ? `${omittedTextLines.toLocaleString('zh-CN')} 行文本` : '',
    omittedTableRows > 0 ? `${omittedTableRows.toLocaleString('zh-CN')} 行表格` : '',
    omittedBlocks > 0 ? `${omittedBlocks.toLocaleString('zh-CN')} 个后续区块` : '',
  ].filter(Boolean).join('、');

  return {
    blocks: visibleBlocks,
    truncated: omittedTextLines > 0 || omittedTableRows > 0 || omittedBlocks > 0,
    omissionSummary: summary,
  };
}

function takeTextLinePrefix(source: string, maxLines: number): {
  source: string;
  renderedLines: number;
  omittedLines: number;
} {
  if (!source) return { source: '', renderedLines: 0, omittedLines: 0 };
  if (maxLines <= 0) {
    return { source: '', renderedLines: 0, omittedLines: countLines(source) };
  }

  let searchFrom = 0;
  for (let lineNumber = 1; lineNumber <= maxLines; lineNumber += 1) {
    const newline = source.indexOf('\n', searchFrom);
    if (newline === -1) {
      return { source, renderedLines: lineNumber, omittedLines: 0 };
    }
    if (lineNumber === maxLines) {
      const remainderStart = newline + 1;
      if (remainderStart >= source.length) {
        return { source: source.slice(0, newline), renderedLines: lineNumber, omittedLines: 0 };
      }
      return {
        source: source.slice(0, newline),
        renderedLines: lineNumber,
        omittedLines: countLines(source, remainderStart),
      };
    }
    searchFrom = newline + 1;
  }

  return { source, renderedLines: 1, omittedLines: 0 };
}

function countLines(source: string, start = 0): number {
  if (start >= source.length) return 0;
  let count = 1;
  let cursor = start;
  while (cursor < source.length) {
    const newline = source.indexOf('\n', cursor);
    if (newline === -1) break;
    count += 1;
    cursor = newline + 1;
  }
  return count;
}
