import { useCallback, useEffect, useState } from 'react';
import { ClipboardCheck, Download, LoaderCircle, X } from 'lucide-react';

import { API_BASE, ApiError, apiRequest } from '../../api/client';
import { t } from '../../i18n';
import { useDialogFocus } from './useDialogFocus';
import './ScriptReviewDialog.css';

export interface ScriptReviewFinding {
  dimension: string;
  dimension_label: string;
  severity: string;
  severity_label: string;
  scene: string;
  where: string;
  quote: string;
  issue: string;
  fix: string;
}

export interface ScriptReviewReport {
  built_at: string;
  model: string;
  calls: number;
  summary: string;
  dimensions: Array<{ key: string; label: string; verdict: string; verdict_label: string; note: string }>;
  findings: ScriptReviewFinding[];
  strengths: string[];
  quotes_dropped: number;
}

export interface ScriptReviewView {
  title: string;
  /** Which check this is: '' is the full review. */
  focus?: string;
  label?: string;
  focuses?: Array<{ key: string; label: string; about: string }>;
  /** Why this check cannot run on this project (no character sheet to hold the lines against); '' when it can. */
  blocked?: string;
  report: ScriptReviewReport | null;
  stale: boolean;
  facts: Array<{ key: string; label: string; value: string }>;
  calls_needed: number;
  attempts: number;
  model: string;
  advice: string;
}

const pathOf = (taskId: string, focus = '', format = '') => {
  const query = [focus ? `focus=${encodeURIComponent(focus)}` : '', format ? `format=${format}` : ''].filter(Boolean).join('&');
  return `/api/drama/${encodeURIComponent(taskId)}/script-review${query ? `?${query}` : ''}`;
};

function builtAt(value: string): string {
  const time = new Date(value);
  return Number.isNaN(time.getTime()) ? value : time.toLocaleString();
}

/**
 * 剧本审核报告：把写完的剧本交给项目的文本模型按七个方面读一遍，每条问题落到具体的场次并给出改法。
 * 只是建议，不改剧本。打开时只读上次的报告和从剧本数出来的概况；点了「生成」并确认之后才调用模型。
 */
export function ScriptReviewDialog({ taskId, onClose }: { taskId: string; onClose: () => void }) {
  const [shown, setShown] = useState<ScriptReviewView | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  // 全面审核，或一项专项体检（前三集主线、台词对照人物小传）：各有各的报告。
  const [focus, setFocus] = useState('');
  const closeRef = useDialogFocus<HTMLButtonElement>();

  useEffect(() => {
    const controller = new AbortController();
    apiRequest<ScriptReviewView>(pathOf(taskId, focus), { signal: controller.signal })
      .then(data => { setShown(data); setError(''); })
      .catch(reason => {
        if (!controller.signal.aborted) setError(reason instanceof ApiError && reason.message ? reason.message : t('审核报告没有读出来，请稍后重试。'));
      });
    return () => controller.abort();
  }, [taskId, focus]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busy) onClose(); };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [busy, onClose]);

  const run = useCallback(async () => {
    setAsking(false);
    setBusy(true);
    setError('');
    try {
      setShown(await apiRequest<ScriptReviewView>(pathOf(taskId, focus), { method: 'POST' }));
    } catch (reason) {
      setError(reason instanceof ApiError && reason.message ? reason.message : t('审核报告没有生成，请稍后重试。'));
    } finally {
      setBusy(false);
    }
  }, [taskId, focus]);

  const report = shown?.report ?? null;
  const choices = shown?.focuses ?? [];
  const about = choices.find(item => item.key === focus)?.about;
  const calls = shown?.calls_needed ?? 0;
  return (
    <div className="script-review__backdrop" role="presentation" onClick={() => { if (!busy) onClose(); }}>
      <section className="script-review" role="dialog" aria-modal="true" aria-labelledby="script-review-title" onClick={event => event.stopPropagation()}>
        <header>
          <div>
            <h2 id="script-review-title">{t('剧本审核报告')}</h2>
            <p className="script-review__note">
              {about ?? t('按故事逻辑、人物逻辑、开场、冲突、反转、情绪、台词七个方面读一遍剧本，每条问题落到具体的场次并给出改法。只是建议，不会改动剧本。')}
            </p>
          </div>
          <button ref={closeRef} type="button" className="script-review__close" aria-label={t('关闭剧本审核报告')} disabled={busy} onClick={onClose}><X aria-hidden="true" /></button>
        </header>
        {error && <div className="inline-error" role="alert">{error}</div>}
        {!shown && !error && <p className="script-review__note" role="status">{t('正在读取…')}</p>}
        {choices.length > 1 && (
          <div className="script-review__actions" role="group" aria-label={t('审核范围')}>
            {choices.map(item => (
              <button
                key={item.key || 'full'} type="button" className={item.key === focus ? 'is-primary' : ''} aria-pressed={item.key === focus} disabled={busy}
                onClick={() => { if (item.key !== focus) { setAsking(false); setShown(current => (current ? { ...current, report: null, stale: false, blocked: '' } : current)); setFocus(item.key); } }}
              >
                {item.label}
              </button>
            ))}
          </div>
        )}
        {shown && (
          <>
            <ul className="script-review__facts" aria-label={t('从剧本直接数出的概况')}>
              {shown.facts.map(item => <li key={item.key}>{item.label}<strong>{item.value}</strong></li>)}
            </ul>
            <div className="script-review__actions">
              {!asking && (
                <button type="button" className="is-primary" disabled={busy || !shown.model || Boolean(shown.blocked)} onClick={() => setAsking(true)}>
                  {busy ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : <ClipboardCheck size={15} aria-hidden="true" />}
                  {busy ? t('正在审读剧本…') : report ? t('重新生成审核报告') : t('生成审核报告')}
                </button>
              )}
              {asking && (
                <>
                  <span className="script-review__note">
                    {t('会用 {0} 调用 {1} 次文本模型（剧本分 {1} 段审读；回答格式不对会退回重答，每段最多 {2} 次）。确定吗？', [shown.model, calls, shown.attempts])}
                  </span>
                  <button type="button" className="is-primary" onClick={() => { void run(); }}>{t('确定生成')}</button>
                  <button type="button" onClick={() => setAsking(false)}>{t('先不用')}</button>
                </>
              )}
              {report && !asking && (
                <a href={`${API_BASE}${pathOf(taskId, focus, 'md')}`} download><Download size={15} aria-hidden="true" /> {t('下载报告（Markdown）')}</a>
              )}
              {!shown.model && <span className="script-review__note">{t('这个项目还没有选文本模型，先到模型设置里选一个')}</span>}
              {shown.blocked && <span className="script-review__warn" role="status">{shown.blocked}</span>}
            </div>
            {!report && !busy && <p className="script-review__note">{t('还没有生成过审核报告。')}</p>}
            {report && (
              <>
                <p className="script-review__note">
                  {t('生成于 {0}，模型 {1}，调用文本模型 {2} 次', [builtAt(report.built_at), report.model || '-', report.calls])}
                </p>
                {shown.stale && <p className="script-review__warn" role="status">{t('剧本在这份报告生成之后改过，下面的结论可能已经对不上，可以重新生成。')}</p>}
                <h3>{t('总体判断')}</h3>
                <p className="script-review__summary">{report.summary}</p>
                <h3>{t('各方面结论')}</h3>
                <ul className="script-review__dimensions">
                  {report.dimensions.map(item => (
                    <li key={item.key}>
                      <strong>{item.label}</strong>
                      <span className={`script-review__verdict is-${item.verdict}`}>{item.verdict_label}</span>
                      <span>{item.note}</span>
                    </li>
                  ))}
                </ul>
                <h3>{t('问题与改法（{0} 条）', [report.findings.length])}</h3>
                {report.findings.length === 0 && <p className="script-review__note">{t('没有指出需要修改的问题。')}</p>}
                <ol className="script-review__findings">
                  {report.findings.map((item, index) => (
                    <li key={`${item.scene}-${index}`} className={`is-${item.severity}`}>
                      <span className="script-review__where">{`${item.dimension_label} · ${item.severity_label} · ${item.where}`}</span>
                      {item.quote && <blockquote>{item.quote}</blockquote>}
                      <span><em>{t('问题')}</em>{item.issue}</span>
                      <span><em>{t('改法')}</em>{item.fix}</span>
                    </li>
                  ))}
                </ol>
                {report.quotes_dropped > 0 && (
                  <p className="script-review__note">{t('有 {0} 条引文在剧本里找不到原话，已经删掉引文、只留问题本身。', [report.quotes_dropped])}</p>
                )}
                {report.strengths.length > 0 && (
                  <>
                    <h3>{t('做得好的地方')}</h3>
                    <ul className="script-review__strengths">{report.strengths.map(text => <li key={text}>{text}</li>)}</ul>
                  </>
                )}
              </>
            )}
          </>
        )}
      </section>
    </div>
  );
}
