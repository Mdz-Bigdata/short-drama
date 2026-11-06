import { useEffect, useMemo, useState } from 'react';
import { History, RotateCcw, Search, Trash2, X } from 'lucide-react';

import { apiUrl } from '../../api/client';
import { t } from '../../i18n';
import { deleteRun, fetchNodeHistory, listVersions, restoreRun } from './canvasApi';
import { RUNNABLE_KINDS, roleChoices } from './canvasGraph';
import { toolOf } from './canvasTools';
import { kindLabel, nodeTitle, roleLabel, statusLabel } from './canvasLabels';
import type { Bookmark, CanvasDoc, CanvasEdge, CanvasNode, CanvasVersion, LatestRun, Medium, NodeHistory, NodePayload, NodeRun, ProjectShot, RunOptions } from './canvasTypes';

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function when(iso: string) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

// ---------------------------------------------------------------- outline

export function OutlinePanel({ nodes, selection, onJump }: { nodes: readonly CanvasNode[]; selection: ReadonlySet<string>; onJump: (id: string) => void }) {
  const [query, setQuery] = useState('');
  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const sorted = [...nodes].sort((a, b) => a.y - b.y || a.x - b.x || a.id.localeCompare(b.id));
    return needle ? sorted.filter(node => `${nodeTitle(node)} ${node.payload.prompt ?? ''} ${node.payload.text ?? ''}`.toLowerCase().includes(needle)) : sorted;
  }, [nodes, query]);
  const mainline = rows.filter(node => node.track === 'mainline');
  const free = rows.filter(node => node.track !== 'mainline');
  const list = (items: CanvasNode[]) => (
    <ul className="cn-outline">
      {items.map(node => (
        <li key={node.id}>
          <button type="button" className={selection.has(node.id) ? 'is-selected' : ''} onClick={() => onJump(node.id)}>
            <span className={`cn-dot cn-kind--${node.kind}`} aria-hidden="true" />
            <strong>{nodeTitle(node)}</strong>
            <small>{kindLabel(node.kind)}</small>
          </button>
        </li>
      ))}
    </ul>
  );
  return (
    <section className="cn-panel" aria-label={t('大纲')}>
      <label className="cn-search">
        <Search aria-hidden="true" />
        <input value={query} onChange={event => setQuery(event.target.value)} placeholder={t('搜索节点')} aria-label={t('搜索节点')} />
      </label>
      <p className="cn-count-line">{t('共 {0} 个节点', [rows.length])}</p>
      {mainline.length > 0 && <><h3>{t('已提交')}</h3>{list(mainline)}</>}
      {free.length > 0 && <><h3>{t('创作区')}</h3>{list(free)}</>}
    </section>
  );
}

// ---------------------------------------------------------------- canvas versions

export function VersionsPanel({ projectId, canvasId, version, onRestore }: {
  projectId: string; canvasId: string; version: number; onRestore: (version: number) => Promise<void>;
}) {
  const [versions, setVersions] = useState<CanvasVersion[] | null>(null);
  const [armed, setArmed] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    listVersions(projectId, canvasId, controller.signal)
      .then(setVersions)
      .catch(error => { if (!controller.signal.aborted) setProblem(messageOf(error, t('版本读取失败'))); });
    return () => controller.abort();
  }, [canvasId, projectId, version]);

  return (
    <section className="cn-panel" aria-label={t('版本')}>
      <p className="cn-hint">{t('恢复旧版本会生成一个新版本，当前内容仍在历史里。很旧的自动保存会被稀疏保留。')}</p>
      {problem && <p className="cn-error" role="alert">{problem}</p>}
      {versions === null && !problem && <p className="cn-hint">{t('读取中…')}</p>}
      {versions?.length === 0 && <p className="cn-hint">{t('还没有保存过。')}</p>}
      <ul className="cn-versions">
        {versions?.map(item => (
          <li key={item.version} className={item.version === version ? 'is-current' : ''}>
            <div>
              <strong>{t('第 {0} 版', [item.version])}{item.version === version ? ` · ${t('当前')}` : ''}</strong>
              <small>{when(item.created_at)} · {t('{0} 节点 / {1} 连线', [item.node_count, item.edge_count])}</small>
            </div>
            {item.version !== version && (armed === item.version ? (
              <button
                type="button" className="cn-button is-primary" disabled={busy}
                onClick={() => {
                  setBusy(true);
                  setProblem('');
                  void onRestore(item.version)
                    .catch(error => setProblem(messageOf(error, t('恢复失败'))))
                    .finally(() => { setBusy(false); setArmed(null); });
                }}
              >{t('确认恢复')}</button>
            ) : (
              <button type="button" className="cn-button" onClick={() => setArmed(item.version)}><RotateCcw aria-hidden="true" /> {t('恢复')}</button>
            ))}
          </li>
        ))}
      </ul>
    </section>
  );
}

// ---------------------------------------------------------------- one node

function RunThumb({ run }: { run: NodeRun }) {
  if (!run.output?.url) return <span className={`cn-thumb cn-thumb--empty is-${run.status}`}>{statusLabel(run.status)}</span>;
  const url = apiUrl(run.output.url);
  if (run.medium === 'image') return <img className="cn-thumb" src={url} alt="" loading="lazy" />;
  if (run.medium === 'video') return <video className="cn-thumb" src={url} muted preload="metadata" />;
  return <audio className="cn-thumb-audio" src={url} controls preload="none" />;
}

/** A node's generations. Append-only on the server: delete only hides one, restore only points back at one. */
export function HistoryStrip({ projectId, canvasId, nodeId, latest, onChanged }: {
  projectId: string; canvasId: string; nodeId: string; latest?: LatestRun; onChanged: () => void;
}) {
  const [history, setHistory] = useState<NodeHistory | null>(null);
  const [problem, setProblem] = useState('');
  const stamp = `${latest?.run_id ?? ''}:${latest?.status ?? ''}`;

  useEffect(() => {
    const controller = new AbortController();
    fetchNodeHistory(projectId, canvasId, nodeId, controller.signal)
      .then(setHistory)
      .catch(error => { if (!controller.signal.aborted) setProblem(messageOf(error, t('生成记录读取失败'))); });
    return () => controller.abort();
  }, [canvasId, nodeId, projectId, stamp]);

  const act = (work: Promise<NodeHistory>, failure: string) => {
    setProblem('');
    void work.then(next => { setHistory(next); onChanged(); }).catch(error => setProblem(messageOf(error, failure)));
  };

  return (
    <div className="cn-history">
      <h3><History aria-hidden="true" /> {t('生成记录')}</h3>
      {problem && <p className="cn-error" role="alert">{problem}</p>}
      {history?.runs.length === 0 && <p className="cn-hint">{t('还没有运行过。')}</p>}
      <ul>
        {history?.runs.map(run => (
          <li key={run.id} className={run.id === history.active_run_id ? 'is-active' : ''}>
            <RunThumb run={run} />
            <small>{when(run.created_at)}{run.id === history.active_run_id ? ` · ${t('当前')}` : ''}</small>
            {run.output?.remote && <small className="cn-warn">{t('只存了供应商链接，可能过期')}</small>}
            {run.error && <small className="cn-error" title={run.error}>{run.error}</small>}
            <div className="cn-history__actions">
              {run.status === 'done' && run.id !== history.active_run_id && (
                <button type="button" className="cn-button" onClick={() => act(restoreRun(projectId, canvasId, nodeId, run.id), t('恢复失败'))}>{t('恢复')}</button>
              )}
              {run.status !== 'queued' && run.status !== 'running' && (
                <button type="button" className="cn-button is-quiet" aria-label={t('删除这次生成')} onClick={() => act(deleteRun(projectId, canvasId, nodeId, run.id), t('删除失败'))}>
                  <Trash2 aria-hidden="true" />
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

const MEDIUM_OF: Partial<Record<CanvasNode['kind'], Medium>> = { image_gen: 'image', video_gen: 'video', audio_gen: 'audio' };

function ModelField({ node, options, onPatch }: { node: CanvasNode; options: RunOptions | null; onPatch: (payload: Partial<NodePayload>) => void }) {
  // A tool only has a model to choose when an image model does its work; the others use the project's.
  const medium = node.kind === 'tool' ? (toolOf(node)?.engine === 'image' ? 'image' : undefined) : MEDIUM_OF[node.kind];
  if (!medium || !options) return null;
  const fallback = options.models[medium];
  const models = [...new Set([...options.enabled[medium], ...(fallback ? [fallback] : [])])];
  return (
    <label className="cn-field">
      <span>{t('模型')}</span>
      <select
        value={node.payload.params?.model ?? ''}
        onChange={event => {
          const params = { ...node.payload.params };
          if (event.target.value) params.model = event.target.value;
          else delete params.model;
          onPatch({ params });
        }}
      >
        <option value="">{t('项目默认（{0}）', [fallback || t('未设置')])}</option>
        {models.map(model => <option key={model} value={model}>{model}</option>)}
      </select>
    </label>
  );
}

function BindingField({ node, shots, onPatch }: { node: CanvasNode; shots: ProjectShot[]; onPatch: (payload: Partial<NodePayload>) => void }) {
  const scenes = [...new Set(shots.map(item => item.scene_id))];
  const binding = node.payload.binding ?? {};
  const inScene = shots.filter(item => item.scene_id === binding.sceneId);
  return (
    <div className="cn-field">
      <span>{t('写回到')}</span>
      <div className="cn-row">
        <select aria-label={t('写回的场景')} value={binding.sceneId ?? ''} onChange={event => onPatch({ binding: { sceneId: event.target.value, shotId: null } })}>
          <option value="">{t('不绑定')}</option>
          {scenes.map(item => <option key={item} value={item}>{item}</option>)}
        </select>
        <select
          aria-label={t('写回的镜头')} value={binding.shotId ?? ''} disabled={!binding.sceneId}
          onChange={event => onPatch({ binding: { ...binding, shotId: event.target.value ? Number(event.target.value) : null } })}
        >
          <option value="">{t('整场')}</option>
          {inScene.map(item => <option key={item.shot_id} value={item.shot_id}>{t('第 {0} 镜', [item.shot_id])}</option>)}
        </select>
      </div>
    </div>
  );
}

export function InspectorPanel({ node, doc, options, shots, projectId, canvasId, latest, onPatch, onSetRole, onRemoveEdge, onHistoryChanged, onRun, onCommit }: {
  node: CanvasNode;
  doc: CanvasDoc;
  options: RunOptions | null;
  shots: ProjectShot[];
  projectId: string;
  canvasId: string;
  latest?: LatestRun;
  onPatch: (payload: Partial<NodePayload>, coalesce?: string) => void;
  onSetRole: (edgeId: string, role: string) => void;
  onRemoveEdge: (edgeId: string) => void;
  onHistoryChanged: () => void;
  onRun: () => void;
  onCommit: () => void;
}) {
  const incoming = doc.edges.filter(edge => edge.target === node.id);
  const sourceOf = (edge: CanvasEdge) => doc.nodes.find(item => item.id === edge.source);
  const params = node.payload.params ?? {};
  return (
    <section className="cn-panel" aria-label={t('属性')}>
      <h3>{kindLabel(node.kind)}</h3>
      <label className="cn-field">
        <span>{t('名称')}</span>
        <input value={node.payload.label ?? ''} maxLength={120} placeholder={kindLabel(node.kind)} onChange={event => onPatch({ label: event.target.value }, `label:${node.id}`)} />
      </label>
      <ModelField node={node} options={options} onPatch={onPatch} />
      {node.kind === 'video_gen' && (
        <label className="cn-field">
          <span>{t('时长（秒）')}</span>
          <input
            type="number" min={options?.video_durations[0]} max={options?.video_durations.at(-1)} step={1}
            value={params.durationSeconds ?? 5}
            onChange={event => onPatch({ params: { ...params, durationSeconds: Number(event.target.value) || 5 } }, `duration:${node.id}`)}
          />
        </label>
      )}
      {node.kind === 'video_gen' && (options?.camera_recipes?.length ?? 0) > 0 && (
        <div className="cn-row">
          <label className="cn-field">
            <span>{t('运镜模板')}</span>
            <select value={String(params.cameraRecipe ?? '')} onChange={event => onPatch({ params: { ...params, cameraRecipe: event.target.value } })}>
              <option value="">{t('不用模板')}</option>
              {options?.camera_recipes?.map(recipe => <option key={recipe.value} value={recipe.value} title={recipe.purpose}>{recipe.label}</option>)}
            </select>
          </label>
          {params.cameraRecipe ? (
            <label className="cn-field">
              <span>{t('力度')}</span>
              <select value={String(params.cameraIntensity ?? 'medium')} onChange={event => onPatch({ params: { ...params, cameraIntensity: event.target.value } })}>
                <option value="soft">{t('轻')}</option>
                <option value="medium">{t('中')}</option>
                <option value="strong">{t('强')}</option>
              </select>
            </label>
          ) : null}
        </div>
      )}
      {node.kind === 'image_gen' && (
        <label className="cn-field">
          <span>{t('尺寸')}</span>
          <input
            value={params.size ?? ''} placeholder="1024x1024" maxLength={16} pattern="[0-9]+x[0-9]+"
            onChange={event => onPatch({ params: { ...params, size: event.target.value } }, `size:${node.id}`)}
          />
        </label>
      )}
      {node.kind === 'audio_gen' && params.mode !== 'music' && params.mode !== 'sfx' && (
        <label className="cn-field">
          <span>{t('声音')}</span>
          <select value={params.gender ?? 'female'} onChange={event => onPatch({ params: { ...params, gender: event.target.value as 'male' | 'female' } })}>
            <option value="female">{t('女声')}</option>
            <option value="male">{t('男声')}</option>
          </select>
        </label>
      )}
      {incoming.length > 0 && (
        <div className="cn-field">
          <span>{t('输入')}</span>
          <ul className="cn-inputs">
            {incoming.map(edge => {
              const source = sourceOf(edge);
              const choices = source ? roleChoices(source, node) : [];
              return (
                <li key={edge.id}>
                  <strong>{source ? nodeTitle(source) : edge.source}</strong>
                  {choices.length > 0 ? (
                    <select aria-label={t('连接用途')} value={edge.payload.role ?? choices[0]} onChange={event => onSetRole(edge.id, event.target.value)}>
                      {choices.map(role => <option key={role} value={role}>{roleLabel(role)}</option>)}
                    </select>
                  ) : <small>{roleLabel(edge.payload.role)}</small>}
                  <button type="button" className="cn-button is-quiet" aria-label={t('断开这条连接')} onClick={() => onRemoveEdge(edge.id)}><X aria-hidden="true" /></button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {node.kind !== 'previz' && node.kind !== 'group' && node.kind !== 'note' && <BindingField node={node} shots={shots} onPatch={onPatch} />}
      <div className="cn-row cn-actions">
        {RUNNABLE_KINDS.has(node.kind) && <button type="button" className="cn-button is-primary" onClick={onRun}>{t('运行')}</button>}
        {node.kind !== 'group' && node.kind !== 'note' && <button type="button" className="cn-button" onClick={onCommit}>{t('提交到项目')}</button>}
      </div>
      {node.payload.committed?.artifact_id && (
        <p className="cn-hint">{t('已提交，影响 {0} 个镜头', [node.payload.committed.shots ?? 0])}</p>
      )}
      {RUNNABLE_KINDS.has(node.kind) && (
        <HistoryStrip projectId={projectId} canvasId={canvasId} nodeId={node.id} latest={latest} onChanged={onHistoryChanged} />
      )}
    </section>
  );
}

// ---------------------------------------------------------------- bookmarks

const SLOTS = [1, 2, 3, 4, 5, 6, 7, 8, 9];

export function BookmarkBar({ bookmarks, onJump, onSave, onClear }: {
  bookmarks: Bookmark[]; onJump: (slot: number) => void; onSave: (slot: number) => void; onClear: (slot: number) => void;
}) {
  const held = new Set(bookmarks.map(item => item.slot));
  return (
    <div className="cn-bookmarks" role="toolbar" aria-label={t('视图书签')}>
      {SLOTS.map(slot => (
        <button
          key={slot} type="button" className={held.has(slot) ? 'is-set' : ''}
          title={held.has(slot) ? t('跳到书签 {0}（按 {0}）；Shift 点击覆盖，Alt 点击清除', [slot]) : t('把当前视图存为书签 {0}（Shift+{0}）', [slot])}
          aria-label={held.has(slot) ? t('跳到书签 {0}', [slot]) : t('存为书签 {0}', [slot])}
          onClick={event => {
            if (event.altKey && held.has(slot)) onClear(slot);
            else if (event.shiftKey || !held.has(slot)) onSave(slot);
            else onJump(slot);
          }}
        >{slot}</button>
      ))}
    </div>
  );
}
