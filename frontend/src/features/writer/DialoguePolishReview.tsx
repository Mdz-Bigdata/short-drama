import { useState } from 'react';

import { ApiError } from '../../api/client';
import { t } from '../../i18n';
import {
  patchScreenwritingPlan,
  polishEpisodeDialogue,
  polishOperations,
  type DialoguePolishResult,
  type ScreenwritingEpisode,
} from './screenwritingApi';
import './DialoguePolishReview.css';

/** 戏路：选了就按这场戏的口气改（吵架写旧账、和解先别扭再松口……），不选按台词本身改。 */
const SCENE_KINDS = ['', '吵架', '和解', '安慰', '暧昧', '重逢', '家人'] as const;

interface Props {
  taskId: string;
  episode: ScreenwritingEpisode;
  disabled?: boolean;
  /** 采纳并写回后的这一集。 */
  onApplied: (updated: ScreenwritingEpisode) => void;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : t('润色失败，请稍后再试');
}

/**
 * 润色台词：整集送去改得更像真人开口，逐句给出改前改后，人勾选采纳后才写回剧本。
 * 写回走分镜规划的编辑接口，下游失效时和「保存」一样先确认。
 */
export function DialoguePolishReview({ taskId, episode, disabled, onApplied }: Props) {
  const [kind, setKind] = useState<(typeof SCENE_KINDS)[number]>('');
  const [extra, setExtra] = useState('');
  const [busy, setBusy] = useState<'' | 'polish' | 'apply'>('');
  const [result, setResult] = useState<DialoguePolishResult | null>(null);
  const [accepted, setAccepted] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState('');

  const polish = async () => {
    setBusy('polish');
    setNotice('');
    try {
      const value = await polishEpisodeDialogue(taskId, episode.episode, { sceneKind: kind, extra });
      setResult(value);
      // 改了的句子默认勾上；没改的不勾（原样返回的不用写回）。
      setAccepted(new Set(value.items.filter(item => item.after !== item.before).map(item => item.id)));
      if (!value.items.some(item => item.after !== item.before)) setNotice(t('这一集的台词已经很自然，没有要改的。'));
    } catch (caught) {
      setNotice(errorText(caught));
    } finally {
      setBusy('');
    }
  };

  const apply = async () => {
    if (!result) return;
    const operations = polishOperations(result, accepted);
    if (!operations.length) return;
    setBusy('apply');
    setNotice('');
    const submit = (confirmInvalidate: boolean) => patchScreenwritingPlan(taskId, episode.episode, {
      baseRevision: result.plan_revision, operations, confirmInvalidate,
    });
    try {
      let updated: ScreenwritingEpisode;
      try {
        updated = await submit(false);
      } catch (caught) {
        const needsConfirm = caught instanceof ApiError && caught.status === 409 && /归档|下游|成片|角色、分镜/.test(String(caught.message));
        if (!needsConfirm) throw caught;
        if (!window.confirm(t('写回润色后的台词会归档当前角色、分镜和成片，并从编剧阶段重新开始。旧成果仍保留在版本归档中。是否继续？'))) {
          setNotice(t('已取消，润色结果还在，可以稍后再采纳。'));
          return;
        }
        updated = await submit(true);
      }
      setResult(null);
      setNotice(t('已写回 {0} 句台词。', [String(accepted.size)]));
      onApplied(updated);
    } catch (caught) {
      setNotice(errorText(caught));
    } finally {
      setBusy('');
    }
  };

  const toggle = (id: string) => setAccepted(current => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const changed = result?.items.filter(item => item.after !== item.before) ?? [];

  return (
    <section className="dialogue-polish" aria-label={t('润色台词')}>
      <div className="dialogue-polish__bar">
        <label>
          {t('戏路')}
          <select value={kind} onChange={event => setKind(event.target.value as (typeof SCENE_KINDS)[number])} disabled={busy !== ''}>
            {SCENE_KINDS.map(value => <option key={value || 'any'} value={value}>{value ? t(value) : t('不限')}</option>)}
          </select>
        </label>
        <input
          type="text" maxLength={300} value={extra} disabled={busy !== ''}
          placeholder={t('额外要求（可不填），如：再冷一点')} aria-label={t('润色的额外要求')}
          onChange={event => setExtra(event.target.value)}
        />
        <button type="button" className="secondary-action" disabled={disabled || busy !== ''}
          title={t('把这一集的台词改得更像真人当下开口；会调用一次文本模型，结果先给你看，勾选后才写回。')}
          onClick={() => { void polish(); }}>
          {busy === 'polish' ? t('润色中…') : t('润色台词')}
        </button>
      </div>
      {notice && <p className="dialogue-polish__notice" role="status">{notice}</p>}
      {result && changed.length > 0 && (
        <>
          <ul className="dialogue-polish__list">
            {changed.map(item => (
              <li key={item.id}>
                <label>
                  <input type="checkbox" checked={accepted.has(item.id)} onChange={() => toggle(item.id)} aria-label={t('采纳 {0} 的这句', [item.speaker])} />
                  <span className="dialogue-polish__where">{item.scene_id} · {item.speaker}</span>
                </label>
                <del>{item.before}</del>
                <ins>{item.after}</ins>
              </li>
            ))}
          </ul>
          <div className="dialogue-polish__bar">
            <button type="button" className="primary-action" disabled={busy !== '' || accepted.size === 0} onClick={() => { void apply(); }}>
              {busy === 'apply' ? t('写回中…') : t('采纳选中的 {0} 句', [String(accepted.size)])}
            </button>
            <button type="button" className="secondary-action" disabled={busy !== ''} onClick={() => setResult(null)}>{t('放弃')}</button>
          </div>
        </>
      )}
    </section>
  );
}
