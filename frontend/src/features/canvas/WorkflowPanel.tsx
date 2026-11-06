import { useCallback, useEffect, useMemo, useState } from 'react';
import { Loader2, Play, RotateCcw, Sparkles, Trash2, X } from 'lucide-react';

import { t } from '../../i18n';
import {
  applyWorkflow, deleteWorkflow, fetchWorkflow, listWorkflows, planWorkflow, updateWorkflow, type WorkflowPlan, type WorkflowStatus, type WorkflowSummary,
} from './canvasApi';
import { stepTakesWords, stepTypeLabel, withoutStep } from './workflowPlan';

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function stateLabel(state: string) {
  switch (state) {
    case 'draft': return t('草稿');
    case 'ready': case 'pending': return t('待运行');
    case 'queued': return t('排队中');
    case 'running': return t('运行中');
    case 'done': return t('完成');
    case 'failed': return t('失败');
    case 'skipped': return t('已跳过');
    case 'cancelled': return t('已取消');
    case 'waiting_input': return t('等你上传');
    case 'needs_input': return t('等你上传素材');
    case 'removed': return t('节点已删除');
    default: return state;
  }
}

interface Props {
  projectId: string;
  canvasId: string;
  /** Changes whenever a run moves on or the document is saved: what is shown is read again then. */
  refreshKey: string;
  /** Save what is on screen first; false means the canvas could not be saved. */
  flush: () => Promise<boolean>;
  currentVersion: () => number;
  /** The canvas has a new version from the server. */
  onApplied: () => Promise<unknown>;
  onRun: (nodeIds: string[]) => void;
  onJump: (nodeId: string) => void;
}

/** A brief becomes a plan to read and correct; the plan goes onto the canvas; the canvas runs it, and picks up where it failed. */
export function WorkflowPanel({ projectId, canvasId, refreshKey, flush, currentVersion, onApplied, onRun, onJump }: Props) {
  const [items, setItems] = useState<WorkflowSummary[]>([]);
  const [selected, setSelected] = useState('');
  const [workflow, setWorkflow] = useState<WorkflowStatus | null>(null);
  const [brief, setBrief] = useState('');
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');

  const refreshList = useCallback((signal?: AbortSignal) => listWorkflows(projectId, canvasId, signal)
    .then(data => setItems(data.workflows))
    .catch(error => { if (!signal?.aborted) setMessage(messageOf(error, t('工作流读取失败'))); }), [canvasId, projectId]);

  useEffect(() => {
    const controller = new AbortController();
    void refreshList(controller.signal);
    return () => controller.abort();
  }, [refreshList]);

  useEffect(() => {
    if (!selected) return undefined;
    const controller = new AbortController();
    fetchWorkflow(projectId, selected, controller.signal)
      .then(setWorkflow)
      .catch(error => { if (!controller.signal.aborted) setMessage(messageOf(error, t('工作流读取失败'))); });
    return () => controller.abort();
  }, [projectId, refreshKey, selected]);

  const shown = workflow?.id === selected ? workflow : null;

  const act = async (label: string, work: () => Promise<void>) => {
    setBusy(label);
    setMessage('');
    try {
      await work();
    } catch (error) {
      setMessage(messageOf(error, t('操作失败，请稍后重试。')));
    } finally {
      setBusy('');
    }
  };

  const plan = () => act('plan', async () => {
    const made = await planWorkflow(projectId, canvasId, brief.trim());
    setWorkflow(made);
    setSelected(made.id);
    setBrief('');
    await refreshList();
  });

  const savePlan = (next: WorkflowPlan) => act('save', async () => {
    if (shown) setWorkflow(await updateWorkflow(projectId, shown.id, next));
  });

  const apply = () => act('apply', async () => {
    if (!shown) return;
    if (!await flush()) { setMessage(t('画布还没保存成功，先解决保存问题再铺。')); return; }
    setWorkflow(await applyWorkflow(projectId, shown.id, currentVersion()));
    await onApplied();
    await refreshList();
  });

  const discard = () => act('delete', async () => {
    if (!shown) return;
    await deleteWorkflow(projectId, shown.id);
    setSelected('');
    setWorkflow(null);
    await refreshList();
  });

  const unfinished = useMemo(() => {
    const tally = { failed: 0, skipped: 0, cancelled: 0, waiting: 0, done: 0, active: 0 };
    shown?.steps.forEach(step => {
      if (step.state === 'failed') tally.failed += 1;
      if (step.state === 'skipped') tally.skipped += 1;
      if (step.state === 'cancelled') tally.cancelled += 1;
      if (step.state === 'waiting_input') tally.waiting += 1;
      if (step.state === 'done') tally.done += 1;
      if (step.state === 'running' || step.state === 'queued') tally.active += 1;
    });
    return tally;
  }, [shown]);

  const steps = shown?.plan.steps ?? [];
  const draft = shown?.state === 'draft';

  return (
    <section className="cn-panel cn-workflow" aria-label={t('工作流')}>
      <select className="cn-select" aria-label={t('选择工作流')} value={selected} onChange={event => { setSelected(event.target.value); setMessage(''); }}>
        <option value="">{t('新建工作流')}</option>
        {items.map(item => <option key={item.id} value={item.id}>{item.title}（{item.steps}）</option>)}
      </select>

      {!selected && (
        <>
          <textarea
            className="cn-textarea" aria-label={t('创作需求')} rows={6} maxLength={4000} value={brief}
            placeholder={t('想做什么？例如：雨夜追车的 15 秒预告，三个镜头，配紧张的音乐')} onChange={event => setBrief(event.target.value)}
          />
          <button type="button" className="cn-button is-primary" disabled={!brief.trim() || Boolean(busy)} onClick={() => { void plan(); }}>
            {busy === 'plan' ? <Loader2 className="cn-spin" aria-hidden="true" /> : <Sparkles aria-hidden="true" />} {busy === 'plan' ? t('规划中…') : t('规划流程')}
          </button>
          <p className="cn-hint">{t('调用一次文本模型，只出草稿，不改画布；确认前不会生成任何内容。')}</p>
        </>
      )}

      {shown && (
        <>
          <h3>{shown.plan.title} <small className={`cn-wfstate is-${shown.state}`}>{stateLabel(shown.state)}</small></h3>
          {shown.plan.summary && <p className="cn-hint">{shown.plan.summary}</p>}
          <ol className="cn-wfsteps">
            {steps.map(step => {
              const state = shown.steps.find(item => item.ref === step.ref);
              return (
                <li key={step.ref} className={`is-${state?.state ?? 'draft'}`}>
                  <div className="cn-row">
                    <strong>{step.label || step.ref}</strong>
                    <small>{stepTypeLabel(step)}</small>
                    {!draft && state && <small className={`cn-wfstate is-${state.state}`}>{stateLabel(state.state)}</small>}
                    {!draft && state?.node_id && state.state !== 'removed' && (
                      <button type="button" className="cn-button is-quiet" onClick={() => onJump(state.node_id)}>{t('定位')}</button>
                    )}
                    {draft && (
                      <button type="button" className="cn-button is-quiet" aria-label={t('去掉这一步：{0}', [step.label || step.ref])} disabled={Boolean(busy)} onClick={() => { void savePlan(withoutStep(shown.plan, step.ref)); }}>
                        <X aria-hidden="true" />
                      </button>
                    )}
                  </div>
                  {(step.inputs?.length ?? 0) > 0 && <small className="cn-hint">← {step.inputs?.map(input => steps.find(item => item.ref === input.source)?.label || input.source).join('、')}</small>}
                  {draft && stepTakesWords(step) && (
                    <textarea
                      key={`${shown.updated_at}:${step.ref}`} className="cn-textarea" rows={3} aria-label={t('{0} 的内容', [step.label || step.ref])}
                      defaultValue={step.kind === 'note' || step.kind === 'style_ref' ? step.text ?? '' : step.prompt ?? ''}
                      onBlur={event => {
                        const field = step.kind === 'note' || step.kind === 'style_ref' ? 'text' : 'prompt';
                        if (event.target.value === (step[field] ?? '')) return;
                        void savePlan({ ...shown.plan, steps: steps.map(item => (item.ref === step.ref ? { ...item, [field]: event.target.value } : item)) });
                      }}
                    />
                  )}
                  {draft && step.kind === 'media' && <small className="cn-hint">{t('铺到画布后由你上传')}</small>}
                  {state?.error && <p className="cn-error" role="status">{state.error}</p>}
                </li>
              );
            })}
          </ol>

          {shown.problems.length > 0 && (
            <ul className="cn-wfproblems" aria-label={t('流程问题')}>
              {shown.problems.map(problem => <li key={`${problem.ref}:${problem.code}:${problem.message}`} className="cn-error">{problem.message}</li>)}
            </ul>
          )}

          {draft && (
            <div className="cn-row">
              <button type="button" className="cn-button is-primary" disabled={!shown.can_apply || Boolean(busy)} onClick={() => { void apply(); }}>{t('铺到画布')}</button>
              <button type="button" className="cn-button is-quiet" disabled={Boolean(busy)} onClick={() => { void discard(); }}><Trash2 aria-hidden="true" /> {t('丢弃')}</button>
            </div>
          )}

          {shown.state === 'ready' && shown.runnable.length > 0 && (
            <button type="button" className="cn-button is-primary" onClick={() => onRun(shown.runnable)}><Play aria-hidden="true" /> {t('运行全部 {0} 步', [shown.runnable.length])}</button>
          )}
          {shown.state === 'needs_input' && <p className="cn-hint cn-warn" role="status">{t('还有 {0} 个素材等你上传，传好后再运行。', [unfinished.waiting])}</p>}
          {shown.state === 'needs_input' && shown.runnable.length > 0 && (
            <button type="button" className="cn-button" onClick={() => onRun(shown.runnable)}><Play aria-hidden="true" /> {t('检查并运行')}</button>
          )}
          {shown.state === 'failed' && (
            <div className="cn-wfrecover" role="status">
              <p>{t('失败 {0} 步，跳过 {1} 步，取消 {2} 步；已完成 {3} 步。', [unfinished.failed, unfinished.skipped, unfinished.cancelled, unfinished.done])}</p>
              <p className="cn-hint">{t('重试只跑没完成的步骤，已完成的结果会接着用，不会重复计费。')}</p>
              <button type="button" className="cn-button is-primary" disabled={!shown.runnable.length} onClick={() => onRun(shown.runnable)}><RotateCcw aria-hidden="true" /> {t('重试 {0} 步', [shown.runnable.length])}</button>
            </div>
          )}
          {shown.state === 'done' && <p className="cn-hint" role="status">{t('全部完成。选中节点可以提交到项目。')}</p>}
          {!draft && <button type="button" className="cn-button is-quiet" disabled={Boolean(busy)} onClick={() => { void discard(); }}>{t('从列表移除（节点保留）')}</button>}
        </>
      )}

      {busy === 'save' && <small className="cn-hint">{t('正在校验…')}</small>}
      {message && <p className="cn-error" role="alert">{message}</p>}
    </section>
  );
}
