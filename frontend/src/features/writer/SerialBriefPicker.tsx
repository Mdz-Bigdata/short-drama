import { useEffect, useState } from 'react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import {
  ENDINGS, GENRES, MAX_GENRES, PAYWALL_KINDS, TONES, genreClashes, type SerialBrief,
} from './serialBrief';
import './ScriptStructurePicker.css';
import './SerialBriefPicker.css';

interface PaywallAnswer {
  episodes: { episode: number; kind: string; label: string }[];
  min_episodes: number;
}

/**
 * 连载立项：题材可以叠到三个(第一个定基调)，基调、结局各选一种，再点一次取消；出海与付费卡点是两个开关。
 * 每一项都可以不选，没选的由总导演自己定。选了的写进总导演的方案要求，也告诉每一批分集规划。
 * 付费卡点落在哪几集由集数算出来(不调用模型)，勾上之后才去取。
 */
export function SerialBriefPicker({ value, onChange, episodeCount }: {
  value: SerialBrief;
  onChange: (next: SerialBrief) => void;
  episodeCount: number;
}) {
  const [shown, setShown] = useState('');
  const [plan, setPlan] = useState<PaywallAnswer | null>(null);
  const [failed, setFailed] = useState(false);
  const lead = value.genres[0] ?? '';

  useEffect(() => {
    if (!value.paywall) return undefined;
    const controller = new AbortController();
    // 拖集数滑块时不要每一格都发一次请求。
    const timer = window.setTimeout(() => {
      const query = new URLSearchParams({ episodes: String(episodeCount), ...(lead ? { genre: lead } : {}) });
      apiRequest<PaywallAnswer>(`/api/serial-brief/paywall?${query}`, { signal: controller.signal })
        .then(answer => { setPlan(answer); setFailed(false); })
        .catch(() => { if (!controller.signal.aborted) { setPlan(null); setFailed(true); } });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [value.paywall, episodeCount, lead]);

  const toggleGenre = (id: string) => {
    const picked = value.genres.includes(id);
    if (!picked && value.genres.length >= MAX_GENRES) return;
    setShown(picked ? '' : id);
    onChange({ ...value, genres: picked ? value.genres.filter(item => item !== id) : [...value.genres, id] });
  };

  const hinted = GENRES.find(item => item.id === (shown && value.genres.includes(shown) ? shown : lead));
  const full = value.genres.length >= MAX_GENRES;
  const tone = TONES.find(item => item.id === value.tone);
  const ending = ENDINGS.find(item => item.id === value.ending);
  const kindLabel = (kind: string, fallback: string) => {
    const known = PAYWALL_KINDS.find(item => item.id === kind);
    return known ? t(known.label) : fallback;
  };

  return (
    <div className="serial-brief">
      <div className="structure-picker">
        <div className="structure-picker__head">
          <span id="new-project-genres-label" className="structure-picker__title">{t('题材')}</span>
          <span className="structure-picker__note">
            {hinted ? t(hinted.hint) : t('可以叠到 {0} 个，第一个定基调；不选由总导演定', [MAX_GENRES])}
          </span>
        </div>
        <div className="structure-picker__chips" role="group" aria-labelledby="new-project-genres-label">
          {GENRES.map(item => {
            const order = value.genres.indexOf(item.id);
            return (
              <button
                key={item.id}
                type="button"
                aria-pressed={order >= 0}
                disabled={order < 0 && full}
                className={`structure-picker__chip${order >= 0 ? ' is-active' : ''}`}
                title={t(item.hint)}
                onClick={() => toggleGenre(item.id)}
              >
                {order >= 0 && value.genres.length > 1 && <span className="serial-brief__order">{order + 1}</span>}
                {t(item.label)}
              </button>
            );
          })}
        </div>
        {full && <p className="structure-picker__note">{t('已经叠了 {0} 个，再点一个已选的可以取消', [MAX_GENRES])}</p>}
        {genreClashes(value.genres).map(say => <p key={say} className="serial-brief__clash" role="status">{t(say)}</p>)}
      </div>

      <div className="serial-brief__pair">
        <div className="structure-picker">
          <div className="structure-picker__head">
            <span id="new-project-tone-label" className="structure-picker__title">{t('故事基调')}</span>
            <span className="structure-picker__note">{tone ? t(tone.hint) : t('不选由总导演定')}</span>
          </div>
          <div className="structure-picker__chips" role="radiogroup" aria-labelledby="new-project-tone-label">
            {TONES.map(item => (
              <button
                key={item.id} type="button" role="radio" aria-checked={value.tone === item.id} title={t(item.hint)}
                className={`structure-picker__chip${value.tone === item.id ? ' is-active' : ''}`}
                onClick={() => onChange({ ...value, tone: value.tone === item.id ? '' : item.id })}
              >
                {t(item.label)}
              </button>
            ))}
          </div>
        </div>
        <div className="structure-picker">
          <div className="structure-picker__head">
            <span id="new-project-ending-label" className="structure-picker__title">{t('结局')}</span>
            <span className="structure-picker__note">{ending ? t(ending.hint) : t('不选由总导演定')}</span>
          </div>
          <div className="structure-picker__chips" role="radiogroup" aria-labelledby="new-project-ending-label">
            {ENDINGS.map(item => (
              <button
                key={item.id} type="button" role="radio" aria-checked={value.ending === item.id} title={t(item.hint)}
                className={`structure-picker__chip${value.ending === item.id ? ' is-active' : ''}`}
                onClick={() => onChange({ ...value, ending: value.ending === item.id ? '' : item.id })}
              >
                {t(item.label)}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="serial-brief__switches">
        <label className="serial-brief__switch">
          <input type="checkbox" checked={value.overseas} onChange={event => onChange({ ...value, overseas: event.target.checked })} />
          <span>
            <strong>{t('出海')}</strong>
            <small>{t('面向海外观众：换掉只有国内观众才懂的冲突与符号')}</small>
          </span>
        </label>
        <label className="serial-brief__switch">
          <input type="checkbox" checked={value.paywall} onChange={event => onChange({ ...value, paywall: event.target.checked })} />
          <span>
            <strong>{t('规划付费卡点')}</strong>
            <small>{t('按集数算出卡点落在哪几集，卡点集停在答案出来的前一刻')}</small>
          </span>
        </label>
      </div>

      {value.paywall && failed && <p className="serial-brief__clash" role="status">{t('付费卡点的位置没有取到，不影响创建')}</p>}
      {value.paywall && plan && plan.episodes.length === 0 && (
        <p className="structure-picker__note" role="status">{t('不到 {0} 集的剧不规划付费卡点', [plan.min_episodes])}</p>
      )}
      {value.paywall && plan && plan.episodes.length > 0 && (
        <div className="serial-brief__plan" role="status">
          <span className="structure-picker__note">{t('共 {0} 个付费卡点', [plan.episodes.length])}</span>
          <ol>
            {plan.episodes.map(row => (
              <li key={row.episode}>
                <b>{t('第 {0} 集', [row.episode])}</b>
                <span>{kindLabel(row.kind, row.label)}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
