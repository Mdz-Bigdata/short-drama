import type { CSSProperties } from 'react';
import { t } from '../../i18n';
import './ScriptStructurePicker.css';

/**
 * 剧本结构：点一种，总导演按它搭整部大纲，分集规划按它把集数分到各段(backend app/data/prompt/script_structure.json)。
 * 再点一次取消，空值由总导演自己定。代码值与后端一致，不要改。
 */
const SCRIPT_STRUCTURES: { id: string; label: string; hint: string }[] = [
  { id: 'three_act', label: '三幕式', hint: '建置—对抗—结局，按 1:2:1 分篇幅，中点有一次反转' },
  { id: 'five_act', label: '五幕式', hint: '开端—发展—高潮—回落—结局，高潮放在正中，之后写代价' },
  { id: 'hero_journey', label: '英雄旅程', hint: '平凡世界—召唤—跨越门槛—考验—磨难—奖赏—回归' },
  { id: 'seven_point', label: '七点式', hint: '钩子—第一转折—升级—中点反转—最大危机—揭露—留钩，短剧常用' },
  { id: 'fichtean', label: '费希特曲线', hint: '一开场就在危机里，危机一个比一个大直到高潮，背景边跑边交代' },
  { id: 'parallel', label: '平行结构', hint: '两三条故事线各走各的，主题互相映照，最后汇合' },
  { id: 'intercut', label: '交叉结构', hint: '两条线在同一集里交替推进，因果咬合，最终相撞' },
  { id: 'nonlinear', label: '非线性结构', hint: '打乱时间顺序讲：倒叙、插叙、闪回，真相逐步拼出' },
  { id: 'circular', label: '环形结构', hint: '结尾回到开头的画面或处境，意义却已经变了' },
  { id: 'episodic', label: '单元结构', hint: '每一两集一个独立事件，开头立题、结尾解决，主线贯穿' },
];

export function ScriptStructurePicker({ value, onChange }: { value: string; onChange: (next: string) => void }) {
  const chosen = SCRIPT_STRUCTURES.find(item => item.id === value);
  return (
    <div className="structure-picker">
      <div className="structure-picker__head">
        <span id="new-project-structure-label" className="structure-picker__title">{t('剧本结构')}</span>
        <span className="structure-picker__note">{chosen ? t(chosen.hint) : t('不选由总导演定')}</span>
      </div>
      <div className="structure-picker__chips" role="radiogroup" aria-labelledby="new-project-structure-label">
        {SCRIPT_STRUCTURES.map(item => (
          <button
            key={item.id}
            type="button"
            role="radio"
            aria-checked={value === item.id}
            className={`structure-picker__chip${value === item.id ? ' is-active' : ''}`}
            title={t(item.hint)}
            onClick={() => onChange(value === item.id ? '' : item.id)}
          >
            {t(item.label)}
          </button>
        ))}
      </div>
    </div>
  );
}

/** 集数：滑块拖到大概，右边的数字框改精确值；电影短片固定 1 集。 */
export function EpisodeCountSlider({ value, min, max, disabled, onChange }: {
  value: number; min: number; max: number; disabled?: boolean; onChange: (next: number) => void;
}) {
  const clamp = (raw: number) => Math.min(max, Math.max(min, Math.round(Number.isFinite(raw) ? raw : min)));
  const shown = disabled ? 1 : value;
  const percent = max > min ? ((shown - min) / (max - min)) * 100 : 0;
  return (
    <div className="episode-slider">
      <label htmlFor="new-project-episode-slider" className="structure-picker__title">{t('集数')}</label>
      <div className="episode-slider__row">
        <input
          id="new-project-episode-slider"
          type="range"
          min={min}
          max={max}
          step={1}
          value={shown}
          disabled={disabled}
          aria-valuetext={t('{0} 集', [shown])}
          style={{ '--episode-fill': `${percent}%` } as CSSProperties}
          onChange={event => onChange(clamp(Number(event.target.value)))}
        />
        <label className="episode-slider__value">
          <input
            type="number"
            min={min}
            max={max}
            value={shown}
            disabled={disabled}
            aria-label={t('集数')}
            onChange={event => onChange(clamp(Number(event.target.value)))}
          />
          <span>{t('集')}</span>
        </label>
      </div>
      {disabled && <p className="structure-picker__note">{t('电影短片只有 1 集')}</p>}
    </div>
  );
}
