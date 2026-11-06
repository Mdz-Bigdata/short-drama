import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react';
import { useState, type ReactNode } from 'react';

import { t } from '../../i18n';
import type { CompareOp, Comparison, Condition, Scalar, StoryEffect, StoryVariable } from './storyTypes';

/** A number box that lets "-" and "1." exist while typing; only a parseable value leaves it. */
export function NumberField({ value, onChange, allowEmpty = false, label, min, max, className }: {
  value: number | null;
  onChange: (value: number | null) => void;
  allowEmpty?: boolean;
  label: string;
  min?: number;
  max?: number;
  className?: string;
}) {
  const [text, setText] = useState(value === null ? '' : String(value));
  const [seen, setSeen] = useState(value);
  if (value !== seen) {
    setSeen(value);
    setText(value === null ? '' : String(value));
  }
  return (
    <input
      type="number"
      className={className}
      aria-label={label}
      step="any"
      min={min}
      max={max}
      value={text}
      onChange={event => {
        const raw = event.target.value;
        setText(raw);
        if (raw.trim() === '') {
          if (allowEmpty) {
            setSeen(null);
            onChange(null);
          }
          return;
        }
        const parsed = Number(raw);
        if (Number.isFinite(parsed)) {
          setSeen(parsed);
          onChange(parsed);
        }
      }}
    />
  );
}

export function RowTools({ onUp, onDown, onDelete, deleteLabel }: { onUp?: () => void; onDown?: () => void; onDelete: () => void; deleteLabel: string }) {
  return (
    <span className="istory-row-tools">
      {onUp && <button type="button" aria-label={t('上移')} onClick={onUp}><ArrowUp aria-hidden="true" /></button>}
      {onDown && <button type="button" aria-label={t('下移')} onClick={onDown}><ArrowDown aria-hidden="true" /></button>}
      <button type="button" aria-label={deleteLabel} onClick={onDelete}><Trash2 aria-hidden="true" /></button>
    </span>
  );
}

function ValueInput({ variable, value, onChange, label }: { variable: StoryVariable | undefined; value: Scalar; onChange: (value: Scalar) => void; label: string }) {
  if (variable?.kind === 'flag') {
    return (
      <select aria-label={label} value={String(value === true)} onChange={event => onChange(event.target.value === 'true')}>
        <option value="true">{t('是')}</option>
        <option value="false">{t('否')}</option>
      </select>
    );
  }
  return <NumberField label={label} value={typeof value === 'number' ? value : 0} onChange={next => onChange(next ?? 0)} />;
}

const NUMBER_OPS: Array<[CompareOp, string]> = [['gte', '≥'], ['gt', '>'], ['lte', '≤'], ['lt', '<'], ['eq', '='], ['ne', '≠']];
const FLAG_OPS: Array<[CompareOp, string]> = [['eq', '='], ['ne', '≠']];

function isGroup(condition: Condition): condition is { all: Condition[] } | { any: Condition[] } {
  return 'all' in condition || 'any' in condition;
}

function ComparisonRow({ value, variables, onChange, onDelete }: { value: Comparison; variables: readonly StoryVariable[]; onChange: (next: Comparison) => void; onDelete: () => void }) {
  const variable = variables.find(item => item.id === value.var);
  const ops = variable?.kind === 'flag' ? FLAG_OPS : NUMBER_OPS;
  return (
    <div className="istory-inline">
      <select
        aria-label={t('变量')}
        value={value.var}
        onChange={event => {
          const next = variables.find(item => item.id === event.target.value);
          onChange(next?.kind === 'flag'
            ? { var: event.target.value, op: 'eq', value: true }
            : { var: event.target.value, op: 'gte', value: typeof value.value === 'number' ? value.value : 0 });
        }}
      >
        {!variable && <option value={value.var}>{value.var}（{t('已删除')}）</option>}
        {variables.map(item => <option key={item.id} value={item.id}>{item.label || item.id}</option>)}
      </select>
      <select aria-label={t('比较方式')} value={value.op} onChange={event => onChange({ ...value, op: event.target.value as CompareOp })}>
        {ops.map(([op, sign]) => <option key={op} value={op}>{sign}</option>)}
      </select>
      <ValueInput variable={variable} value={value.value} label={t('比较值')} onChange={next => onChange({ ...value, value: next })} />
      <RowTools onDelete={onDelete} deleteLabel={t('删除这条条件')} />
    </div>
  );
}

function defaultComparison(variables: readonly StoryVariable[]): Comparison {
  const first = variables[0];
  return first?.kind === 'flag' ? { var: first.id, op: 'eq', value: true } : { var: first?.id ?? '', op: 'gte', value: 1 };
}

/** Rows joined by 全部 / 任一, with groups inside groups: the expression model as a form, never as text to parse. */
export function ConditionEditor({ value, variables, onChange, depth = 1 }: {
  value: Condition | null;
  variables: readonly StoryVariable[];
  onChange: (next: Condition | null) => void;
  depth?: number;
}) {
  if (!variables.length && !value) return <p className="istory-hint">{t('先在左侧添加变量，才能设置条件。')}</p>;
  const mode: 'all' | 'any' = value && 'any' in value ? 'any' : 'all';
  const items: Condition[] = !value ? [] : isGroup(value) ? ('all' in value ? value.all : value.any) : [value];
  const emit = (nextMode: 'all' | 'any', nextItems: Condition[]) => {
    if (!nextItems.length) onChange(null);
    else onChange(nextMode === 'all' ? { all: nextItems } : { any: nextItems });
  };
  const replace = (index: number, next: Condition | null) => {
    const copy = [...items];
    if (next) copy[index] = next;
    else copy.splice(index, 1);
    emit(mode, copy);
  };
  return (
    <div className={`istory-condition ${depth > 1 ? 'is-nested' : ''}`}>
      {items.length > 1 && (
        <label className="istory-inline">
          <span>{t('需要满足')}</span>
          <select aria-label={t('条件组合方式')} value={mode} onChange={event => emit(event.target.value as 'all' | 'any', items)}>
            <option value="all">{t('全部')}</option>
            <option value="any">{t('任一')}</option>
          </select>
        </label>
      )}
      {items.map((item, index) => (isGroup(item)
        ? <ConditionEditor key={index} value={item} variables={variables} depth={depth + 1} onChange={next => replace(index, next)} />
        : <ComparisonRow key={index} value={item} variables={variables} onChange={next => replace(index, next)} onDelete={() => replace(index, null)} />
      ))}
      <div className="istory-inline">
        <button type="button" className="istory-link" disabled={!variables.length} onClick={() => emit(mode, [...items, defaultComparison(variables)])}>
          <Plus aria-hidden="true" /> {t('添加条件')}
        </button>
        {depth < 3 && items.length > 0 && (
          <button type="button" className="istory-link" disabled={!variables.length} onClick={() => emit(mode, [...items, { any: [defaultComparison(variables)] }])}>
            <Plus aria-hidden="true" /> {t('添加一组')}
          </button>
        )}
      </div>
    </div>
  );
}

export function EffectsEditor({ value, variables, onChange }: { value: readonly StoryEffect[]; variables: readonly StoryVariable[]; onChange: (next: StoryEffect[]) => void }) {
  const update = (index: number, next: StoryEffect) => onChange(value.map((item, at) => (at === index ? next : item)));
  return (
    <div className="istory-effects">
      {value.map((effect, index) => {
        const variable = variables.find(item => item.id === effect.var);
        return (
          <div className="istory-inline" key={index}>
            <select
              aria-label={t('变量')}
              value={effect.var}
              onChange={event => {
                const next = variables.find(item => item.id === event.target.value);
                update(index, next?.kind === 'flag' ? { var: event.target.value, op: 'set', value: true } : { var: event.target.value, op: 'add', value: 1 });
              }}
            >
              {!variable && <option value={effect.var}>{effect.var}（{t('已删除')}）</option>}
              {variables.map(item => <option key={item.id} value={item.id}>{item.label || item.id}</option>)}
            </select>
            <select
              aria-label={t('效果方式')}
              value={effect.op}
              onChange={event => update(index, { ...effect, op: event.target.value as StoryEffect['op'] })}
            >
              {variable?.kind !== 'flag' && <option value="add">+=</option>}
              <option value="set">=</option>
            </select>
            <ValueInput variable={variable} value={effect.value} label={t('效果值')} onChange={next => update(index, { ...effect, value: next })} />
            <RowTools onDelete={() => onChange(value.filter((_, at) => at !== index))} deleteLabel={t('删除这条效果')} />
          </div>
        );
      })}
      <button
        type="button"
        className="istory-link"
        disabled={!variables.length}
        onClick={() => {
          const first = variables[0];
          onChange([...value, first.kind === 'flag' ? { var: first.id, op: 'set', value: true } : { var: first.id, op: 'add', value: 1 }]);
        }}
      >
        <Plus aria-hidden="true" /> {t('添加效果')}
      </button>
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="istory-field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
