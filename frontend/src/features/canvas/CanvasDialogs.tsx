import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';

import { t } from '../../i18n';
import { previewCommit } from './canvasApi';
import type { CommitPreview, CommitResult, RunAssessment, RunStart, TierConfirmation } from './canvasTypes';

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    panel.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onClose]);
  return (
    <div className="cn-dialog-backdrop">
      <div ref={panel} className="cn-dialog" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

function costLine(assessment: RunAssessment) {
  const { totals, paid_items: paid, unpriced_items: unpriced } = assessment.estimate;
  if (!paid) return t('本机处理，不调用付费模型。');
  const priced = totals.map(item => `${item.cost} ${item.currency}`).join(' + ');
  if (priced && unpriced) return t('参考费用约 {0}，另有 {1} 项未定价', [priced, unpriced]);
  if (priced) return t('参考费用约 {0}', [priced]);
  return t('{0} 项都没有定价，费用无法估算', [unpriced]);
}

export function RunDialog({ assessment: initial, onClose, onConfirm }: {
  assessment: RunAssessment;
  onClose: () => void;
  onConfirm: (confirmations: TierConfirmation[]) => Promise<RunStart>;
}) {
  const [assessment, setAssessment] = useState(initial);
  const [tiersAccepted, setTiersAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const blocked = assessment.decision === 'blocked';
  const tiers = assessment.confirmations;

  const confirm = () => {
    if (busy) return;
    setBusy(true);
    setProblem('');
    onConfirm(tiersAccepted ? tiers : [])
      .then(outcome => {
        if (outcome.status === 'started') {
          onClose();
        } else if (outcome.assessment) {
          // Something changed since the quote: show what the server sees now instead of proceeding.
          setAssessment(outcome.assessment);
          setTiersAccepted(false);
        }
      })
      .catch(error => setProblem(messageOf(error, t('启动失败'))))
      .finally(() => setBusy(false));
  };

  return (
    <Dialog title={blocked ? t('这批节点不能运行') : t('确认运行')} onClose={onClose}>
      <ul className="cn-dialog__rows">
        {assessment.nodes.map(node => (
          <li key={node.node_id} className={node.quote === 'blocked' ? 'is-blocked' : ''}>
            <strong>{node.label}</strong>
            <small>
              {node.model || t('未选模型')}
              {node.requested_seconds > 0 ? ` · ${t('{0} 秒', [node.requested_seconds])}` : ''}
              {node.paid && node.estimate.priced && node.estimate.currency ? ` · ${node.estimate.cost} ${node.estimate.currency}` : ''}
              {node.paid && !node.estimate.priced ? ` · ${t('未定价')}` : ''}
            </small>
            {node.problems.map(problem_ => (
              <p key={problem_.code + problem_.message} className={problem_.blocking ? 'cn-error' : 'cn-hint'}>{problem_.message}</p>
            ))}
          </li>
        ))}
      </ul>
      {tiers.length > 0 && !blocked && (
        <label className="cn-dialog__tiers">
          <input type="checkbox" checked={tiersAccepted} onChange={event => setTiersAccepted(event.target.checked)} />
          <span>
            {t('接受模型档位调整：')}
            {tiers.map(item => t('{0} 秒按 {1} 秒请求 × {2}', [item.scripted_seconds, item.requested_seconds, item.shot_count])).join('；')}
          </span>
        </label>
      )}
      {!blocked && <p className="cn-dialog__cost">{costLine(assessment)}</p>}
      {blocked && <p className="cn-hint">{t('一个节点不能跑，整批都不提交，也不会计费。')}</p>}
      {problem && <p className="cn-error" role="alert">{problem}</p>}
      <footer className="cn-dialog__foot">
        <button type="button" className="cn-button" onClick={onClose}>{blocked ? t('知道了') : t('取消')}</button>
        {!blocked && (
          <button type="button" className="cn-button is-primary" disabled={busy || (tiers.length > 0 && !tiersAccepted)} onClick={confirm}>
            {busy && <Loader2 className="cn-spin" aria-hidden="true" />}
            {assessment.estimate.paid_items ? t('确认并运行') : t('运行')}
          </button>
        )}
      </footer>
    </Dialog>
  );
}

export function CommitDialog({ projectId, canvasId, nodeIds, onClose, onCommit }: {
  projectId: string;
  canvasId: string;
  nodeIds: string[];
  onClose: () => void;
  onCommit: (nodeIds: string[]) => Promise<CommitResult>;
}) {
  const [preview, setPreview] = useState<CommitPreview | null>(null);
  const [result, setResult] = useState<CommitResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');

  useEffect(() => {
    previewCommit(projectId, canvasId, nodeIds)
      .then(setPreview)
      .catch(error => setProblem(messageOf(error, t('影响预览失败'))));
  }, [canvasId, nodeIds, projectId]);

  const ready = preview?.nodes.filter(row => row.state === 'ready').map(row => row.node_id) ?? [];
  const failed = result?.results.filter(item => item.status === 'failed') ?? [];

  const send = (ids: string[]) => {
    setBusy(true);
    setProblem('');
    onCommit(ids)
      .then(setResult)
      .catch(error => setProblem(messageOf(error, t('提交失败'))))
      .finally(() => setBusy(false));
  };

  const stateText = (state: string, reason: string) => {
    if (state === 'already') return t('已经提交过');
    if (state === 'no_provenance') return t('没有来源记录，跳过');
    if (state === 'no_result') return t('还没有结果，跳过');
    return reason;
  };

  return (
    <Dialog title={t('提交到项目')} onClose={onClose}>
      {!preview && !problem && <p className="cn-hint">{t('读取中…')}</p>}
      {preview && !result && (
        <>
          <p className="cn-dialog__cost">{t('影响 {0} 个镜头', [preview.impacted_shots])}</p>
          <ul className="cn-dialog__rows">
            {preview.nodes.map(row => (
              <li key={row.node_id} className={row.state === 'ready' ? '' : 'is-skipped'}>
                <strong>{row.label}</strong>
                {row.state === 'ready' ? (
                  <small>
                    {row.impact.count > 0 ? t('影响 {0} 个镜头', [row.impact.count]) : t('不绑定镜头，只存为项目产物')}
                    {row.impact.count > 0 && !row.applies_to_shots ? ` · ${t('这种结果不写入镜头')}` : ''}
                    {row.impact.shots.length > 0 ? `：${row.impact.shots.slice(0, 6).map(shot => `${shot.scene_id}#${shot.shot_id}`).join('、')}${row.impact.shots.length > 6 ? '…' : ''}` : ''}
                  </small>
                ) : <small>{stateText(row.state, row.reason)}</small>}
              </li>
            ))}
          </ul>
          {(preview.counts.no_provenance + preview.counts.no_result + preview.counts.already) > 0 && (
            <p className="cn-hint">{t('将跳过 {0} 个：没有来源 {1}，没有结果 {2}，已提交 {3}', [
              preview.counts.no_provenance + preview.counts.no_result + preview.counts.already,
              preview.counts.no_provenance, preview.counts.no_result, preview.counts.already,
            ])}</p>
          )}
        </>
      )}
      {result && (
        <>
          <p className="cn-dialog__cost">
            <CheckCircle2 aria-hidden="true" /> {t('已提交 {0} 个，跳过 {1} 个（其中没有来源 {2} 个），失败 {3} 个', [result.counts.committed, result.counts.skipped, result.counts.no_provenance, result.counts.failed])}
          </p>
          {failed.length > 0 && (
            <ul className="cn-dialog__rows">
              {failed.map(item => (
                <li key={item.node_id} className="is-blocked">
                  <strong><AlertTriangle aria-hidden="true" /> {item.label}</strong>
                  <p className="cn-error">{item.reason}</p>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {problem && <p className="cn-error" role="alert">{problem}</p>}
      <footer className="cn-dialog__foot">
        <button type="button" className="cn-button" onClick={onClose}>{result ? t('完成') : t('取消')}</button>
        {!result && (
          <button type="button" className="cn-button is-primary" disabled={busy || !ready.length} onClick={() => send(ready)}>
            {busy && <Loader2 className="cn-spin" aria-hidden="true" />} {t('提交 {0} 个节点', [ready.length])}
          </button>
        )}
        {failed.length > 0 && (
          <button type="button" className="cn-button is-primary" disabled={busy} onClick={() => send(failed.map(item => item.node_id))}>
            {busy && <Loader2 className="cn-spin" aria-hidden="true" />} {t('重试失败的 {0} 个', [failed.length])}
          </button>
        )}
      </footer>
    </Dialog>
  );
}
