import { X } from 'lucide-react';
import { useState } from 'react';
import { t } from '../../i18n';
import type { MarkKind, MarkRegion, SculptCatalog, SculptMark } from './faceSculptModel';

/**
 * 脸部与身体特征：先点一种(痣、疤、雀斑、纹身…)，再在示意图上点它长在哪。
 * 示意图是面对角色看的，所以角色自己的左边在画面右侧；部位名都按角色自己的左右说。
 * 全脸雀斑这类不用点部位，点一下就加上；纹身和自定义要先写是什么。
 */
export function StudioMarks({ catalog, marks, area, onAreaChange, onChange }: {
  catalog: NonNullable<SculptCatalog['marks']>;
  marks: SculptMark[];
  area: 'face' | 'body';
  onAreaChange: (area: 'face' | 'body') => void;
  onChange: (marks: SculptMark[]) => void;
}) {
  const [kindKey, setKindKey] = useState('');
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const kind = catalog.kinds.find(item => item.key === kindKey);
  const label = (mark: SculptMark) => {
    const found = catalog.kinds.find(item => item.key === mark.kind);
    const region = catalog.regions.find(item => item.key === mark.region);
    return [region?.label, found?.label, mark.text].filter(Boolean).join(' · ');
  };
  const full = marks.length >= catalog.limit;

  const add = (mark: SculptMark) => {
    setError('');
    if (marks.some(item => item.kind === mark.kind && item.region === mark.region && item.text === mark.text)) return;
    if (full) { setError(t('特征最多 {0} 处', [catalog.limit])); return; }
    onChange([...marks, mark]);
  };
  const pickKind = (item: MarkKind) => {
    setError('');
    if (!item.region && !item.text) { add({ kind: item.key, region: '', text: '' }); setKindKey(''); return; }
    setKindKey(kindKey === item.key ? '' : item.key);
  };
  const place = (region: MarkRegion) => {
    if (!kind) { setError(t('先在上面选一种特征')); return; }
    if (kind.text && !text.trim()) { setError(t('先写上「{0}」是什么', [kind.label])); return; }
    add({ kind: kind.key, region: region.key, text: kind.text ? text.trim() : '' });
  };
  const regions = catalog.regions.filter(region => region.area === area);

  return (
    <div className="studio-marks">
      <h3 className="studio-section-title">{t('纹身 & 疤痕')}</h3>
      <div className="studio-mark-kinds">
        {catalog.kinds.map(item => (
          <button
            key={item.key}
            type="button"
            aria-pressed={kindKey === item.key}
            className={kindKey === item.key ? 'is-active' : ''}
            onClick={() => pickKind(item)}
          >
            <span className="studio-mark-kinds__swatch" style={{ background: item.swatch || 'var(--border-color)' }} />
            <span>{item.label}</span>
          </button>
        ))}
      </div>
      {kind?.text && (
        <input
          className="studio-text"
          value={text}
          maxLength={catalog.text_chars}
          aria-label={t('{0}是什么', [kind.label])}
          placeholder={kind.key === 'tattoo' ? t('如：一条青龙、梵文小字') : t('如：一道烫伤的旧痕')}
          onChange={event => setText(event.target.value)}
        />
      )}
      <p className="studio-hint">
        {kind
          ? t('在下面的示意图上点「{0}」长在哪；左右以角色自己为准。', [kind.label])
          : t('选一种特征，再点它在脸上或身上的位置。')}
      </p>
      <div className="studio-area" role="tablist" aria-label={t('示意图')}>
        {(['face', 'body'] as const).map(item => (
          <button key={item} type="button" role="tab" aria-selected={area === item} className={area === item ? 'is-active' : ''} onClick={() => onAreaChange(item)}>
            {item === 'face' ? t('脸部') : t('身体')}
          </button>
        ))}
      </div>
      <svg className="studio-map" viewBox="0 0 100 100" role="group" aria-label={area === 'face' ? t('脸部示意图') : t('身体示意图')}>
        {area === 'face' ? (
          <g className="studio-map__outline">
            <ellipse cx="50" cy="52" rx="30" ry="40" />
            <path d="M33 33 q7 -4 13 0 M54 33 q7 -4 13 0" />
            <path d="M36 43 q5 3 10 0 M54 43 q5 3 10 0" />
            <path d="M50 42 v14 q-3 3 0 4" />
            <path d="M41 70 q9 5 18 0" />
          </g>
        ) : (
          <g className="studio-map__outline">
            <circle cx="50" cy="8" r="6" />
            <path d="M44 14 h12 l14 8 l8 30 M44 14 l-14 8 l-8 30 M36 22 v28 h28 v-28 M40 50 l-2 46 M60 50 l2 46 M50 50 v40" />
          </g>
        )}
        {regions.map(region => {
          const placed = marks.filter(mark => mark.region === region.key);
          return (
            <g key={region.key}>
              <circle
                role="button"
                tabIndex={0}
                aria-label={t('放在{0}', [region.label])}
                className={`studio-map__spot${placed.length ? ' is-placed' : ''}`}
                cx={region.x * 100}
                cy={region.y * 100}
                r={placed.length ? 3.2 : 2.4}
                onClick={() => place(region)}
                onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); place(region); } }}
              >
                <title>{region.label}</title>
              </circle>
            </g>
          );
        })}
      </svg>
      {error && <p className="studio-error" role="alert">{error}</p>}
      {marks.length > 0 && (
        <ul className="studio-placed" aria-label={t('已加的特征')}>
          {marks.map((mark, index) => (
            <li key={`${mark.kind}-${mark.region}-${mark.text}`}>
              <span>{label(mark)}</span>
              <button
                type="button"
                aria-label={t('去掉 {0}', [label(mark)])}
                onClick={() => onChange(marks.filter((_item, at) => at !== index))}
              >
                <X size={12} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
