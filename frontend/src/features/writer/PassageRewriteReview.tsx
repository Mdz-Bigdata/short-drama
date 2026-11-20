import { useMemo, useState } from 'react';

import { ApiError } from '../../api/client';
import { t } from '../../i18n';
import {
  passageOperations,
  patchScreenwritingPlan,
  putEpisodeStateChanges,
  rewritePassage,
  type PassageRewriteResult,
  type PassageShotFields,
  type ScreenwritingEpisode,
} from './screenwritingApi';
import './PassageRewriteReview.css';

interface Props {
  taskId: string;
  episode: ScreenwritingEpisode;
  disabled?: boolean;
  /** 采纳并写回后的这一集；sheetChanged 为真时本集场记也换了。 */
  onApplied: (updated: ScreenwritingEpisode, sheetChanged: boolean) => void;
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function Shot({ fields }: { fields: Partial<PassageShotFields> }) {
  return (
    <div className="passage-rewrite__shot">
      <small>{fields.setting || '—'} · {(fields.characters_in_scene ?? []).join('、') || t('无角色')}</small>
      <p>{fields.scene_description || '—'}</p>
      {(fields.utterances ?? []).map((utterance, index) => (
        <p key={index} className="passage-rewrite__line">
          <b>{utterance.kind === 'dialogue' ? utterance.speaker : t('旁白')}</b>{utterance.text}
        </p>
      ))}
    </div>
  );
}

/**
 * 改写一段：选连着的几个分镜、写一句怎么改，先给出改后版本和这次改动会碰到的伏笔、约定与后面各集的事。
 * 人看过再决定：照样采纳（可同时更新本集场记）、让它守住这些再改一次，或者放弃。写回走分镜规划的编辑接口。
 */
export function PassageRewriteReview({ taskId, episode, disabled, onApplied }: Props) {
  const ids = useMemo(() => episode.plan.scenes.map(scene => scene.scene_id), [episode]);
  const [from, setFrom] = useState(ids[0] ?? '');
  const [to, setTo] = useState(ids[0] ?? '');
  const [instruction, setInstruction] = useState('');
  const [busy, setBusy] = useState<'' | 'rewrite' | 'apply'>('');
  const [result, setResult] = useState<PassageRewriteResult | null>(null);
  const [syncSheet, setSyncSheet] = useState(true);
  const [notice, setNotice] = useState('');

  // 规划改过、选着的分镜不在了，就落回第一个，免得选着已经不存在的分镜。
  const start = ids.includes(from) ? from : (ids[0] ?? '');
  const end = ids.includes(to) ? to : (ids[0] ?? '');
  const selected = useMemo(() => {
    const first = ids.indexOf(start);
    const last = ids.indexOf(end);
    if (first < 0 || last < 0) return [];
    return ids.slice(Math.min(first, last), Math.max(first, last) + 1);
  }, [ids, start, end]);

  const findings = result?.impact.findings ?? [];
  const lostKeyLines = result?.impact.lost_key_lines ?? [];
  const sheetBefore = result?.impact.state_changes.before ?? [];
  const sheetAfter = result?.impact.state_changes.after ?? [];
  const sheetDiffers = sheetBefore.join('\n') !== sheetAfter.join('\n');
  const keepList = [...findings.map(item => item.fact), ...lostKeyLines];

  const ask = async (keep: string[] = []) => {
    if (!selected.length || !instruction.trim()) return;
    setBusy('rewrite');
    setNotice('');
    try {
      const value = await rewritePassage(taskId, episode.episode, { sceneIds: selected, instruction: instruction.trim(), keep });
      setResult(value);
      const { before, after } = value.impact.state_changes;
      setSyncSheet(before.join('\n') !== after.join('\n'));
    } catch (caught) {
      setNotice(errorText(caught, t('改写失败，请稍后再试')));
    } finally {
      setBusy('');
    }
  };

  const apply = async () => {
    if (!result) return;
    setBusy('apply');
    setNotice('');
    const operations = passageOperations(result);
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
        if (!window.confirm(t('写回改写会归档当前角色、分镜和成片，并从编剧阶段重新开始。旧成果仍保留在版本归档中。是否继续？'))) {
          setNotice(t('已取消，改写结果还在，可以稍后再采纳。'));
          return;
        }
        updated = await submit(true);
      }
      const sheetChanged = syncSheet && sheetDiffers;
      if (sheetChanged) await putEpisodeStateChanges(taskId, episode.episode, result.impact.state_changes.after);
      const later = [...new Set(result.impact.findings.map(item => item.episode).filter(number => number > episode.episode))];
      setResult(null);
      setNotice(later.length
        ? t('已写回 {0} 个分镜。第 {1} 集可能要跟着改。', [String(operations.length), later.join('、')])
        : t('已写回 {0} 个分镜。', [String(operations.length)]));
      onApplied(updated, sheetChanged);
    } catch (caught) {
      setNotice(errorText(caught, t('写回失败，请稍后再试')));
    } finally {
      setBusy('');
    }
  };

  return (
    <section className="passage-rewrite" aria-label={t('改写一段')}>
      <div className="passage-rewrite__bar">
        <label>
          {t('从')}
          <select value={start} disabled={busy !== ''} onChange={event => setFrom(event.target.value)} aria-label={t('改写起点分镜')}>
            {ids.map(id => <option key={id} value={id}>{id}</option>)}
          </select>
        </label>
        <label>
          {t('到')}
          <select value={end} disabled={busy !== ''} onChange={event => setTo(event.target.value)} aria-label={t('改写终点分镜')}>
            {ids.map(id => <option key={id} value={id}>{id}</option>)}
          </select>
        </label>
        <input
          type="text" maxLength={600} value={instruction} disabled={busy !== ''}
          placeholder={t('要怎么改，如：让对手先动手，主角后发制人')} aria-label={t('改写要求')}
          onChange={event => setInstruction(event.target.value)}
        />
        <button type="button" className="secondary-action" disabled={disabled || busy !== '' || !instruction.trim() || !selected.length}
          title={t('只改选中的分镜，再核对这次改动会碰到哪些伏笔、约定和后面各集的事；会调用两次文本模型，结果先给你看。')}
          onClick={() => { void ask(); }}>
          {busy === 'rewrite' ? t('改写中…') : t('改写这 {0} 个分镜', [String(selected.length)])}
        </button>
      </div>
      {notice && <p className="passage-rewrite__notice" role="status">{notice}</p>}
      {result && (
        <>
          <ul className="passage-rewrite__list">
            {result.scenes.map(row => (
              <li key={row.scene_id}>
                <code>{row.scene_id}</code>
                <div className="passage-rewrite__pair">
                  <div className="passage-rewrite__before"><span>{t('改前')}</span><Shot fields={row.before} /></div>
                  <div className="passage-rewrite__after"><span>{t('改后')}</span><Shot fields={row.after} /></div>
                </div>
              </li>
            ))}
          </ul>
          <div className="passage-rewrite__impact" role="note" aria-label={t('这次改动的后果')}>
            {!result.impact.checked && <p>{t('这次没能核对后果，采纳前请自己对一下前后各集。')}</p>}
            {result.impact.checked && findings.length === 0 && lostKeyLines.length === 0 && <p>{t('没发现这次改动碰到伏笔、约定或后面各集的事。')}</p>}
            {(findings.length > 0 || lostKeyLines.length > 0) && (
              <ul>
                {lostKeyLines.map(line => <li key={line}><b>{t('本集')}</b>{t('{0} 改没了', [line])}</li>)}
                {findings.map((item, index) => (
                  <li key={index}>
                    <b>{item.episode === episode.episode ? t('本集') : t('第 {0} 集', [String(item.episode)])}</b>
                    <span>{item.fact}</span>
                    {item.quote && <small>{t('起因：{0}', [item.quote])}</small>}
                    <em>{item.fix}</em>
                  </li>
                ))}
              </ul>
            )}
            {sheetDiffers && (
              <div className="passage-rewrite__sheet">
                <label>
                  <input type="checkbox" checked={syncSheet} onChange={event => setSyncSheet(event.target.checked)} />
                  {t('采纳时同时更新本集场记')}
                </label>
                <div className="passage-rewrite__pair">
                  <ul aria-label={t('本集场记改前')}>{sheetBefore.map(line => <li key={line}><del>{line}</del></li>)}</ul>
                  <ul aria-label={t('本集场记改后')}>{sheetAfter.map(line => <li key={line}><ins>{line}</ins></li>)}</ul>
                </div>
              </div>
            )}
          </div>
          <div className="passage-rewrite__bar">
            <button type="button" className="primary-action" disabled={busy !== ''} onClick={() => { void apply(); }}>
              {busy === 'apply' ? t('写回中…') : t('采纳改写')}
            </button>
            {keepList.length > 0 && (
              <button type="button" className="secondary-action" disabled={busy !== ''} onClick={() => { void ask(keepList); }}>
                {t('守住这些再改一次')}
              </button>
            )}
            <button type="button" className="secondary-action" disabled={busy !== ''} onClick={() => setResult(null)}>{t('放弃')}</button>
          </div>
        </>
      )}
    </section>
  );
}
