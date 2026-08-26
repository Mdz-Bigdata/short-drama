import type { ReactNode } from 'react';

import './MarkdownDocument.css';
import { parseMarkdownBlocks, type MarkdownBlock } from './markdownParser';

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
        {listItems.map((item, index) => <li key={`${item}-${index}`}>{cleanInline(item)}</li>)}
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
      output.push(<span className="writer-markdown-document__space" key={`space-${index}`} aria-hidden="true" />);
    } else if (heading) {
      output.push(<h3 key={`heading-${index}`}>{cleanInline(heading[2])}</h3>);
    } else if (/^\s*---+\s*$/.test(line)) {
      output.push(<hr key={`rule-${index}`} />);
    } else if (line.trim().startsWith('>')) {
      output.push(<blockquote key={`quote-${index}`}>{cleanInline(line.trim().slice(1))}</blockquote>);
    } else {
      output.push(<p key={`paragraph-${index}`}>{cleanInline(line)}</p>);
    }
  });
  flushList();
  return <>{output}</>;
}

export function MarkdownBlocks({ blocks }: { blocks: MarkdownBlock[] }) {
  return blocks.map((block, blockIndex) => {
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
      </div>
    );
  });
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
