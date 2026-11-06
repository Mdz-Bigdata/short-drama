import { Sparkles, X } from 'lucide-react';
import { useState } from 'react';

import { t } from '../../i18n';
import { planStory } from './interactiveApi';
import { issueText } from './issueText';
import type { PlanDraft, StoryGraph } from './storyTypes';

/** Brief in, a draft to look over out. Nothing replaces the story until the author says so. */
export function StoryPlanDialog({ taskId, hasStory, onApply, onClose }: {
  taskId: string;
  hasStory: boolean;
  onApply: (graph: StoryGraph) => void;
  onClose: () => void;
}) {
  const [brief, setBrief] = useState('');
  const [endings, setEndings] = useState(3);
  const [minutes, setMinutes] = useState(10);
  const [useProject, setUseProject] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [plan, setPlan] = useState<PlanDraft | null>(null);

  const generate = async () => {
    setBusy(true);
    setError('');
    try {
      setPlan(await planStory(taskId, { brief: brief.trim(), endings, minutes, useProject }));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : t('规划失败'));
    } finally {
      setBusy(false);
    }
  };

  const apply = () => {
    if (!plan) return;
    if (hasStory && !window.confirm(t('用这份草稿替换当前的故事？当前的片段和连线都会被覆盖。'))) return;
    onApply(plan.draft);
  };

  return (
    <div className="istory-dialog__backdrop">
      <div className="istory-dialog" role="dialog" aria-modal="true" aria-label={t('AI 规划故事')}>
        <header className="istory-inspector__head">
          <h2><Sparkles aria-hidden="true" /> {t('AI 规划故事')}</h2>
          <button type="button" className="istory-icon" aria-label={t('关闭')} onClick={onClose}><X aria-hidden="true" /></button>
        </header>
        <label className="istory-field">
          <span>{t('故事想法')}</span>
          <textarea
            rows={5}
            maxLength={4000}
            value={brief}
            placeholder={t('例如：女主收到一封十年前寄出的信，观众替她决定要不要回到那座小城，好感度决定最后和谁在一起。')}
            onChange={event => setBrief(event.target.value)}
          />
        </label>
        <div className="istory-inline">
          <label className="istory-field">
            <span>{t('结局数量')}</span>
            <input type="number" min={2} max={12} value={endings} onChange={event => setEndings(Math.max(2, Math.min(12, Number(event.target.value) || 2)))} />
          </label>
          <label className="istory-field">
            <span>{t('每条路线约几分钟')}</span>
            <input type="number" min={1} max={120} value={minutes} onChange={event => setMinutes(Math.max(1, Math.min(120, Number(event.target.value) || 1)))} />
          </label>
          <label className="istory-check">
            <input type="checkbox" checked={useProject} onChange={event => setUseProject(event.target.checked)} />
            {t('沿用本项目的剧名和角色')}
          </label>
        </div>
        <p className="istory-hint">{t('会调用一次项目的文本模型；不合格时最多自动重试两次。')}</p>
        {error && <p className="istory-error" role="alert">{error}</p>}
        <div className="istory-inline">
          <button type="button" className="primary-action" disabled={busy || brief.trim().length < 4} onClick={() => { void generate(); }}>
            <Sparkles aria-hidden="true" /> {busy ? t('正在规划…') : plan ? t('重新规划') : t('开始规划')}
          </button>
        </div>
        {plan && (
          <section className="istory-section" aria-label={t('规划结果')}>
            <h3>{plan.draft.title || t('未命名故事')}</h3>
            {plan.draft.synopsis && <p>{plan.draft.synopsis}</p>}
            {plan.draft.outline.length > 0 && <ol className="istory-outline">{plan.draft.outline.map((beat, index) => <li key={index}>{beat}</li>)}</ol>}
            <p className="istory-hint">
              {t('{0} 个片段，{1} 个结局，{2} 条完整路线，每条约 {3} ~ {4} 分钟。', [
                plan.draft.segments.length, plan.analysis.paths.coverage.endings_total, plan.analysis.paths.complete_paths,
                plan.analysis.paths.minutes.min ?? 0, plan.analysis.paths.minutes.max ?? 0,
              ])}
            </p>
            {plan.analysis.issues.length > 0 && (
              <ul className="istory-issues">
                {plan.analysis.issues.slice(0, 8).map((issue, index) => <li key={index} className={`is-${issue.severity}`}><span>{issueText(issue)}</span></li>)}
              </ul>
            )}
            <button type="button" className="primary-action" onClick={apply}>{t('采用这份草稿')}</button>
          </section>
        )}
      </div>
    </div>
  );
}
