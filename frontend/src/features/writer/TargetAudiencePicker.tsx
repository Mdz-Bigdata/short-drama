import { t } from '../../i18n';
import type { AudienceAge, AudienceLean, TargetAudience } from '../../types';

/** Codes are the backend's (app/data/prompt/target_audience.json); an empty value leaves the choice to the director. */
const LEANS: { id: AudienceLean; label: string }[] = [
  { id: '', label: '不限（总导演定）' },
  { id: 'male', label: '男频' },
  { id: 'female', label: '女频' },
];

const AGES: { id: AudienceAge; label: string }[] = [
  { id: '', label: '不限' },
  { id: 'youth', label: '青年' },
  { id: 'adult', label: '青中年' },
  { id: 'senior', label: '中老年' },
];

const selectStyle = { width: '100%', padding: '10px', background: 'var(--surface)', border: '1px solid var(--border-color)', borderRadius: '8px', color: 'var(--ink)', fontSize: '0.85rem' } as const;
const labelStyle = { display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' } as const;

/**
 * Who a serial is written for. The episode planner writes the first three episodes to this audience's taste
 * (男频: a hook in the very first scene and a sense of gain; 女频: the core conflict inside episode 1 and a
 * relationship worth following). Only serials use it, so the form hides it for a short film or an advert.
 */
export function TargetAudiencePicker({ value, onChange }: { value: TargetAudience; onChange: (next: TargetAudience) => void }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
      <div>
        <label htmlFor="new-project-audience-lean" style={labelStyle}>{t('目标用户')}</label>
        <select
          id="new-project-audience-lean"
          value={value.lean}
          onChange={e => onChange({ ...value, lean: e.target.value as AudienceLean })}
          title={t('男频：第一场戏就有吸睛点，前 3 集给获得感；女频：第 1 集立住核心冲突，前 3 集建立关系感')}
          style={selectStyle}
        >
          {LEANS.map(option => <option key={option.id} value={option.id}>{t(option.label)}</option>)}
        </select>
      </div>
      <div>
        <label htmlFor="new-project-audience-age" style={labelStyle}>{t('年龄段')}</label>
        <select
          id="new-project-audience-age"
          value={value.age}
          onChange={e => onChange({ ...value, age: e.target.value as AudienceAge })}
          style={selectStyle}
        >
          {AGES.map(option => <option key={option.id} value={option.id}>{t(option.label)}</option>)}
        </select>
      </div>
    </div>
  );
}
