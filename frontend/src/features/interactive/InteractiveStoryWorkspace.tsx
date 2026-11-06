import { BarChart3, Flag, GitBranch, LayoutGrid, Package, Play, Plus, Save, Sparkles, Trash2, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { ApiError } from '../../api/client';
import { t, useLocale } from '../../i18n';
import {
  addChoice, addSegment, addVariable, autoLayout, connectEdge, deleteSegment, deleteVariable, ensureLayout,
  graphBounds, MAX_CHOICES, MAX_SEGMENTS, MAX_VARIABLES, starterGraph, updateSegment, updateVariable, variableUses,
} from './graphOps';
import { analyzeDraft, fetchStory, recordPlaytest, resetPlaytests, saveStory } from './interactiveApi';
import { SegmentInspector } from './SegmentInspector';
import { StoryAnalysisPanel } from './StoryAnalysisPanel';
import type { Playthrough } from './storyEngine';
import { StoryExportPanel } from './StoryExportPanel';
import { Field, NumberField, RowTools } from './storyFields';
import { StoryGraphCanvas } from './StoryGraphCanvas';
import { StoryPlanDialog } from './StoryPlanDialog';
import { StoryPlaytest } from './StoryPlaytest';
import type { PlaytestRun, PlaytestStats, Point, Selection, StoryAnalysis, StoryGraph, StoryIssue } from './storyTypes';
import './InteractiveStoryWorkspace.css';

type Tab = 'graph' | 'play' | 'analysis' | 'export';

function VariablesPanel({ graph, edit }: { graph: StoryGraph; edit: (change: (graph: StoryGraph) => StoryGraph) => void }) {
  const remove = (id: string) => {
    const uses = variableUses(graph, id);
    if (uses && !window.confirm(t('还有 {0} 处条件或效果用到这个变量；删除后它们会被标记为错误。确定删除吗？', [uses]))) return;
    edit(current => deleteVariable(current, id));
  };
  return (
    <section className="istory-section" aria-label={t('故事变量')}>
      <h3>{t('故事变量')}</h3>
      {!graph.variables.length && <p className="istory-hint">{t('好感度、分数、是否拿到某样东西……选项可以改变它们，条件可以读取它们。')}</p>}
      {graph.variables.map(variable => (
        <article className="istory-variable" key={variable.id} data-variable={variable.id}>
          <div className="istory-inline">
            <input aria-label={t('变量名称')} placeholder={variable.id} value={variable.label} maxLength={40} onChange={event => edit(current => updateVariable(current, variable.id, { label: event.target.value }))} />
            <RowTools onDelete={() => remove(variable.id)} deleteLabel={t('删除这个变量')} />
          </div>
          <div className="istory-inline">
            {variable.kind === 'flag' ? (
              <label className="istory-check">
                <input type="checkbox" checked={variable.initial === true} onChange={event => edit(current => updateVariable(current, variable.id, { initial: event.target.checked }))} />
                {t('初始为真')}
              </label>
            ) : (
              <>
                <Field label={t('初始')}><NumberField label={t('初始')} value={typeof variable.initial === 'number' ? variable.initial : 0} onChange={value => edit(current => updateVariable(current, variable.id, { initial: value ?? 0 }))} /></Field>
                <Field label={t('下限')}><NumberField label={t('下限')} allowEmpty value={variable.min} onChange={value => edit(current => updateVariable(current, variable.id, { min: value }))} /></Field>
                <Field label={t('上限')}><NumberField label={t('上限')} allowEmpty value={variable.max} onChange={value => edit(current => updateVariable(current, variable.id, { max: value }))} /></Field>
              </>
            )}
          </div>
        </article>
      ))}
      <div className="istory-inline">
        <button type="button" className="istory-link" disabled={graph.variables.length >= MAX_VARIABLES} onClick={() => edit(current => addVariable(current, 'number', t('数值')).graph)}><Plus aria-hidden="true" /> {t('数值变量')}</button>
        <button type="button" className="istory-link" disabled={graph.variables.length >= MAX_VARIABLES} onClick={() => edit(current => addVariable(current, 'flag', t('标记')).graph)}><Plus aria-hidden="true" /> {t('标记变量')}</button>
      </div>
    </section>
  );
}

/** The 互动剧 workspace: branching graph, playtest, analysis and export of one project's story. */
export function InteractiveStoryWorkspace({ taskId, onClose, onOpenCanvas }: { taskId: string; onClose: () => void; onOpenCanvas?: () => void }) {
  useLocale();
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [revision, setRevision] = useState(0);
  const [graph, setGraph] = useState<StoryGraph | null>(null);
  const [analysis, setAnalysis] = useState<StoryAnalysis | null>(null);
  const [analysisStale, setAnalysisStale] = useState(false);
  const [stats, setStats] = useState<PlaytestStats | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [conflict, setConflict] = useState(false);
  const [tab, setTab] = useState<Tab>('graph');
  const [selection, setSelection] = useState<Selection>(null);
  const [planOpen, setPlanOpen] = useState(false);
  const [fitKey, setFitKey] = useState(0);
  const [run, setRun] = useState<Playthrough | null>(null);
  const latest = useRef<StoryGraph | null>(null);
  useEffect(() => { latest.current = graph; }, [graph]);

  const adopt = useCallback((record: Awaited<ReturnType<typeof fetchStory>>) => {
    setRevision(record.revision);
    setGraph(record.graph ? ensureLayout(record.graph) : null);
    setAnalysis(record.analysis);
    setStats(record.stats);
    setDirty(false);
    setConflict(false);
    setSaveError('');
    setRun(null);
    setFitKey(key => key + 1);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      adopt(await fetchStory(taskId));
    } catch (failure) {
      setLoadError(failure instanceof Error ? failure.message : t('互动剧加载失败'));
    } finally {
      setLoading(false);
    }
  }, [adopt, taskId]);

  useEffect(() => {
    const handle = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(handle);
  }, [load]);

  const edit = useCallback((change: (current: StoryGraph) => StoryGraph) => {
    setGraph(current => (current ? change(current) : current));
    setDirty(true);
    setAnalysisStale(true);
  }, []);

  // Problems on the graph follow the edits; a draft the server would refuse just waits for the next keystroke.
  useEffect(() => {
    if (!graph || !analysisStale) return undefined;
    const controller = new AbortController();
    const handle = window.setTimeout(() => {
      analyzeDraft(taskId, graph, controller.signal)
        .then(result => {
          setAnalysis(result);
          setAnalysisStale(false);
        })
        .catch(() => undefined);
    }, 700);
    return () => {
      window.clearTimeout(handle);
      controller.abort();
    };
  }, [analysisStale, graph, taskId]);

  const persist = useCallback(async (sent: StoryGraph, base: number) => {
    setSaving(true);
    setSaveError('');
    try {
      const saved = await saveStory(taskId, base, sent);
      setRevision(saved.revision);
      setConflict(false);
      if (latest.current === sent) {
        // Keep the server's copy only when nothing was typed while it was on its way.
        setGraph(saved.graph ? ensureLayout(saved.graph) : sent);
        setDirty(false);
        setAnalysis(saved.analysis);
        setAnalysisStale(false);
      }
      setStats(saved.stats);
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 409) setConflict(true);
      else setSaveError(failure instanceof Error ? failure.message : t('保存失败'));
    } finally {
      setSaving(false);
    }
  }, [taskId]);

  const save = useCallback(() => {
    if (graph && !saving) void persist(graph, revision);
  }, [graph, persist, revision, saving]);

  const overwrite = useCallback(async () => {
    if (!graph || !window.confirm(t('用你的版本覆盖另一个页面保存的内容？'))) return;
    try {
      const current = await fetchStory(taskId);
      await persist(graph, current.revision);
    } catch (failure) {
      setSaveError(failure instanceof Error ? failure.message : t('保存失败'));
    }
  }, [graph, persist, taskId]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
        event.preventDefault();
        save();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [save]);

  const close = () => {
    if (dirty && !window.confirm(t('有未保存的修改，确定离开吗？'))) return;
    onClose();
  };

  const startBlank = () => {
    setGraph(starterGraph(t('开场'), t('结局'), t('继续')));
    setDirty(true);
    setAnalysisStale(true);
    setFitKey(key => key + 1);
  };

  const applyDraft = (draft: StoryGraph) => {
    const placed = ensureLayout(draft);
    setGraph(placed);
    latest.current = placed;
    setDirty(true);
    setSelection(null);
    setRun(null);
    setPlanOpen(false);
    setTab('graph');
    setFitKey(key => key + 1);
    // A draft the model was paid for should not depend on remembering to press save.
    void persist(placed, revision);
  };

  const selectedSegment = useMemo(() => {
    if (!graph || !selection) return null;
    const id = selection.kind === 'segment' ? selection.id : selection.segment;
    return graph.segments.find(item => item.id === id) ?? null;
  }, [graph, selection]);

  const addAt = (kind: 'scene' | 'ending', position?: Point) => {
    if (!graph || graph.segments.length >= MAX_SEGMENTS) return;
    const bounds = graphBounds(graph);
    const at = position ?? { x: bounds.right + 60, y: bounds.top };
    const made = addSegment(graph, kind, kind === 'ending' ? t('新结局') : t('新片段'), at);
    edit(() => made.graph);
    setSelection({ kind: 'segment', id: made.id });
  };

  const removeSelected = () => {
    if (!selection) return;
    if (selection.kind === 'edge') {
      // Disconnect only: a choice's text and rules are work, and the inspector is where it gets deleted.
      edit(current => connectEdge(current, selection.segment, selection.edge, null));
      return;
    }
    if (!window.confirm(t('确定删除这个片段吗？连到它的选项会变成未连接。'))) return;
    edit(current => deleteSegment(current, selection.id));
    setSelection(null);
  };

  const onConnect = (segmentId: string, edgeId: string | null, target: string) => {
    if (edgeId) {
      edit(current => connectEdge(current, segmentId, edgeId, target));
      setSelection({ kind: 'edge', segment: segmentId, edge: edgeId });
      return;
    }
    const segment = graph?.segments.find(item => item.id === segmentId);
    if (!graph || !segment || segment.choices.length >= MAX_CHOICES) return;
    const made = addChoice(graph, segmentId, t('新选项'), target);
    edit(() => made.graph);
    setSelection({ kind: 'edge', segment: segmentId, edge: made.id });
  };

  const onAddChoice = (segmentId: string) => {
    const segment = graph?.segments.find(item => item.id === segmentId);
    if (!graph || !segment || segment.choices.length >= MAX_CHOICES) return;
    const made = addChoice(graph, segmentId, t('新选项'));
    edit(() => made.graph);
    setSelection({ kind: 'edge', segment: segmentId, edge: made.id });
  };

  const onRecord = useCallback((finished: PlaytestRun) => {
    recordPlaytest(taskId, finished).then(setStats).catch(() => undefined);
  }, [taskId]);

  const pickIssue = (issue: StoryIssue) => {
    if (!issue.segment_id) return;
    const edge = issue.choice_id ?? issue.route_id;
    setSelection(edge ? { kind: 'edge', segment: issue.segment_id, edge } : { kind: 'segment', id: issue.segment_id });
    setTab('graph');
  };

  const tabs: Array<{ id: Tab; label: string; icon: typeof Play }> = [
    { id: 'graph', label: t('分支图'), icon: GitBranch },
    { id: 'play', label: t('试玩'), icon: Play },
    { id: 'analysis', label: t('分析'), icon: BarChart3 },
    { id: 'export', label: t('导出'), icon: Package },
  ];

  const issueCount = analysis ? analysis.errors + analysis.warnings : 0;
  return (
    <div className="istory" role="dialog" aria-modal="true" aria-label={t('互动剧')}>
      <header className="istory-top">
        <div className="istory-top__title">
          <span>{t('互动剧')}</span>
          {graph ? (
            <input aria-label={t('故事标题')} placeholder={t('未命名故事')} value={graph.title} maxLength={120} onChange={event => edit(current => ({ ...current, title: event.target.value }))} />
          ) : <h1>{t('互动剧')}</h1>}
        </div>
        {graph && (
          <nav className="istory-tabs" role="tablist" aria-label={t('互动剧视图')}>
            {tabs.map(item => (
              <button key={item.id} type="button" role="tab" aria-selected={tab === item.id} className={tab === item.id ? 'is-active' : ''} onClick={() => setTab(item.id)}>
                <item.icon aria-hidden="true" /> {item.label}
                {item.id === 'analysis' && issueCount > 0 && <em className={analysis?.errors ? 'is-error' : ''}>{issueCount}</em>}
              </button>
            ))}
          </nav>
        )}
        <div className="istory-top__actions">
          {graph && <span className={`istory-state ${dirty ? 'is-dirty' : ''}`} role="status">{saving ? t('正在保存…') : dirty ? t('有未保存的修改') : t('已保存')}</span>}
          <button type="button" className="secondary-action" onClick={() => setPlanOpen(true)}><Sparkles aria-hidden="true" /> {t('AI 规划')}</button>
          {graph && <button type="button" className="primary-action" disabled={saving || !dirty} onClick={save}><Save aria-hidden="true" /> {t('保存')}</button>}
          <button type="button" className="istory-icon" aria-label={t('关闭互动剧')} onClick={close}><X aria-hidden="true" /></button>
        </div>
      </header>

      {conflict && (
        <div className="istory-banner" role="alert">
          <span>{t('这个故事已在其他页面更新，你的修改还没有保存。')}</span>
          <button type="button" className="secondary-action" onClick={() => { void load(); }}>{t('载入最新版本（放弃我的修改）')}</button>
          <button type="button" className="secondary-action" onClick={() => { void overwrite(); }}>{t('用我的版本覆盖')}</button>
        </div>
      )}
      {saveError && <div className="istory-banner is-error" role="alert"><span>{saveError}</span></div>}

      <main className="istory-body">
        {loading && <p className="istory-hint istory-pad">{t('正在加载…')}</p>}
        {!loading && loadError && (
          <div className="istory-empty">
            <p className="istory-error" role="alert">{loadError}</p>
            <button type="button" className="secondary-action" onClick={() => { void load(); }}>{t('重试')}</button>
          </div>
        )}
        {!loading && !loadError && !graph && (
          <div className="istory-empty">
            <GitBranch aria-hidden="true" />
            <h2>{t('这个项目还没有互动剧')}</h2>
            <p>{t('描述一个故事想法，让 AI 起草分支；也可以从空白开始自己画。')}</p>
            <div className="istory-inline">
              <button type="button" className="primary-action" onClick={() => setPlanOpen(true)}><Sparkles aria-hidden="true" /> {t('AI 规划')}</button>
              <button type="button" className="secondary-action" onClick={startBlank}><Plus aria-hidden="true" /> {t('从空白开始')}</button>
            </div>
          </div>
        )}
        {!loading && graph && tab === 'graph' && (
          <div className="istory-editor">
            <aside className="istory-side" aria-label={t('故事设定')}>
              <Field label={t('故事简介')}>
                <textarea rows={3} maxLength={2000} value={graph.synopsis} onChange={event => edit(current => ({ ...current, synopsis: event.target.value }))} />
              </Field>
              {graph.outline.length > 0 && (
                <details className="istory-section">
                  <summary>{t('大纲')}（{graph.outline.length}）</summary>
                  <ol className="istory-outline">{graph.outline.map((beat, index) => <li key={index}>{beat}</li>)}</ol>
                </details>
              )}
              <VariablesPanel graph={graph} edit={edit} />
            </aside>
            <section className="istory-graph" aria-label={t('分支图')}>
              <div className="istory-graph__tools">
                <button type="button" className="secondary-action" disabled={graph.segments.length >= MAX_SEGMENTS} onClick={() => addAt('scene')}><Plus aria-hidden="true" /> {t('片段')}</button>
                <button type="button" className="secondary-action" disabled={graph.segments.length >= MAX_SEGMENTS} onClick={() => addAt('ending')}><Flag aria-hidden="true" /> {t('结局')}</button>
                <button type="button" className="secondary-action" onClick={() => { edit(autoLayout); setFitKey(key => key + 1); }}><LayoutGrid aria-hidden="true" /> {t('自动排布')}</button>
                {selection && <button type="button" className="secondary-action" onClick={removeSelected}><Trash2 aria-hidden="true" /> {selection.kind === 'edge' ? t('断开这条连线') : t('删除片段')}</button>}
                <small>{t('拖动片段调整位置；从选项右侧的圆点拖到另一个片段来连接；拖动空白处平移，滚轮缩放，双击空白处新建。')}</small>
              </div>
              <StoryGraphCanvas
                graph={graph}
                selection={selection}
                issues={analysis?.issues}
                fitKey={fitKey}
                onSelect={setSelection}
                onMoveNode={(id, position) => edit(current => updateSegment(current, id, { position }))}
                onConnect={onConnect}
                onAddChoice={onAddChoice}
                onAddAt={position => addAt('scene', position)}
                onDeleteSelection={removeSelected}
              />
            </section>
            <aside className="istory-side is-right" aria-label={t('片段编辑')}>
              {selectedSegment ? (
                <SegmentInspector
                  key={selectedSegment.id}
                  taskId={taskId}
                  onOpenCanvas={onOpenCanvas}
                  graph={graph}
                  segment={selectedSegment}
                  selection={selection}
                  edit={edit}
                  onDelete={() => {
                    if (window.confirm(t('确定删除这个片段吗？连到它的选项会变成未连接。'))) {
                      edit(current => deleteSegment(current, selectedSegment.id));
                      setSelection(null);
                    }
                  }}
                  onSelect={setSelection}
                />
              ) : <p className="istory-hint istory-pad">{t('选一个片段或连线来编辑。')}</p>}
            </aside>
          </div>
        )}
        {!loading && graph && tab === 'play' && (
          <StoryPlaytest graph={graph} dirty={dirty} run={run} onRunChange={setRun} onRecord={onRecord} />
        )}
        {!loading && graph && tab === 'analysis' && (
          <StoryAnalysisPanel
            graph={graph}
            analysis={analysis}
            stats={stats}
            stale={analysisStale}
            onPickIssue={pickIssue}
            onResetStats={() => {
              if (window.confirm(t('清空全部试玩统计？'))) resetPlaytests(taskId).then(setStats).catch(() => undefined);
            }}
          />
        )}
        {!loading && graph && tab === 'export' && <StoryExportPanel taskId={taskId} title={graph.title} dirty={dirty} revision={revision} />}
      </main>
      {planOpen && <StoryPlanDialog taskId={taskId} hasStory={Boolean(graph?.segments.length)} onApply={applyDraft} onClose={() => setPlanOpen(false)} />}
    </div>
  );
}
