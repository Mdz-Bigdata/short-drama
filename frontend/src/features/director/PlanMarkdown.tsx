import { Fragment, type ReactNode } from 'react';

/**
 * The director's plan as a document rather than raw Markdown: headings, tables, lists, quotes and rules,
 * with **bold** and `code` inline. Only this subset is understood, and everything is built as React
 * elements — the text is never injected as HTML.
 */

function inline(text: string, key: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const pattern = /\*\*([^*]+)\*\*|`([^`]+)`/g;
  let last = 0;
  let index = 0;
  for (let match = pattern.exec(text); match; match = pattern.exec(text)) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    parts.push(match[1] !== undefined
      ? <strong key={`${key}-b${index}`}>{match[1]}</strong>
      : <code key={`${key}-c${index}`}>{match[2]}</code>);
    last = pattern.lastIndex;
    index += 1;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function cells(line: string): string[] {
  return line.trim().replace(/^\||\|$/g, '').split('|').map(cell => cell.trim());
}

const isRule = (line: string) => /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line);
const isTableDivider = (line: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);

export function PlanMarkdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const key = `b${i}`;
    if (!line.trim()) { i += 1; continue; }
    if (isRule(line)) { blocks.push(<hr key={key} />); i += 1; continue; }
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      const level = Math.min(heading[1].length + 2, 6);
      const Tag = `h${level}` as 'h3' | 'h4' | 'h5' | 'h6';
      blocks.push(<Tag key={key}>{inline(heading[2], key)}</Tag>);
      i += 1;
      continue;
    }
    if (line.trim().startsWith('|')) {
      const rows: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) { rows.push(lines[i]); i += 1; }
      const [head, ...rest] = rows;
      const body = rest.filter(row => !isTableDivider(row));
      blocks.push(
        <div className="plan-table" key={key}>
          <table>
            <thead><tr>{cells(head).map((cell, c) => <th key={c}>{inline(cell, `${key}h${c}`)}</th>)}</tr></thead>
            <tbody>{body.map((row, r) => (
              <tr key={r}>{cells(row).map((cell, c) => <td key={c}>{inline(cell, `${key}r${r}c${c}`)}</td>)}</tr>
            ))}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (/^\s*>/.test(line)) {
      const quoted: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) { quoted.push(lines[i].replace(/^\s*>\s?/, '')); i += 1; }
      blocks.push(<blockquote key={key}>{inline(quoted.join(' '), key)}</blockquote>);
      continue;
    }
    if (/^\s*(?:[-*•]|\d+[.)、])\s+/.test(line)) {
      const ordered = /^\s*\d/.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*(?:[-*•]|\d+[.)、])\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*(?:[-*•]|\d+[.)、])\s+/, ''));
        i += 1;
      }
      const List = ordered ? 'ol' : 'ul';
      blocks.push(<List key={key}>{items.map((item, n) => <li key={n}>{inline(item, `${key}l${n}`)}</li>)}</List>);
      continue;
    }
    const paragraph: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*\||\s*>|\s*(?:[-*•]|\d+[.)、])\s)/.test(lines[i]) && !isRule(lines[i])) {
      paragraph.push(lines[i].trim());
      i += 1;
    }
    blocks.push(<p key={key}>{paragraph.map((part, n) => <Fragment key={n}>{n > 0 && <br />}{inline(part, `${key}p${n}`)}</Fragment>)}</p>);
  }
  return <div className="plan-markdown">{blocks}</div>;
}
