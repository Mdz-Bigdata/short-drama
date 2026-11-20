import { useMemo, useState, type CSSProperties } from 'react';
import { t } from '../../i18n';
import type { SculptControl } from './faceSculptModel';

/**
 * 造型编辑器右栏的一个控件：选项是一排胶囊(带色块的画成色块，带分组的先选分组)，
 * 刻度(-2..2)是从中间往两边拉的滑块，档位(0..n)是从左往右拉的滑块，只有两档的画成开关。
 */
export function StudioControl({ control, value, onChange }: {
  control: SculptControl;
  value: string | number;
  onChange: (next: string | number) => void;
}) {
  if (control.type === 'choice') return <ChoiceControl control={control} value={String(value || '')} onChange={onChange} />;
  if (control.type === 'level' && (control.steps?.length || 0) === 2) {
    const on = Number(value || 0) === 1;
    return (
      <div className="studio-control studio-control--toggle">
        <span className="studio-control__label" title={control.steps?.[1]}>{control.label}</span>
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-label={control.label}
          className={`studio-switch${on ? ' is-on' : ''}`}
          onClick={() => onChange(on ? 0 : 1)}
        >
          <span />
        </button>
      </div>
    );
  }
  return <SliderControl control={control} value={Number(value || 0)} onChange={onChange} />;
}

function SliderControl({ control, value, onChange }: { control: SculptControl; value: number; onChange: (next: number) => void }) {
  const steps = control.steps || [];
  const bipolar = control.type === 'scale';
  const min = bipolar ? -2 : 0;
  const max = bipolar ? 2 : Math.max(1, steps.length - 1);
  const phrase = bipolar ? steps[value + 2] : steps[value];
  // 中间(刻度 0)不加任何描述：从中间往当前值涂色；档位从左边涂起。
  const at = (number: number) => ((number - min) / (max - min)) * 100;
  const from = bipolar ? Math.min(at(0), at(value)) : 0;
  const to = bipolar ? Math.max(at(0), at(value)) : at(value);
  const id = `studio-${control.key}`;
  return (
    <div className="studio-control">
      <div className="studio-control__head">
        <label className="studio-control__label" htmlFor={id}>{control.label}</label>
        <span className="studio-control__value">{bipolar && value > 0 ? `+${value}` : value}</span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={1}
        value={value}
        aria-valuetext={phrase || (bipolar ? t('沿用原描述') : t('不加'))}
        className={`studio-slider${bipolar ? ' is-bipolar' : ''}`}
        style={{ '--fill-from': `${from}%`, '--fill-to': `${to}%` } as CSSProperties}
        onChange={event => onChange(Number(event.target.value))}
      />
      <p className="studio-control__phrase">{phrase || (bipolar ? t('沿用原描述') : t('不加'))}</p>
    </div>
  );
}

function ChoiceControl({ control, value, onChange }: { control: SculptControl; value: string; onChange: (next: string) => void }) {
  const options = useMemo(() => control.options || [], [control.options]);
  const groups = useMemo(() => [...new Set(options.map(option => option.group).filter(Boolean))] as string[], [options]);
  const chosenGroup = options.find(option => option.value === value)?.group;
  const [group, setGroup] = useState(chosenGroup || groups[0] || '');
  const shownGroup = groups.length ? (groups.includes(group) ? group : groups[0]) : '';
  const shown = shownGroup ? options.filter(option => option.group === shownGroup) : options;
  const swatches = options.some(option => option.swatch);
  return (
    <div className="studio-control" role="group" aria-label={control.label}>
      <div className="studio-control__head">
        <span className="studio-control__label">{control.label}</span>
        {value && (
          <button type="button" className="studio-control__clear" onClick={() => onChange('')}>
            {t('沿用原描述')}
          </button>
        )}
      </div>
      {groups.length > 1 && (
        <div className="studio-groups" role="tablist" aria-label={t('{0}分类', [control.label])}>
          {groups.map(item => (
            <button
              key={item}
              type="button"
              role="tab"
              aria-selected={item === shownGroup}
              className={item === shownGroup ? 'is-active' : ''}
              onClick={() => setGroup(item)}
            >
              {item}
            </button>
          ))}
        </div>
      )}
      <div className={swatches ? 'studio-swatches' : 'studio-chips'}>
        {shown.map(option => (
          <button
            key={option.value}
            type="button"
            aria-pressed={value === option.value}
            className={value === option.value ? 'is-active' : ''}
            title={option.label}
            aria-label={swatches ? `${control.label}：${option.label}` : undefined}
            onClick={() => onChange(value === option.value ? '' : option.value)}
          >
            {swatches ? <span className="studio-swatch" style={{ background: option.swatch }} /> : option.label}
            {swatches && <span className="studio-swatch__label">{option.label}</span>}
          </button>
        ))}
      </div>
    </div>
  );
}
