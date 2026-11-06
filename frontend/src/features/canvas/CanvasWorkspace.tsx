import { forwardRef, lazy, Suspense, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import {
  AudioLines, Boxes, Clapperboard, Copy, Film, Globe2, HelpCircle, ImageIcon, ListTree, Maximize, Moon, Palette, Pencil, Play, Plus, Redo2, Send, SlidersHorizontal,
  StickyNote, Sun, Trash2, Undo2, Upload, Waypoints, X, History, type LucideIcon, Workflow, Wrench,
} from 'lucide-react';

import { apiUrl } from '../../api/client';
import { t } from '../../i18n';
import {
  assessRun, cancelRun, commitNodes, createBoard, deleteBoard, fetchRunOptions, fetchShots, openTaskCanvas, patchBoard, restoreVersion, saveCanvas, startRun, uploadMedia,
} from './canvasApi';
import { CanvasContext, type CanvasActions } from './canvasContext';
import {
  DEFAULT_SIZES, RUNNABLE_KINDS, connect, copySelection, deleteSelection, effectiveOutput, groupNodes, makeId, moveNodes, movingIds, newNode, pasteClip, patchNode, ungroup, upstreamImageUrl, type CanvasClip,
} from './canvasGraph';
import { boundsOf } from './canvasGeometry';
import { kindLabel, refusalMessage } from './canvasLabels';
import { WorkflowPanel } from './WorkflowPanel';
import { CommitDialog, RunDialog } from './CanvasDialogs';
import { CanvasMinimap } from './CanvasMinimap';
import { CanvasNodeCard, NodeShell } from './CanvasNodeCard';
import { BookmarkBar, InspectorPanel, OutlinePanel, VersionsPanel } from './CanvasPanels';
import { CanvasSurface, type NodeRenderProps, type SurfaceHandle } from './CanvasSurface';
import type { Bookmark, CanvasBoard, CanvasDoc, LatestRun, NodeKind, NodeOutput, NodePayload, ProjectShot, RunAssessment, RunOptions, TierConfirmation, Viewport } from './canvasTypes';
import { useCanvasDocument, type SaveStatus } from './useCanvasDocument';
import { useCanvasRuns } from './useCanvasRuns';
import './CanvasWorkspace.css';

const DirectorDesk = lazy(() => import('../directorDesk/DirectorDesk').then(module => ({ default: module.DirectorDesk })));

const BEAT_GAP = 40;

const PALETTE: Array<{ kind: NodeKind; icon: LucideIcon }> = [
  { kind: 'media', icon: Upload }, { kind: 'note', icon: StickyNote }, { kind: 'image_gen', icon: ImageIcon }, { kind: 'video_gen', icon: Film },
  { kind: 'audio_gen', icon: AudioLines }, { kind: 'video_compose', icon: Clapperboard }, { kind: 'style_ref', icon: Palette }, { kind: 'panorama', icon: Globe2 },
  { kind: 'previz', icon: Waypoints }, { kind: 'tool', icon: Wrench },
];

function shortcuts(): Array<[string, string]> {
  return [
    ['Ctrl / ⌘ + Z', t('撤销')], ['Ctrl / ⌘ + Shift + Z', t('重做')], ['Ctrl / ⌘ + C / X / V', t('复制 / 剪切 / 粘贴')], ['Ctrl / ⌘ + D', t('就地复制')],
    ['Ctrl / ⌘ + A', t('全选')], ['Ctrl / ⌘ + G', t('成组')], ['Ctrl / ⌘ + Shift + G', t('解组')], ['Delete', t('删除所选')],
    [t('Shift + 点击或框选'), t('追加到所选')], [t('空格 + 拖动'), t('平移（中键也可以）')], [t('滚轮'), t('以光标为中心缩放')], [t('Alt + 拖动'), t('拖动时不吸附')],
    ['F', t('显示全部（有选中时显示所选）')], ['1 … 9', t('跳到视图书签')], ['Shift + 1 … 9', t('保存视图书签')], [t('方向键'), t('微调所选（Shift 走 10 格）')],
    ['Ctrl / ⌘ + S', t('立即保存')], ['Esc', t('取消当前操作，再按取消选择')],
  ];
}

const PASTE_OFFSET = 40;
// In memory and outside any board, so a copy can be pasted onto another canvas.
let clipboard: CanvasClip | null = null;

function typing(target: EventTarget | null) {
  return target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));
}

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function storedView(canvasId: string): Viewport | null {
  try {
    const raw = window.localStorage.getItem(`canvas.view.${canvasId}`);
    const view = raw ? JSON.parse(raw) as Viewport : null;
    return view && Number.isFinite(view.x) && Number.isFinite(view.y) && view.zoom > 0 ? view : null;
  } catch {
    return null;
  }
}

function rememberView(canvasId: string, view: Viewport) {
  try {
    window.localStorage.setItem(`canvas.view.${canvasId}`, JSON.stringify(view));
  } catch {
    // Remembering where you were looking is a convenience; private mode can do without.
  }
}

function saveLabel(status: SaveStatus) {
  switch (status) {
    case 'loading': return t('读取中…');
    case 'dirty': return t('有未保存的修改');
    case 'saving': return t('保存中…');
    case 'saved': return t('已保存');
    case 'error': return t('保存失败，稍后重试');
    case 'conflict': return t('版本冲突，未保存');
    case 'idle': return '';
  }
}

function ZoomReadout({ surface }: { surface: React.RefObject<SurfaceHandle | null> }) {
  const label = useRef<HTMLSpanElement>(null);
  useEffect(() => surface.current?.subscribe(view => {
    if (label.current) label.current.textContent = `${Math.round(view.zoom * 100)}%`;
  }), [surface]);
  return <span ref={label} className="cn-zoom" aria-live="off">100%</span>;
}

interface EditorHandle {
  flush: () => Promise<boolean>;
}

interface EditorProps {
  taskId: string;
  projectId: string;
  board: CanvasBoard;
  options: RunOptions | null;
  shots: ProjectShot[];
  onBookmarks: (bookmarks: Bookmark[]) => void;
  onForked: (board: CanvasBoard) => void;
  onVersion: (version: number) => void;
}

/** One canvas. Remounted per board, so nothing of one canvas's undo stack or selection can reach another. */
const CanvasEditor = forwardRef<EditorHandle, EditorProps>(function CanvasEditor({ taskId, projectId, board, options, shots, onBookmarks, onForked, onVersion }, handle) {
  const canvasId = board.id;
  const document_ = useCanvasDocument(projectId, canvasId);
  const { doc, status, version, edit, flush, adopt, reload, currentDoc, currentVersion, hasUnsaved, isLoaded } = document_;
  const surface = useRef<SurfaceHandle | null>(null);
  const [selection, setSelection] = useState<ReadonlySet<string>>(() => new Set());
  const [edgeSelection, setEdgeSelection] = useState<ReadonlySet<string>>(() => new Set());
  const [notice, setNotice] = useState('');
  const [panel, setPanel] = useState<'inspector' | 'outline' | 'versions' | 'workflow' | null>('inspector');
  const [help, setHelp] = useState(false);
  const [assessment, setAssessment] = useState<{ value: RunAssessment; nodeIds: string[]; operationId: string } | null>(null);
  const [commit, setCommit] = useState<string[] | null>(null);
  const [desk, setDesk] = useState<{ sceneId: string; shotId?: number; reference?: { url: string } } | null>(null);
  const [deskToken, setDeskToken] = useState(0);
  const [fitted, setFitted] = useState(false);

  const onRemoteVersion = useCallback((remote: number) => {
    // Until the document is in, its version is still 0: the first poll to come back is not news from anywhere.
    if (!isLoaded() || remote <= currentVersion() || hasUnsaved()) return;
    // Someone else wrote (another window, the assistant). With nothing of ours pending, just catch up.
    void reload().then(() => setNotice(t('画布已在别处更新，已载入最新版本。')));
  }, [currentVersion, hasUnsaved, isLoaded, reload]);

  const runs = useCanvasRuns(projectId, canvasId, onRemoteVersion);
  const outputsRef = useRef<Readonly<Record<string, NodeOutput>>>(runs.data.outputs);
  useEffect(() => { outputsRef.current = runs.data.outputs; }, [runs.data.outputs]);
  useEffect(() => { onVersion(version); }, [onVersion, version]);

  useImperativeHandle(handle, () => ({ flush }), [flush]);

  const say = useCallback((message: string) => setNotice(message), []);

  const select = useCallback((nodes: ReadonlySet<string>, edges: ReadonlySet<string>) => {
    setSelection(nodes);
    setEdgeSelection(edges);
  }, []);

  // First look at a canvas: where you left it, or else the whole thing.
  useEffect(() => {
    if (fitted || status === 'loading') return;
    const saved = storedView(canvasId);
    if (saved) surface.current?.setView(saved);
    else surface.current?.fit();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- runs once, the first time the document is there
    setFitted(true);
  }, [canvasId, fitted, status]);

  const addNode = useCallback((kind: NodeKind, at?: { x: number; y: number }, payload?: NodePayload) => {
    const point = at ?? surface.current?.centre() ?? { x: 0, y: 0 };
    const node = newNode(kind, Math.round(point.x), Math.round(point.y), payload);
    edit(current => ({ ...current, nodes: kind === 'group' ? [node, ...current.nodes] : [...current.nodes, node] }));
    setSelection(new Set([node.id]));
    setEdgeSelection(new Set());
    return node.id;
  }, [edit]);

  const runNodes = useCallback(async (nodeIds: string[]) => {
    const runnable = nodeIds.filter(id => RUNNABLE_KINDS.has(currentDoc().nodes.find(node => node.id === id)?.kind as NodeKind));
    if (!runnable.length) {
      say(t('所选节点没有可以运行的。'));
      return;
    }
    if (!await flush()) {
      say(t('画布还没保存成功，先解决保存问题再运行。'));
      return;
    }
    try {
      const value = await assessRun(projectId, canvasId, runnable);
      const free = value.decision === 'admitted' && value.estimate.paid_items === 0;
      if (!free) {
        setAssessment({ value, nodeIds: runnable, operationId: makeId('op') });
        return;
      }
      const outcome = await startRun(projectId, canvasId, { nodeIds: runnable, expectedVersion: currentVersion(), operationId: makeId('op'), confirm: false, confirmed: [] });
      if (outcome.status === 'started') {
        runs.kick();
      } else if (outcome.assessment) {
        setAssessment({ value: outcome.assessment, nodeIds: runnable, operationId: makeId('op') });
      }
    } catch (error) {
      say(messageOf(error, t('运行失败')));
    }
  }, [canvasId, currentDoc, currentVersion, flush, projectId, runs, say]);

  const confirmRun = useCallback(async (confirmations: TierConfirmation[]) => {
    if (!assessment) throw new Error(t('运行失败'));
    const outcome = await startRun(projectId, canvasId, {
      nodeIds: assessment.nodeIds, expectedVersion: currentVersion(), operationId: assessment.operationId, confirm: true, confirmed: confirmations,
    });
    if (outcome.status === 'started') runs.kick();
    return outcome;
  }, [assessment, canvasId, currentVersion, projectId, runs]);

  const upload = useCallback((nodeId: string, file: File) => {
    say(t('上传中…'));
    uploadMedia(projectId, file).then(result => {
      const node = currentDoc().nodes.find(item => item.id === nodeId);
      if (!node) return;
      if ((node.kind === 'style_ref' || node.kind === 'panorama') && result.medium !== 'image') {
        say(t('这个节点只接受图片。'));
        return;
      }
      const output: NodeOutput = { medium: result.medium, url: result.url, filename: result.filename, provenance: result.provenance };
      edit(current => patchNode(current, nodeId, {}, { output, ...(node.kind === 'media' ? { label: node.payload.label || result.filename } : {}) }));
      say('');
    }).catch(error => say(messageOf(error, t('上传失败'))));
  }, [currentDoc, edit, projectId, say]);

  const actions = useMemo<CanvasActions>(() => ({
    taskId,
    options,
    shots,
    deskToken,
    patch: (nodeId, payload, coalesce) => edit(current => patchNode(current, nodeId, {}, payload), coalesce ?? null),
    run: nodeIds => { void runNodes(nodeIds); },
    cancel: (latest: LatestRun) => {
      cancelRun(projectId, latest.batch_id, latest.run_id).then(() => runs.kick()).catch(error => say(messageOf(error, t('取消失败'))));
    },
    upload,
    layOutBeats: (sourceId, beats) => {
      // One undo: a plan arrives as a whole row or not at all.
      edit(current => {
        const source = current.nodes.find(node => node.id === sourceId);
        if (!source) return current;
        const [width] = DEFAULT_SIZES.image_gen;
        const made = beats.map((beat, index) => newNode('image_gen', source.x + source.width + BEAT_GAP + index * (width + BEAT_GAP), source.y, { label: beat.title, prompt: beat.prompt }));
        return { ...current, nodes: [...current.nodes, ...made] };
      });
    },
    openDesk: nodeId => {
      const current = currentDoc();
      const node = current.nodes.find(item => item.id === nodeId);
      if (!node?.payload.sceneId) return;
      const url = upstreamImageUrl(node, current, outputsRef.current);
      setDesk({ sceneId: node.payload.sceneId, shotId: node.payload.shotId ?? undefined, reference: url ? { url: apiUrl(url) } : undefined });
    },
  }), [currentDoc, deskToken, edit, options, projectId, runNodes, runs, say, shots, taskId, upload]);

  const inputCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const edge of doc.edges) counts.set(edge.target, (counts.get(edge.target) ?? 0) + 1);
    return counts;
  }, [doc.edges]);

  const { outputs, latest, history_counts: historyCounts } = runs.data;

  const renderNode = useCallback(({ node, selected, shell, dropState }: NodeRenderProps) => {
    if (shell) return <NodeShell node={node} selected={selected} />;
    return (
      <CanvasNodeCard
        node={node} selected={selected} dropState={dropState} output={effectiveOutput(node, doc, outputs)} latest={latest[node.id]}
        historyCount={historyCounts[node.id] ?? 0} inputs={inputCounts.get(node.id) ?? 0}
        reference={node.kind === 'previz' ? upstreamImageUrl(node, doc, outputs) : null}
      />
    );
  }, [doc, historyCounts, inputCounts, latest, outputs]);

  const onMove = useCallback((ids: ReadonlySet<string>, dx: number, dy: number) => {
    edit(current => moveNodes(current, ids, Math.round(dx), Math.round(dy)));
  }, [edit]);

  const onResize = useCallback((id: string, width: number, height: number) => {
    edit(current => patchNode(current, id, { width: Math.round(width), height: Math.round(height) }));
  }, [edit]);

  const onConnect = useCallback((source: string, target: string) => {
    const result = connect(currentDoc(), source, target);
    if (result.ok) edit(current => ({ ...current, edges: [...current.edges, result.edge] }));
    else say(refusalMessage(result.reason));
  }, [currentDoc, edit, say]);

  const canConnect = useCallback((source: string, target: string) => connect(currentDoc(), source, target).ok, [currentDoc]);

  const onDropFiles = useCallback((files: File[], world: { x: number; y: number }) => {
    files.slice(0, 20).forEach((file, index) => {
      const id = addNode('media', { x: world.x + index * PASTE_OFFSET, y: world.y + index * PASTE_OFFSET }, { label: file.name });
      upload(id, file);
    });
  }, [addNode, upload]);

  const copy = useCallback(() => {
    const clip = copySelection(currentDoc(), selection, outputsRef.current);
    if (clip) clipboard = clip;
    return Boolean(clip);
  }, [currentDoc, selection]);

  const paste = useCallback((at?: { x: number; y: number } | null) => {
    const clip = clipboard;
    if (!clip) return;
    const box = boundsOf(clip.nodes);
    if (!box) return;
    const target = at ?? { x: box.x + PASTE_OFFSET, y: box.y + PASTE_OFFSET };
    const placed = pasteClip(currentDoc(), clip, Math.round(target.x - box.x), Math.round(target.y - box.y));
    edit(() => placed.doc);
    setSelection(new Set(placed.ids));
    setEdgeSelection(new Set());
  }, [currentDoc, edit]);

  const remove = useCallback(() => {
    if (!selection.size && !edgeSelection.size) return;
    edit(current => deleteSelection(current, selection, edgeSelection));
    setSelection(new Set());
    setEdgeSelection(new Set());
  }, [edgeSelection, edit, selection]);

  const group = useCallback(() => {
    const made = groupNodes(currentDoc(), selection, t('分组'));
    if (!made) {
      say(t('至少选中两个节点才能成组。'));
      return;
    }
    edit(() => made.doc);
    setSelection(new Set([made.groupId]));
  }, [currentDoc, edit, say, selection]);

  const saveBookmark = useCallback((slot: number) => {
    const view = surface.current?.getView();
    if (!view) return;
    const next = [...board.bookmarks.filter(item => item.slot !== slot), { slot, x: view.x, y: view.y, zoom: view.zoom }];
    onBookmarks(next);
    say(t('已保存书签 {0}。', [slot]));
  }, [board.bookmarks, onBookmarks, say]);

  const jumpBookmark = useCallback((slot: number) => {
    const mark = board.bookmarks.find(item => item.slot === slot);
    if (mark) surface.current?.setView({ x: mark.x, y: mark.y, zoom: mark.zoom });
  }, [board.bookmarks]);

  const modal = Boolean(assessment || commit || desk);

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      // The desk and the dialogs have their own keys; Delete there must not reach the canvas underneath.
      if (modal || event.defaultPrevented) return;
      const mod = event.ctrlKey || event.metaKey;
      const letter = event.key.toLowerCase();
      if (mod && letter === 's') {
        event.preventDefault();
        void flush();
        return;
      }
      if (typing(event.target)) return;
      if (event.target instanceof Element && event.target !== document.body && !event.target.closest('.canvas-workspace')) return;
      if (mod) {
        if (letter === 'z') {
          event.preventDefault();
          if (event.shiftKey) document_.redo();
          else document_.undo();
        } else if (letter === 'y') {
          event.preventDefault();
          document_.redo();
        } else if (letter === 'c') {
          if (copy()) event.preventDefault();
        } else if (letter === 'x') {
          if (copy()) {
            event.preventDefault();
            remove();
          }
        } else if (letter === 'v') {
          event.preventDefault();
          paste(surface.current?.pointer());
        } else if (letter === 'd') {
          event.preventDefault();
          if (copy()) paste();
        } else if (letter === 'a') {
          event.preventDefault();
          setSelection(new Set(currentDoc().nodes.map(node => node.id)));
        } else if (letter === 'g') {
          event.preventDefault();
          if (event.shiftKey) {
            const groups = new Set([...selection].filter(id => currentDoc().nodes.find(node => node.id === id)?.kind === 'group'));
            if (groups.size) {
              edit(current => ungroup(current, groups));
              setSelection(new Set());
            }
          } else {
            group();
          }
        }
        return;
      }
      if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault();
        remove();
      } else if (event.key === 'Escape') {
        setSelection(new Set());
        setEdgeSelection(new Set());
      } else if (letter === 'f') {
        surface.current?.fit(selection.size ? [...selection] : undefined);
      } else if (event.key === '?') {
        setHelp(value => !value);
      } else if (event.key.startsWith('Arrow') && selection.size) {
        event.preventDefault();
        const step = event.shiftKey ? 10 : 1;
        const dx = event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0;
        const dy = event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : 0;
        edit(current => moveNodes(current, movingIds(current.nodes, selection), dx, dy), `nudge:${[...selection].join()}`);
      } else if (event.code.startsWith('Digit') && event.code !== 'Digit0') {
        // By code, not key: Shift+1 is "!" on the event's key.
        const slot = Number(event.code.slice(5));
        event.preventDefault();
        if (event.shiftKey) saveBookmark(slot);
        else jumpBookmark(slot);
      }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [copy, currentDoc, document_, edit, flush, group, jumpBookmark, modal, paste, remove, saveBookmark, selection]);

  const onlySelected = selection.size === 1 ? doc.nodes.find(node => selection.has(node.id)) : undefined;

  const restore = useCallback(async (older: number) => {
    if (!await flush()) throw new Error(t('画布还没保存成功，先解决保存问题。'));
    const record = await restoreVersion(projectId, canvasId, older, currentVersion());
    adopt(record);
    setSelection(new Set());
    say(t('已恢复到第 {0} 版（新版本 {1}）。', [older, record.version]));
  }, [adopt, canvasId, currentVersion, flush, projectId, say]);

  const openCommit = useCallback(async (nodeIds: string[]) => {
    if (!nodeIds.length) return;
    if (!await flush()) {
      say(t('画布还没保存成功，先解决保存问题再提交。'));
      return;
    }
    setCommit(nodeIds);
  }, [flush, say]);

  const sendCommit = useCallback(async (nodeIds: string[]) => {
    const result = await commitNodes(projectId, canvasId, nodeIds, currentVersion());
    if (result.canvas) adopt(result.canvas);
    return result;
  }, [adopt, canvasId, currentVersion, projectId]);

  const forkConflict = useCallback(async () => {
    try {
      const mine: CanvasDoc = currentDoc();
      const created = await createBoard(projectId, t('{0}（我的版本）', [board.title]));
      const saved = await saveCanvas(projectId, created.id, 0, mine);
      onForked({ ...created, version: saved.version });
    } catch (error) {
      say(messageOf(error, t('另存失败')));
    }
  }, [board.title, currentDoc, onForked, projectId, say]);

  const closeAssessment = useCallback(() => setAssessment(null), []);
  const closeCommit = useCallback(() => setCommit(null), []);
  const closeDesk = useCallback(() => {
    setDesk(null);
    setDeskToken(value => value + 1);
  }, []);

  const selectedRunnable = [...selection].filter(id => RUNNABLE_KINDS.has(doc.nodes.find(node => node.id === id)?.kind as NodeKind));

  return (
    <CanvasContext.Provider value={actions}>
      <div className="cn-editor">
        <div className="cn-rail" role="toolbar" aria-label={t('添加节点')}>
          {PALETTE.map(item => (
            <button key={item.kind} type="button" onClick={() => addNode(item.kind)} title={t('添加：{0}', [kindLabel(item.kind)])} aria-label={t('添加：{0}', [kindLabel(item.kind)])}>
              <item.icon aria-hidden="true" />
              <span>{kindLabel(item.kind)}</span>
            </button>
          ))}
        </div>

        <div className="cn-stage">
          <div className="cn-toolbar" role="toolbar" aria-label={t('画布工具')}>
            <button type="button" className="cn-icon" onClick={document_.undo} disabled={!document_.canUndo} aria-label={t('撤销')} title={t('撤销')}><Undo2 aria-hidden="true" /></button>
            <button type="button" className="cn-icon" onClick={document_.redo} disabled={!document_.canRedo} aria-label={t('重做')} title={t('重做')}><Redo2 aria-hidden="true" /></button>
            <button type="button" className="cn-icon" onClick={() => surface.current?.fit()} aria-label={t('显示全部')} title={t('显示全部')}><Maximize aria-hidden="true" /></button>
            <ZoomReadout surface={surface} />
            <span className="cn-sep" />
            <button type="button" className="cn-icon" disabled={!selection.size} onClick={() => { if (copy()) paste(); }} aria-label={t('就地复制')} title={t('就地复制')}><Copy aria-hidden="true" /></button>
            <button type="button" className="cn-icon" disabled={selection.size < 2} onClick={group} aria-label={t('成组')} title={t('成组')}><Boxes aria-hidden="true" /></button>
            <button type="button" className="cn-icon" disabled={!selection.size && !edgeSelection.size} onClick={remove} aria-label={t('删除所选')} title={t('删除所选')}><Trash2 aria-hidden="true" /></button>
            <span className="cn-sep" />
            <button type="button" className="cn-button is-primary" disabled={!selectedRunnable.length} onClick={() => { void runNodes(selectedRunnable); }}>
              <Play aria-hidden="true" /> {t('运行所选')}{selectedRunnable.length ? ` (${selectedRunnable.length})` : ''}
            </button>
            <button type="button" className="cn-button" disabled={!selection.size} onClick={() => { void openCommit([...selection]); }}>
              <Send aria-hidden="true" /> {t('提交所选')}{selection.size ? ` (${selection.size})` : ''}
            </button>
            {runs.data.running > 0 && <span className="cn-status is-running">{t('{0} 个运行中', [runs.data.running])}</span>}
            <span className={`cn-save is-${status}`} role="status" title={status === 'error' ? document_.saveError : undefined}>
              {saveLabel(status)}{status === 'saved' && version ? ` · ${t('第 {0} 版', [version])}` : ''}
              {status === 'error' && document_.saveError ? `：${document_.saveError}` : ''}
            </span>
            {status === 'error' && !document_.loadError && <button type="button" className="cn-button" onClick={() => { void flush(); }}>{t('重试')}</button>}
          </div>

          {status === 'conflict' && (
            <div className="cn-banner" role="alert">
              <strong>{t('这张画布已在别处被修改（其他窗口或助手）。')}</strong>
              <span>{t('你最近的修改还没保存，也没有覆盖任何内容。')}</span>
              <button type="button" className="cn-button" onClick={() => { void reload(); }}>{t('载入最新版本（放弃我的修改）')}</button>
              <button type="button" className="cn-button is-primary" onClick={() => { void forkConflict(); }}>{t('把我的版本另存为新画布')}</button>
            </div>
          )}
          {document_.loadError && (
            <div className="cn-banner" role="alert">
              <strong>{document_.loadError}</strong>
              <button type="button" className="cn-button" onClick={() => { void reload(); }}>{t('重试')}</button>
            </div>
          )}

          <CanvasSurface
            ref={surface}
            nodes={doc.nodes}
            edges={doc.edges}
            selection={selection}
            edgeSelection={edgeSelection}
            initialView={null}
            renderNode={renderNode}
            onSelect={select}
            onMove={onMove}
            onResize={onResize}
            onConnect={onConnect}
            canConnect={canConnect}
            onViewSettled={view => rememberView(canvasId, view)}
            onDropFiles={onDropFiles}
          />

          <div className="cn-overlay-bottom">
            <CanvasMinimap nodes={doc.nodes} surface={surface} />
            <BookmarkBar
              bookmarks={board.bookmarks}
              onJump={jumpBookmark}
              onSave={saveBookmark}
              onClear={slot => onBookmarks(board.bookmarks.filter(item => item.slot !== slot))}
            />
          </div>

          {notice && (
            <div className="cn-notice" role="status">
              {notice}
              <button type="button" className="cn-button is-quiet" onClick={() => setNotice('')} aria-label={t('关闭提示')}><X aria-hidden="true" /></button>
            </div>
          )}
          {help && (
            <aside className="cn-help" aria-label={t('快捷键')}>
              <h3>{t('快捷键')}</h3>
              <dl>{shortcuts().map(([keys, what]) => <div key={keys}><dt>{keys}</dt><dd>{what}</dd></div>)}</dl>
            </aside>
          )}
        </div>

        <aside className={`cn-side${panel ? '' : ' is-collapsed'}`}>
          <div className="cn-tabs" role="tablist" aria-label={t('侧栏')}>
            {([['inspector', t('属性'), SlidersHorizontal], ['outline', t('大纲'), ListTree], ['versions', t('版本'), History], ['workflow', t('工作流'), Workflow]] as const).map(([id, label, Icon]) => (
              <button key={id} type="button" role="tab" aria-selected={panel === id} aria-label={label} title={label} className={panel === id ? 'is-active' : ''} onClick={() => setPanel(value => (value === id ? null : id))}>
                <Icon aria-hidden="true" />{panel ? <span>{label}</span> : null}
              </button>
            ))}
            <button type="button" aria-label={t('快捷键')} title={t('快捷键')} onClick={() => setHelp(value => !value)}><HelpCircle aria-hidden="true" /></button>
          </div>
          {panel === 'inspector' && (onlySelected ? (
            <InspectorPanel
              key={onlySelected.id} node={onlySelected} doc={doc} options={options} shots={shots} projectId={projectId} canvasId={canvasId} latest={latest[onlySelected.id]}
              onPatch={(payload, coalesce) => actions.patch(onlySelected.id, payload, coalesce)}
              onSetRole={(edgeId, role) => edit(current => ({ ...current, edges: current.edges.map(edge => (edge.id === edgeId ? { ...edge, payload: { ...edge.payload, role } } : edge)) }))}
              onRemoveEdge={edgeId => edit(current => ({ ...current, edges: current.edges.filter(edge => edge.id !== edgeId) }))}
              onHistoryChanged={() => { void runs.refresh(); }}
              onRun={() => { void runNodes([onlySelected.id]); }}
              onCommit={() => { void openCommit([onlySelected.id]); }}
            />
          ) : (
            <section className="cn-panel"><p className="cn-hint">{selection.size ? t('已选中 {0} 个节点', [selection.size]) : t('选中一个节点查看属性和生成记录。')}</p></section>
          ))}
          {panel === 'outline' && (
            <OutlinePanel nodes={doc.nodes} selection={selection} onJump={id => { surface.current?.jumpTo(id); setSelection(new Set([id])); setEdgeSelection(new Set()); }} />
          )}
          {panel === 'versions' && <VersionsPanel projectId={projectId} canvasId={canvasId} version={version} onRestore={restore} />}
          {panel === 'workflow' && (
            <WorkflowPanel
              projectId={projectId} canvasId={canvasId} refreshKey={`${version}:${JSON.stringify(latest)}`} flush={flush} currentVersion={currentVersion}
              onApplied={reload} onRun={nodeIds => { void runNodes(nodeIds); }}
              onJump={id => { surface.current?.jumpTo(id); setSelection(new Set([id])); setEdgeSelection(new Set()); }}
            />
          )}
        </aside>

        {assessment && <RunDialog assessment={assessment.value} onClose={closeAssessment} onConfirm={confirmRun} />}
        {commit && <CommitDialog projectId={projectId} canvasId={canvasId} nodeIds={commit} onClose={closeCommit} onCommit={sendCommit} />}
        {desk && (
          <Suspense fallback={null}>
            <DirectorDesk
              key={`desk-${desk.sceneId}`} taskId={taskId} sceneId={desk.sceneId} initialShotId={desk.shotId}
              initialSideTab={desk.reference ? 'blockout' : undefined} initialReference={desk.reference} onClose={closeDesk}
            />
          </Suspense>
        )}
      </div>
    </CanvasContext.Provider>
  );
});

function initialTheme(): 'light' | 'dark' {
  try {
    const stored = window.localStorage.getItem('canvas.theme');
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {
    // Falls through to the app's own setting.
  }
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
}

/** The infinite node canvas of one project, as a full-window layer over the workbench. */
export function CanvasWorkspace({ taskId, onClose }: { taskId: string; onClose: () => void }) {
  const [projectId, setProjectId] = useState('');
  const [boards, setBoards] = useState<CanvasBoard[]>([]);
  const [boardId, setBoardId] = useState('main');
  const [options, setOptions] = useState<RunOptions | null>(null);
  const [shots, setShots] = useState<ProjectShot[]>([]);
  const [problem, setProblem] = useState('');
  const [theme, setTheme] = useState(initialTheme);
  const [renaming, setRenaming] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [closeBlocked, setCloseBlocked] = useState(false);
  const editor = useRef<EditorHandle | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    openTaskCanvas(taskId, controller.signal).then(opened => {
      setProjectId(opened.project_id);
      setBoards(opened.canvases);
      setBoardId(opened.canvases[0]?.id ?? 'main');
      // Both are conveniences for the node bodies: without them a node still edits, its pickers are just empty.
      fetchRunOptions(opened.project_id, controller.signal).then(setOptions).catch(() => undefined);
      fetchShots(opened.project_id, controller.signal).then(setShots).catch(() => undefined);
    }).catch(error => {
      if (!controller.signal.aborted) setProblem(messageOf(error, t('画布打开失败')));
    });
    return () => controller.abort();
  }, [taskId]);

  const board = boards.find(item => item.id === boardId);

  const switchTo = useCallback(async (id: string) => {
    await editor.current?.flush();
    setBoardId(id);
    setConfirmDelete(false);
    setRenaming(false);
  }, []);

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    try {
      window.localStorage.setItem('canvas.theme', next);
    } catch {
      // A per-browser preference; losing it costs one click.
    }
  };

  const addBoard = async () => {
    try {
      await editor.current?.flush();
      const created = await createBoard(projectId, t('画布 {0}', [boards.length + 1]));
      setBoards(current => [...current, created]);
      setBoardId(created.id);
    } catch (error) {
      setProblem(messageOf(error, t('新建画布失败')));
    }
  };

  const rename = async (title: string) => {
    setRenaming(false);
    const trimmed = title.trim();
    if (!trimmed || !board || trimmed === board.title) return;
    try {
      const saved = await patchBoard(projectId, board.id, { title: trimmed });
      setBoards(current => current.map(item => (item.id === saved.id ? { ...item, title: saved.title } : item)));
    } catch (error) {
      setProblem(messageOf(error, t('改名失败')));
    }
  };

  const removeBoard = async () => {
    if (!board) return;
    try {
      await deleteBoard(projectId, board.id);
      setBoards(current => current.filter(item => item.id !== board.id));
      setBoardId('main');
      setConfirmDelete(false);
    } catch (error) {
      setProblem(messageOf(error, t('删除画布失败')));
    }
  };

  const onBookmarks = useCallback((bookmarks: Bookmark[]) => {
    setBoards(current => current.map(item => (item.id === boardId ? { ...item, bookmarks } : item)));
    patchBoard(projectId, boardId, { bookmarks }).catch(error => setProblem(messageOf(error, t('书签保存失败'))));
  }, [boardId, projectId]);

  const onForked = useCallback((created: CanvasBoard) => {
    setBoards(current => [...current, created]);
    setBoardId(created.id);
  }, []);

  const onVersion = useCallback((version: number) => {
    setBoards(current => current.map(item => (item.id === boardId && item.version !== version ? { ...item, version } : item)));
  }, [boardId]);

  const close = async () => {
    if (await (editor.current?.flush() ?? Promise.resolve(true))) onClose();
    else setCloseBlocked(true);
  };

  return (
    <div className="canvas-workspace" data-theme={theme} role="dialog" aria-modal="true" aria-label={t('节点画布')}>
      <header className="cn-topbar">
        <h1>{t('节点画布')}</h1>
        {boards.length > 0 && (
          <div className="cn-boards">
            {renaming && board ? (
              <input
                autoFocus defaultValue={board.title} maxLength={80} aria-label={t('画布名称')}
                onBlur={event => { void rename(event.target.value); }}
                onKeyDown={event => {
                  if (event.key === 'Enter') void rename(event.currentTarget.value);
                  if (event.key === 'Escape') setRenaming(false);
                }}
              />
            ) : (
              <select aria-label={t('切换画布')} value={boardId} onChange={event => { void switchTo(event.target.value); }}>
                {boards.map(item => <option key={item.id} value={item.id}>{item.id === 'main' && item.title === '主画布' ? t('主画布') : item.title}</option>)}
              </select>
            )}
            <button type="button" className="cn-icon" onClick={() => { void addBoard(); }} aria-label={t('新建画布')} title={t('新建画布')}><Plus aria-hidden="true" /></button>
            <button type="button" className="cn-icon" onClick={() => setRenaming(true)} aria-label={t('重命名画布')} title={t('重命名画布')}><Pencil aria-hidden="true" /></button>
            {boardId !== 'main' && (confirmDelete ? (
              <button type="button" className="cn-button is-danger" onClick={() => { void removeBoard(); }}>{t('确认删除这张画布')}</button>
            ) : (
              <button type="button" className="cn-icon" onClick={() => setConfirmDelete(true)} aria-label={t('删除画布')} title={t('删除画布')}><Trash2 aria-hidden="true" /></button>
            ))}
          </div>
        )}
        {problem && <span className="cn-error" role="alert">{problem}</span>}
        <span className="cn-grow" />
        {closeBlocked && (
          <div className="cn-close-blocked" role="alert">
            <span>{t('还有修改没保存成功。')}</span>
            <button type="button" className="cn-button is-danger" onClick={onClose}>{t('放弃修改并关闭')}</button>
            <button type="button" className="cn-button" onClick={() => setCloseBlocked(false)}>{t('留下')}</button>
          </div>
        )}
        <button type="button" className="cn-icon" onClick={toggleTheme} aria-label={theme === 'dark' ? t('切换到浅色') : t('切换到深色')} title={theme === 'dark' ? t('切换到浅色') : t('切换到深色')}>
          {theme === 'dark' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
        </button>
        <button type="button" className="cn-button" onClick={() => { void close(); }}><X aria-hidden="true" /> {t('关闭')}</button>
      </header>
      {projectId && board ? (
        <CanvasEditor
          key={board.id} ref={editor} taskId={taskId} projectId={projectId} board={board} options={options} shots={shots}
          onBookmarks={onBookmarks} onForked={onForked} onVersion={onVersion}
        />
      ) : (
        !problem && <p className="cn-loading">{t('读取中…')}</p>
      )}
    </div>
  );
}
