import { AlertTriangle, Plus, RotateCcw, Trash2, UserRound } from 'lucide-react';

import { t } from '../../i18n';
import { clipKey, type NameCard, type StudioClip } from './postProduction';

/** 一个片段最多几条(与服务端 character_intro.json 的 limits.cards_per_clip 一致)。 */
export const CARDS_PER_CLIP = 4;

interface Props {
  clips: StudioClip[];
  /** 播放头所在的片段：「添加」加在它上面。 */
  current?: StudioClip;
  enabled: boolean;
  busy: boolean;
  /** cards 不给 = 交还给自动排的；给空列表 = 这一镜不出。 */
  onChange: (clip: StudioClip, cards: NameCard[] | undefined) => void;
}

const labelOf = (clip: StudioClip) => (clip.scene_id ? `${clip.scene_id} · ` : '') + t('镜头 {0}', [clip.shot_id]);

/** What the server needs back for one clip: the fields a person can change, nothing derived. */
const plain = (cards: NameCard[]): NameCard[] => cards.map(({ name, identity, side, at }) => ({ name, identity, side, at }));

/**
 * 人物出场字幕：谁第一次出场，在哪一镜、哪一侧、第几秒出字。自动排的可以改，改过的片段不再被自动覆盖。
 * 位置和时间来自分镜，不是看着画面定的；标了「请核对」的是同一侧还站着别人、可能认错人的。
 */
export function NameCards({ clips, current, enabled, busy, onChange }: Props) {
  const rows = clips.flatMap(clip => (clip.name_cards ?? []).map((card, index) => ({ clip, card, index })));
  const edited = clips.filter(clip => clip.name_cards_edited);
  const canAdd = Boolean(current) && (current?.name_cards?.length ?? 0) < CARDS_PER_CLIP;

  const change = (clip: StudioClip, index: number, patch: Partial<NameCard>) => {
    const cards = plain(clip.name_cards ?? []);
    cards[index] = { ...cards[index], ...patch };
    onChange(clip, cards);
  };
  const remove = (clip: StudioClip, index: number) => onChange(clip, plain(clip.name_cards ?? []).filter((_, at) => at !== index));
  const add = () => {
    if (!current) return;
    onChange(current, [...plain(current.name_cards ?? []), { name: t('姓名'), identity: '', side: 'right', at: 0.6 }]);
  };

  return (
    <section className="pp-card pp-names" aria-labelledby="pp-names">
      <h4 id="pp-names"><UserRound aria-hidden="true" /> {t('人物出场字幕')}</h4>
      <p className="pp-names-hint">
        {enabled
          ? t('人物第一次出场时，在身旁竖排显示姓名和身份，之后不再出现。位置和时间按分镜排，可以在这里改。')
          : t('「人物出场字幕」已在基础设定里关掉，成片里不会出现；下面的内容仍会保留。')}
      </p>
      {rows.length === 0 && <p className="pp-names-empty">{t('这一集没有第一次出场的人物。')}</p>}
      <ul className="pp-names-list">
        {rows.map(({ clip, card, index }) => (
          <li key={`${clipKey(clip)}-${index}-${card.name}-${card.identity}-${card.at}`} className={card.unsure ? 'is-unsure' : undefined}>
            <div className="pp-names-where">
              <b>{labelOf(clip)}</b>
              {card.unsure && (
                <span className="pp-names-flag" title={t('分镜里这一侧还站着别人，字幕可能落在别人身旁；看一眼成片，必要时换一侧或换个时间。')}>
                  <AlertTriangle aria-hidden="true" /> {t('请核对位置')}
                </span>
              )}
              {clip.name_cards_edited && <span className="pp-names-edited">{t('已手动修改')}</span>}
            </div>
            <div className="pp-names-fields">
              <input
                type="text" defaultValue={card.name} maxLength={8} disabled={busy} aria-label={t('{0} 的姓名', [labelOf(clip)])}
                onBlur={event => { const value = event.target.value.trim(); if (value && value !== card.name) change(clip, index, { name: value }); else event.target.value = card.name; }}
              />
              <input
                type="text" defaultValue={card.identity} maxLength={12} disabled={busy} placeholder={t('身份')} aria-label={t('{0} 的身份', [card.name])}
                onBlur={event => { const value = event.target.value.trim(); if (value !== card.identity) change(clip, index, { identity: value }); }}
              />
            </div>
            <div className="pp-names-place">
              <button type="button" disabled={busy} aria-label={t('{0} 的字幕在画面哪一侧', [card.name])}
                onClick={() => change(clip, index, { side: card.side === 'left' ? 'right' : 'left' })}>
                {card.side === 'left' ? t('画面左侧') : t('画面右侧')}
              </button>
              <label>
                {t('出现时间（秒）')}
                <input
                  type="number" min={0} max={60} step={0.1} defaultValue={card.at} disabled={busy} aria-label={t('{0} 的字幕在片段第几秒出现', [card.name])}
                  onBlur={event => { const value = Number(event.target.value); if (Number.isFinite(value) && value >= 0 && value !== card.at) change(clip, index, { at: value }); else event.target.value = String(card.at); }}
                />
              </label>
              <button type="button" className="pp-icon" disabled={busy} aria-label={t('删除 {0} 的出场字幕', [card.name])} onClick={() => remove(clip, index)}>
                <Trash2 aria-hidden="true" />
              </button>
            </div>
          </li>
        ))}
      </ul>
      <div className="pp-names-actions">
        <button type="button" disabled={busy || !canAdd} onClick={add}>
          <Plus aria-hidden="true" /> {current ? t('给 {0} 加一条', [labelOf(current)]) : t('加一条')}
        </button>
        {edited.map(clip => (
          <button key={clipKey(clip)} type="button" disabled={busy} onClick={() => onChange(clip, undefined)}>
            <RotateCcw aria-hidden="true" /> {t('{0} 恢复自动', [labelOf(clip)])}
          </button>
        ))}
      </div>
    </section>
  );
}
