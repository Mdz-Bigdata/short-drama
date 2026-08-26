import type { ReactNode } from 'react';

import { parseMarkdownTable, type ParsedMarkdownTable } from './parseMarkdownTable';
import { promptLabel } from './promptLabels';
import type { PromptValue } from './storyboardPromptTypes';

function PromptMarkdownTable({ table, label }: { table: ParsedMarkdownTable; label: string }) {
  return (
    <div className="prompt-detail__table-wrap">
      <table className="prompt-detail__table" aria-label={label}>
        {table.caption && <caption>{table.caption}</caption>}
        <thead>
          <tr>{table.headers.map((header, index) => <th key={`${index}-${header}`} scope="col">{header}</th>)}</tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>{row.map((cell, columnIndex) => <td key={`${columnIndex}-${cell}`}>{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function displayValue(value: PromptValue, label: string): ReactNode {
  if (value === null || value === undefined || value === '') return '未注明';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (Array.isArray(value)) {
    if (value.length === 0) return '无';
    if (value.every(item => typeof item !== 'object')) return value.join('、');
    return <div className="prompt-detail__nested-list">{value.map((item, index) => <PromptFields key={index} value={item as Record<string, PromptValue>} />)}</div>;
  }
  if (typeof value === 'object') return <PromptFields value={value} />;
  if (typeof value === 'string') {
    const table = parseMarkdownTable(value);
    if (table) return <PromptMarkdownTable table={table} label={label} />;
  }
  return String(value);
}

export function PromptFields({ value, omit = [] }: { value?: Record<string, PromptValue>; omit?: string[] }) {
  if (!value) return <p className="prompt-detail__muted">未生成该部分信息。</p>;
  return (
    <dl className="prompt-detail__fields">
      {Object.entries(value).filter(([key]) => !omit.includes(key)).map(([key, field]) => {
        const label = promptLabel(key);
        return (
          <div className="prompt-detail__field" key={key}>
            <dt>{label}</dt>
            <dd>{displayValue(field, label)}</dd>
          </div>
        );
      })}
    </dl>
  );
}

export function PromptSection({ title, icon, meta, children }: { title: string; icon?: ReactNode; meta?: ReactNode; children: ReactNode }) {
  return (
    <section className="prompt-detail__section" aria-labelledby={`prompt-section-${title}`}>
      <header className="prompt-detail__section-header">
        <h2 id={`prompt-section-${title}`}>{icon}{title}</h2>
        {meta && <span>{meta}</span>}
      </header>
      <div className="prompt-detail__section-body">{children}</div>
    </section>
  );
}
