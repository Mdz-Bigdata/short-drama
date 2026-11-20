import { forwardRef, lazy, Suspense, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, type RefObject } from 'react';
import {
  AudioLines, Bot, Boxes, Clapperboard, Copy, Download, FileUp, Film, Globe2, HelpCircle, ImageIcon, Library, ListTree, Moon, Palette, Pencil, Play, Plus, Redo2, RefreshCw, Search, Cpu, Clapperboard as FilmIcon, Send, Share2, SlidersHorizontal,
  StickyNote, Sun, Trash2, Undo2, Upload, Waypoints, X, History, type LucideIcon, Workflow, Wrench,
} from 'lucide-react';

import { apiUrl } from '../../api/client';
import { t } from '../../i18n';
import { DeskLoading } from '../directorDesk/DeskLoading';
import {
  assessRun, cancelRun, commitNodes, createBoard, deleteBoard, fetchRunOptions, fetchShots, openTaskCanvas, patchBoard, restoreVersion, saveCanvas, startRun, uploadMedia,
} from './canvasApi';
import { BACKGROUND_MODES, type CanvasBackgroundMode } from './canvasBackground';
import { pasteIdMap, pastePlan, readStoredClip, reconnectInbound, writeClip } from './canvasClipboard';
import { createConnectedNode, findFreeSpot } from './canvasConnectedPlacement';
import { CanvasContext, type CanvasActions } from './canvasContext';
import { exportCanvas, exportFileName, importOffset, mergeImport, parseCanvasImport } from './canvasExport';
import { changedNodeIds, flashDurationMs } from './canvasFocus';
import {
  carriedIds, descendantIds, dropIntoGroup, fitGroupToMembers, groupNodes2, hiddenMemberIds, isCollapsed, layoutUnits, shownAs, toggleGroupCollapsed, visibleNodes,
} from './canvasFrames';
import { CANVAS_COORD_LIMIT, CANVAS_MAX_EDGES, CANVAS_MAX_NODES, boundsOf, clampCoord } from './canvasGeometry';
import {
  DEFAULT_SIZES, RUNNABLE_KINDS, connect, copySelection, deleteSelection, effectiveOutput, makeId, newNode, pasteClip, patchNode, ungroup, upstreamImageUrl, type CanvasClip,
} from './canvasGraph';
import { kindLabel, refusalMessage } from './canvasLabels';
import { align, applyPositions, arrange, distribute, type AlignKind, type ArrangeKind, type DistributeAxis, type PositionPatch } from './canvasLayout';
import { bindMenu, canvasMenu, edgeMenu, nodeMenu, type MenuItem, type MenuSpec } from './canvasMenus';
import { shortcutGroups } from './canvasShortcutsHelp';
import { WorkflowPanel } from './WorkflowPanel';
import { CommitDialog, RunDialog } from './CanvasDialogs';
import { CanvasContextMenu } from './CanvasContextMenu';
import { CanvasMinimapCanvas } from './CanvasMinimapCanvas';
import { CanvasNodeCard, NodeShell } from './CanvasNodeCard';
import { CanvasPresenceLayer, CanvasPresencePeers } from './CanvasPresenceLayer';
import { BookmarkBar, InspectorPanel, OutlinePanel, VersionsPanel } from './CanvasPanels';
import { CanvasSearchDialog } from './CanvasSearchDialog';
import { CanvasShareDialog } from './CanvasShareDialog';
import { CanvasStoryboardDialog } from './CanvasStoryboardDialog';
import { CanvasExportDialog } from './CanvasExportDialog';
import { importBundle, isBundleFile } from './canvasBundleApi';
import { CanvasProjectSyncDialog } from './CanvasProjectSyncDialog';
import { useSyncCount } from './canvasProjectSync';
import { CanvasFilmDialog } from './CanvasFilmDialog';
import { CanvasModelsDialog } from './CanvasModelsDialog';
import type { FilmBuild } from './canvasFilmApi';
import { layOutShotTable } from './canvasShotLayout';
import { CanvasElementPickerDialog, CanvasSaveElementDialog } from './CanvasElementDialogs';
import { savablePicture, type SavedElement, type TakenElements } from './canvasElementsApi';
import { CanvasSelectionToolbar, TOOLBAR_CLEARANCE } from './CanvasSelectionToolbar';
import { CanvasSurface, type NodeRenderProps, type SurfaceHandle, type SurfaceMenuRequest } from './CanvasSurface';
import { CanvasZoomControls } from './CanvasZoomControls';
import type {
  Bookmark, CanvasBoard, CanvasDoc, CanvasNode, LatestRun, NodeKind, NodeOutput, NodePayload, ProjectShot, RunAssessment, RunOptions, TierConfirmation, Viewport,
} from './canvasTypes';
import { useCanvasDocument, type SaveStatus } from './useCanvasDocument';
import { fitMediaNode, measureMedia, type MediaSize } from './canvasMedia';
import { useCanvasOpen, type BoundShot } from './useCanvasOpen';
import { CanvasComposerHost } from './CanvasComposerHost';
import { CanvasChatPanel } from './CanvasChatPanel';
import { useCanvasPresence } from './useCanvasPresence';
import { useCanvasRuns } from './useCanvasRuns';
import { useCanvasNodeActions } from './useCanvasNodeActions';
import { CanvasBatchTable } from './CanvasBatchTable';
import { CanvasBeefConflictActions } from './CanvasBeefConflictActions';
import { CanvasBeefReferencePanel } from './CanvasBeefReferencePanel';
import { CanvasBeefToolbarExtras } from './CanvasBeefToolbarExtras';
import { CanvasBeefVersionPreview } from './CanvasBeefVersionPreview';
import { appearanceStyle, boardAppearance, resolveAppearance, type CanvasAppearance } from './canvasBeefAppearance';
import { fetchReferenceLimits, type ReferenceLimits } from './canvasBeefApi';
import { applySuggestions } from './canvasBeefReferences';
import { useCanvasTool } from './canvasBeefTool';
import { CanvasBeefDocContext } from './canvasBeefDocContext';
import './CanvasWorkspace.css';

const DirectorDesk = lazy(() => import('../directorDesk/DirectorDesk').then(module => ({ default: module.DirectorDesk })));

const BEAT_GAP = 40;

const PALETTE: Array<{ kind: NodeKind; icon: LucideIcon }> = [
  { kind: 'media', icon: Upload }, { kind: 'note', icon: StickyNote }, { kind: 'image_gen', icon: ImageIcon }, { kind: 'video_gen', icon: Film },
  { kind: 'audio_gen', icon: AudioLines }, { kind: 'video_compose', icon: Clapperboard }, { kind: 'style_ref', icon: Palette }, { kind: 'panorama', icon: Globe2 },
  { kind: 'previz', icon: Waypoints }, { kind: 'tool', icon: Wrench },
];

const PASTE_OFFSET = 40;
/** Pasted or dropped files are laid out this many to a row. */
const FILE_COLUMNS = 3;
const FILE_GAP = 24;
/** How long Ctrl/⌘+V waits for the browser's paste event before falling back to this tab's own copy. */
const PASTE_FALLBACK_MS = 60;
const NO_IDS: ReadonlySet<string> = new Set();
// In memory and outside any board, so a copy can be pasted onto another canvas even when storage is refused.
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

function storedBackground(canvasId: string): CanvasBackgroundMode {
  try {
    const raw = window.localStorage.getItem(`canvas.background.${canvasId}`);
    return BACKGROUND_MODES.find(mode => mode === raw) ?? 'dots';
  } catch {
    return 'dots';
  }
}

function rememberBackground(canvasId: string, mode: CanvasBackgroundMode) {
  try {
    window.localStorage.setItem(`canvas.background.${canvasId}`, mode);
  } catch {
    // Like the view: a per-browser convenience.
  }
}

function backgroundLabel(mode: CanvasBackgroundMode) {
  switch (mode) {
    case 'dots': return t('点阵');
    case 'grid': return t('网格');
    case 'blank': return t('空白');
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

/** Why the server would refuse this document, or '' when it fits. */
function limitProblem(doc: CanvasDoc) {
  if (doc.nodes.length > CANVAS_MAX_NODES || doc.edges.length > CANVAS_MAX_EDGES) {
    return t('一张画布最多 {0} 个节点、{1} 条连线。', [CANVAS_MAX_NODES, CANVAS_MAX_EDGES]);
  }
  if (doc.nodes.some(node => Math.abs(node.x) > CANVAS_COORD_LIMIT || Math.abs(node.y) > CANVAS_COORD_LIMIT)) return t('节点位置超出了画布范围。');
  return '';
}

function shiftNodes(doc: CanvasDoc, ids: ReadonlySet<string>, dx: number, dy: number): CanvasDoc {
  if (!dx && !dy) return doc;
  return { ...doc, nodes: doc.nodes.map(node => (ids.has(node.id) ? { ...node, x: clampCoord(node.x + dx), y: clampCoord(node.y + dy) } : node)) };
}

/**
 * After a move: a frame whose members moved grows to keep them inside, and a frame a member left closes
 * around the ones that stayed. A frame that moved with them is left as it is.
 */
function refitGroups(before: CanvasDoc, after: CanvasDoc, moved: ReadonlySet<string>): CanvasDoc {
  const prior = new Map(before.nodes.map(node => [node.id, node.payload.groupId]));
  const touched = new Map<string, 'grow' | 'fit'>();
  for (const node of after.nodes) {
    if (!moved.has(node.id)) continue;
    const was = prior.get(node.id);
    const now = node.payload.groupId;
    if (was && was !== now && !moved.has(was)) touched.set(was, 'fit');
    if (now && !moved.has(now) && !touched.has(now)) touched.set(now, 'grow');
  }
  let next = after;
  for (const [groupId, how] of touched) {
    const group = next.nodes.find(node => node.id === groupId);
    if (!group || isCollapsed(group)) continue;
    const fitted = fitGroupToMembers(next, groupId);
    if (how === 'fit' || fitted === next) {
      next = fitted;
      continue;
    }
    const snug = fitted.nodes.find(node => node.id === groupId)!;
    next = patchNode(next, groupId, boundsOf([group, snug])!);
  }
  return next;
}

async function readText(file: File): Promise<string> {
  if (typeof file.text === 'function') return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(reader.error ?? new Error(t('文件读取失败')));
    reader.readAsText(file);
  });
}

/** The surface's view as React state, for the few small things drawn over it that follow every frame. */
function useSurfaceView(surface: RefObject<SurfaceHandle | null>) {
  const [state, setState] = useState<{ view: Viewport; width: number; height: number } | null>(null);
  useEffect(() => surface.current?.subscribe((view, size) => setState({ view, width: size.width, height: size.height })), [surface]);
  return state;
}

function ZoomControlsHost({ surface, hasSelection, onFitSelection }: { surface: RefObject<SurfaceHandle | null>; hasSelection: boolean; onFitSelection: () => void }) {
  const state = useSurfaceView(surface);
  return (
    <CanvasZoomControls
      zoom={state?.view.zoom ?? 1} hasSelection={hasSelection} onFitSelection={onFitSelection}
      onZoomTo={zoom => surface.current?.zoomTo(zoom)} onStep={dir => surface.current?.zoomStep(dir)} onFitAll={() => surface.current?.fit()}
    />
  );
}

function MinimapHost({ surface, nodes, selection }: { surface: RefObject<SurfaceHandle | null>; nodes: readonly CanvasNode[]; selection: ReadonlySet<string> }) {
  const state = useSurfaceView(surface);
  if (!state) return null;
  return (
    <CanvasMinimapCanvas
      nodes={nodes} view={state.view} width={state.width} height={state.height} selected={selection} mapWidth={176} mapHeight={120}
      onJump={view => surface.current?.setView(view)}
    />
  );
}

interface SelectionToolbarHostProps {
  surface: RefObject<SurfaceHandle | null>;
  nodes: readonly CanvasNode[];
  selection: ReadonlySet<string>;
  onAlign: (kind: AlignKind) => void;
  onDistribute: (axis: DistributeAxis) => void;
  onArrange: (kind: ArrangeKind) => void;
  onGroup: () => void;
  onUngroup: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  /** Present when the selection holds two or more pictures or clips: wire them to one video node. */
  onConnectVideo?: () => void;
}

function SelectionToolbarHost({ surface, nodes, selection, onUngroup, ...actions }: SelectionToolbarHostProps) {
  const state = useSurfaceView(surface);
  const chosen = useMemo(() => nodes.filter(node => selection.has(node.id)), [nodes, selection]);
  const box = useMemo(() => boundsOf(chosen), [chosen]);
  if (!state || !box || chosen.length < 2) return null;
  const { view, width, height } = state;
  // A selection bigger than the view keeps its toolbar on screen: anchored to the part of it that is in sight.
  const left = Math.max(0, box.x * view.zoom + view.x);
  const right = Math.min(width, (box.x + box.width) * view.zoom + view.x);
  const rawTop = box.y * view.zoom + view.y;
  // Its top above the screen: the toolbar sits at the top of the view instead of below a bottom that may be far off.
  const top = rawTop < 0 ? TOOLBAR_CLEARANCE : Math.min(rawTop, height);
  const bottom = Math.max(top, Math.min(height, (box.y + box.height) * view.zoom + view.y));
  const rect = { x: Math.min(left, right), y: top, width: Math.abs(right - left), height: bottom - top };
  return (
    <CanvasSelectionToolbar
      rect={rect} count={chosen.length} {...actions}
      onUngroup={chosen.some(node => node.kind === 'group') ? onUngroup : undefined}
    />
  );
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
  /** Leave the canvas for the storyboard, at the shot a card is tied to. */
  onOpenShot?: (shot: BoundShot) => void;
}

/** What a menu item acts on: fixed when the menu opens, so a later click does not read a changed selection. */
interface MenuContext {
  world: { x: number; y: number };
  ids: ReadonlySet<string>;
  nodeId?: string;
  edgeId?: string;
  /** The connection being dropped, for the kind picker. */
  source?: string;
}

/** One canvas. Remounted per board, so nothing of one canvas's undo stack or selection can reach another. */
const CanvasEditor = forwardRef<EditorHandle, EditorProps>(function CanvasEditor({ taskId, projectId, board, options, shots, onBookmarks, onForked, onVersion, onOpenShot }, handle) {
  const canvasId = board.id;
  // The other windows this person has on this canvas (never on the public share page, which has no editor).
  const presence = useCanvasPresence({ projectId, canvasId, enabled: true });
  const { onSaved, sendCursor, sendDrag, sendSelection } = presence;
  const document_ = useCanvasDocument(projectId, canvasId, { clientId: presence.clientId });
  const { doc, status, version, edit, flush, adopt, reload, currentDoc, currentVersion, hasUnsaved, isLoaded } = document_;
  const surface = useRef<SurfaceHandle | null>(null);
  const [selection, setSelection] = useState<ReadonlySet<string>>(() => new Set());
  const [edgeSelection, setEdgeSelection] = useState<ReadonlySet<string>>(() => new Set());
  const [notice, setNotice] = useState('');
  const [panel, setPanel] = useState<'inspector' | 'outline' | 'versions' | 'workflow' | 'assistant' | null>('inspector');
  const [help, setHelp] = useState(false);
  const [assessment, setAssessment] = useState<{ value: RunAssessment; nodeIds: string[]; operationId: string } | null>(null);
  const [commit, setCommit] = useState<string[] | null>(null);
  const [desk, setDesk] = useState<{ sceneId: string; shotId?: number; reference?: { url: string } } | null>(null);
  // BeefTV-described additions: the hand tool, the batch creation table, version preview, board appearance, smart reference.
  const [tool, setTool] = useCanvasTool();
  const [batching, setBatching] = useState(false);
  const [previewing, setPreviewing] = useState<number | null>(null);
  const [appearance, setAppearance] = useState<CanvasAppearance>(() => boardAppearance(canvasId, ''));
  const [referenceLimits, setReferenceLimits] = useState<ReferenceLimits | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetchReferenceLimits(taskId, controller.signal).then(setReferenceLimits).catch(() => undefined);
    return () => controller.abort();
  }, [taskId]);
  const boardTheme = appearance.theme === 'follow' ? null : resolveAppearance(appearance, 'light');
  const [deskToken, setDeskToken] = useState(0);
  const [fitted, setFitted] = useState(false);
  const [background, setBackground] = useState<CanvasBackgroundMode>(() => storedBackground(canvasId));
  const [menu, setMenu] = useState<{ x: number; y: number; items: MenuItem[]; label?: string } | null>(null);
  const [search, setSearch] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [flash, setFlash] = useState<ReadonlySet<string>>(NO_IDS);
  const renamingRef = useRef<string | null>(null);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pasteTick = useRef(0);
  const pasteTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const importInput = useRef<HTMLInputElement>(null);

  const say = useCallback((message: string) => setNotice(message), []);

  useEffect(() => () => {
    if (flashTimer.current) clearTimeout(flashTimer.current);
    if (pasteTimer.current) clearTimeout(pasteTimer.current);
  }, []);

  /** Light up nodes someone else changed, for a moment. */
  const flashNodes = useCallback((ids: readonly string[]) => {
    if (flashTimer.current) clearTimeout(flashTimer.current);
    setFlash(new Set(ids));
    flashTimer.current = setTimeout(() => setFlash(NO_IDS), flashDurationMs);
  }, []);

  /** Catch up with the stored canvas, then show and light up what changed there. */
  const reloadAndShow = useCallback(async () => {
    const before = currentDoc();
    await reload();
    const after = currentDoc();
    if (after === before) return;
    const changed = changedNodeIds(before, after);
    if (!changed.length) return;
    // A change inside a folded group shows on the group.
    const shownIds = new Set(changed.map(id => shownAs(after, id)));
    surface.current?.reveal(after.nodes.filter(node => shownIds.has(node.id)));
    flashNodes([...shownIds]);
  }, [currentDoc, flashNodes, reload]);

  const onRemoteVersion = useCallback((remote: number) => {
    // Until the document is in, its version is still 0: the first poll to come back is not news from anywhere.
    if (!isLoaded() || remote <= currentVersion() || hasUnsaved()) return;
    // Someone else wrote (another window, the assistant). With nothing of ours pending, just catch up.
    void reloadAndShow().then(() => setNotice(t('画布已在别处更新，已载入最新版本。')));
  }, [currentVersion, hasUnsaved, isLoaded, reloadAndShow]);

  const runs = useCanvasRuns(projectId, canvasId, onRemoteVersion);
  // Another window saved: catch up now rather than on the next poll. With edits of our own pending,
  // onRemoteVersion leaves it alone and the next save meets the usual 409.
  useEffect(() => onSaved(saved => onRemoteVersion(saved.version)), [onRemoteVersion, onSaved]);
  // A run changed state (here or in another window): read the outputs now; the poll stays as the fallback.
  const { onRun } = presence;
  const { refreshSoon } = runs;
  useEffect(() => onRun(() => refreshSoon()), [onRun, refreshSoon]);
  useEffect(() => { sendSelection([...selection]); }, [selection, sendSelection]);
  const outputsRef = useRef<Readonly<Record<string, NodeOutput>>>(runs.data.outputs);
  useEffect(() => { outputsRef.current = runs.data.outputs; }, [runs.data.outputs]);
  useEffect(() => { onVersion(version); }, [onVersion, version]);

  useImperativeHandle(handle, () => ({ flush }), [flush]);

  const select = useCallback((nodes: ReadonlySet<string>, edges: ReadonlySet<string>) => {
    setSelection(nodes);
    setEdgeSelection(edges);
  }, []);

  // First look at a canvas: where you left it, or else the whole thing.
  useEffect(() => {
    if (fitted || status === 'loading') return;
    const saved = storedView(canvasId);
    if (saved) surface.current?.setView(saved);
    else surface.current?.fit(undefined, { instant: true });
    // eslint-disable-next-line react-hooks/set-state-in-effect -- runs once, the first time the document is there
    setFitted(true);
  }, [canvasId, fitted, status]);

  const addNode = useCallback((kind: NodeKind, at?: { x: number; y: number }, payload?: NodePayload): string | null => {
    if (currentDoc().nodes.length >= CANVAS_MAX_NODES) {
      say(t('一张画布最多 {0} 个节点、{1} 条连线。', [CANVAS_MAX_NODES, CANVAS_MAX_EDGES]));
      return null;
    }
    const point = at ?? surface.current?.centre() ?? { x: 0, y: 0 };
    let x = clampCoord(Math.round(point.x));
    let y = clampCoord(Math.round(point.y));
    if (!at) {
      // 从工具栏加的节点：以画面中心为准，找最近一块不压住任何节点的空地（往下或往右，挑挪得少的那边）。
      // 原来只是往右下错开一格，连着加几个就一张压一张、把下面的节点盖住。
      const [width, height] = DEFAULT_SIZES[kind];
      const spot = findFreeSpot(currentDoc().nodes, { x: x - width / 2, y: y - height / 2 }, { width, height });
      x = clampCoord(Math.round(spot.x));
      y = clampCoord(Math.round(spot.y));
    }
    const node = newNode(kind, x, y, payload);
    edit(current => ({ ...current, nodes: kind === 'group' ? [node, ...current.nodes] : [...current.nodes, node] }));
    setSelection(new Set([node.id]));
    setEdgeSelection(new Set());
    return node.id;
  }, [currentDoc, edit, say]);

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

  // 几个文件一起传时先后结束：记着还有几个没传完，全部结束才撤掉提示(有失败就留下失败原因)。
  const uploads = useRef({ total: 0, settled: 0, problem: '' });

  const upload = useCallback((nodeId: string, file: File) => {
    const batch = uploads.current;
    batch.total += 1;
    const report = () => say(batch.total > 1 ? t('上传中：已完成 {0}/{1}…', [batch.settled, batch.total]) : t('上传中…'));
    const settle = (problem = '') => {
      batch.settled += 1;
      if (problem) batch.problem = problem;
      if (batch.settled < batch.total) {
        report();
        return;
      }
      say(batch.problem);
      uploads.current = { total: 0, settled: 0, problem: '' };
    };
    report();
    // Read locally while the file travels: ready by the time the upload answers, or the card keeps its size.
    let measured: MediaSize | null = null;
    void measureMedia(file).then(size => { measured = size; });
    uploadMedia(projectId, file).then(result => {
      const node = currentDoc().nodes.find(item => item.id === nodeId);
      if (!node) {
        settle();
        return;
      }
      if ((node.kind === 'style_ref' || node.kind === 'panorama') && result.medium !== 'image') {
        settle(t('这个节点只接受图片。'));
        return;
      }
      const output: NodeOutput = {
        medium: result.medium, url: result.url, filename: result.filename, provenance: result.provenance,
        ...(result.preview_url ? { preview_url: result.preview_url } : {}),
      };
      edit(current => patchNode(current, nodeId, fitMediaNode(node, measured) ?? {}, { output, ...(node.kind === 'media' ? { label: node.payload.label || result.filename } : {}) }));
      settle();
    }).catch(error => settle(messageOf(error, t('上传失败'))));
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
    layOutShots: (sourceId, shots, framePrompts, cast) => {
      // A frame and a clip per shot, all at once or none: past the canvas's node limit nothing is laid out.
      if (currentDoc().nodes.length + shots.length * 2 + (cast?.length ?? 0) > CANVAS_MAX_NODES) {
        say(t('一张画布最多 {0} 个节点、{1} 条连线。', [CANVAS_MAX_NODES, CANVAS_MAX_EDGES]));
        return;
      }
      edit(current => layOutShotTable(current, sourceId, shots, framePrompts, cast) ?? current);
    },
    layOutBeats: (sourceId, beats) => {
      // 一整排节拍要么全部铺上，要么一个也不铺：铺上去会超出单张画布的节点上限时直接说明。
      if (currentDoc().nodes.length + beats.length > CANVAS_MAX_NODES) {
        say(t('一张画布最多 {0} 个节点、{1} 条连线。', [CANVAS_MAX_NODES, CANVAS_MAX_EDGES]));
        return;
      }
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

  const memberCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const node of doc.nodes) if (node.payload.groupId) counts.set(node.payload.groupId, (counts.get(node.payload.groupId) ?? 0) + 1);
    return counts;
  }, [doc.nodes]);

  /** The nodes that are drawn: none hidden in a folded group. */
  const shownNodes = useMemo(() => visibleNodes(doc.nodes), [doc.nodes]);

  const { outputs, latest, history_counts: historyCounts } = runs.data;

  const startRename = useCallback((id: string) => {
    renamingRef.current = id;
    setRenaming(id);
  }, []);

  const finishRename = useCallback((id: string, title: string | null) => {
    // Enter commits and unmounts the field; a blur arriving after that is not a second rename.
    if (renamingRef.current !== id) return;
    renamingRef.current = null;
    setRenaming(null);
    if (title === null) return;
    const node = currentDoc().nodes.find(item => item.id === id);
    const trimmed = title.trim().slice(0, 120);
    if (!node || trimmed === (node.payload.label ?? '')) return;
    edit(current => patchNode(current, id, {}, { label: trimmed }));
  }, [currentDoc, edit]);

  const toggleCollapse = useCallback((groupId: string) => {
    const current = currentDoc();
    const group = current.nodes.find(node => node.id === groupId);
    if (group?.kind !== 'group') return;
    const folding = !isCollapsed(group);
    edit(doc => toggleGroupCollapsed(doc, groupId));
    if (folding) {
      // What folds away is no longer selectable.
      const inside = descendantIds(current, groupId);
      setSelection(chosen => ([...chosen].some(id => inside.has(id)) ? new Set([...chosen].filter(id => !inside.has(id))) : chosen));
    }
  }, [currentDoc, edit]);

  const renderNode = useCallback(({ node, selected, lod, dropState }: NodeRenderProps) => {
    if (lod === 'shell') return <NodeShell node={node} selected={selected} />;
    return (
      <CanvasNodeCard
        node={node} selected={selected} dropState={dropState} output={effectiveOutput(node, doc, outputs)} latest={latest[node.id]}
        historyCount={historyCounts[node.id] ?? 0} inputs={inputCounts.get(node.id) ?? 0}
        reference={node.kind === 'previz' ? upstreamImageUrl(node, doc, outputs) : null}
        lod={lod} renaming={renaming === node.id} onRename={finishRename} onToggleCollapse={toggleCollapse} members={memberCounts.get(node.id) ?? 0}
      />
    );
  }, [doc, finishRename, historyCounts, inputCounts, latest, memberCounts, outputs, renaming, toggleCollapse]);

  const onMove = useCallback((ids: ReadonlySet<string>, dx: number, dy: number, point: { x: number; y: number } | null) => {
    edit(current => {
      const moved = shiftNodes(current, ids, Math.round(dx), Math.round(dy));
      // A drop over an open group's body puts the dragged nodes in it; one dragged out of its frame leaves it.
      return refitGroups(current, dropIntoGroup(moved, ids, point), ids);
    });
  }, [edit]);

  const onResize = useCallback((id: string, width: number, height: number) => {
    edit(current => patchNode(current, id, { width: Math.round(width), height: Math.round(height) }));
  }, [edit]);

  const onConnect = useCallback((source: string, target: string) => {
    const current = currentDoc();
    if (current.edges.length >= CANVAS_MAX_EDGES) {
      say(t('一张画布最多 {0} 个节点、{1} 条连线。', [CANVAS_MAX_NODES, CANVAS_MAX_EDGES]));
      return;
    }
    const result = connect(current, source, target);
    if (result.ok) edit(doc => ({ ...doc, edges: [...doc.edges, result.edge] }));
    else say(refusalMessage(result.reason));
  }, [currentDoc, edit, say]);

  const canConnect = useCallback((source: string, target: string) => connect(currentDoc(), source, target).ok, [currentDoc]);

  /** Media nodes for files, laid out in rows of three from `world`, each uploading on its own. */
  const placeFiles = useCallback((files: File[], world: { x: number; y: number }) => {
    const [width, height] = DEFAULT_SIZES.media;
    const made: string[] = [];
    files.slice(0, 20).forEach((file, index) => {
      const at = { x: world.x + (index % FILE_COLUMNS) * (width + FILE_GAP), y: world.y + Math.floor(index / FILE_COLUMNS) * (height + FILE_GAP) };
      const id = addNode('media', at, { label: file.name });
      if (!id) return;
      made.push(id);
      upload(id, file);
    });
    if (made.length) setSelection(new Set(made));
  }, [addNode, upload]);

  // ------------------------------------------------------------ copy, paste and the other edits on a set of nodes

  const writeCopy = useCallback((ids: ReadonlySet<string>) => {
    const current = currentDoc();
    const clip = copySelection(current, carriedIds(current.nodes, ids), outputsRef.current);
    if (!clip) return false;
    clipboard = clip;
    writeClip(clip);
    return true;
  }, [currentDoc]);

  const placeClip = useCallback((clip: CanvasClip, at: { x: number; y: number } | null) => {
    const box = boundsOf(clip.nodes);
    if (!box) return;
    const target = at ?? { x: box.x + PASTE_OFFSET, y: box.y + PASTE_OFFSET };
    const placed = pasteClip(currentDoc(), clip, Math.round(target.x - box.x), Math.round(target.y - box.y));
    // On the canvas it was copied from, the copies hang on the same upstream nodes as the originals.
    const next = reconnectInbound(placed.doc, clip, pasteIdMap(clip, placed.ids));
    const problem = limitProblem(next);
    if (problem) {
      say(problem);
      return;
    }
    edit(() => next);
    setSelection(new Set(placed.ids));
    setEdgeSelection(new Set());
  }, [currentDoc, edit, say]);

  const pasteStored = useCallback((at: { x: number; y: number } | null) => {
    const clip = readStoredClip() ?? clipboard;
    if (clip) placeClip(clip, at);
  }, [placeClip]);

  const duplicateIds = useCallback((ids: ReadonlySet<string>) => {
    const current = currentDoc();
    const clip = copySelection(current, carriedIds(current.nodes, ids), outputsRef.current);
    if (clip) placeClip(clip, null);
  }, [currentDoc, placeClip]);

  const removeIds = useCallback((ids: ReadonlySet<string>, edgeIds: ReadonlySet<string> = NO_IDS) => {
    if (!ids.size && !edgeIds.size) return;
    edit(current => deleteSelection(current, ids, edgeIds));
    setSelection(new Set());
    setEdgeSelection(new Set());
  }, [edit]);

  const groupIds = useCallback((ids: ReadonlySet<string>) => {
    const current = currentDoc();
    const made = groupNodes2(current, ids, t('分组'));
    if (!made) {
      say(layoutUnits(current.nodes, ids).length < 2 ? t('至少选中两个节点才能成组。') : t('分组最多只能嵌套一层。'));
      return;
    }
    edit(() => made.doc);
    setSelection(new Set([made.groupId]));
  }, [currentDoc, edit, say]);

  const ungroupIds = useCallback((ids: ReadonlySet<string>) => {
    const groups = new Set([...ids].filter(id => currentDoc().nodes.find(node => node.id === id)?.kind === 'group'));
    if (!groups.size) return;
    edit(current => ungroup(current, groups));
    setSelection(new Set());
  }, [currentDoc, edit]);

  const applyLayout = useCallback((patch: PositionPatch) => {
    if (!Object.keys(patch).length) return;
    edit(current => refitGroups(current, applyPositions(current, patch), new Set(Object.keys(patch))));
  }, [edit]);

  const selectAll = useCallback(() => {
    setSelection(new Set(visibleNodes(currentDoc()).map(node => node.id)));
    setEdgeSelection(new Set());
  }, [currentDoc]);

  const connectNew = useCallback((source: string, kind: NodeKind, world: { x: number; y: number }) => {
    const result = createConnectedNode(currentDoc(), source, kind, world);
    if (!result.ok) {
      say(refusalMessage(result.reason));
      return;
    }
    const problem = limitProblem(result.doc);
    if (problem) {
      say(problem);
      return;
    }
    edit(() => result.doc);
    setSelection(new Set([result.nodeId]));
    setEdgeSelection(new Set());
  }, [currentDoc, edit, say]);

  const saveBookmark = useCallback((slot: number) => {
    const view = surface.current?.getView();
    if (!view) return;
    const next = [...board.bookmarks.filter(item => item.slot !== slot), { slot, x: view.x, y: view.y, zoom: view.zoom }];
    onBookmarks(next);
    say(t('已保存书签 {0}。', [slot]));
  }, [board.bookmarks, onBookmarks, say]);

  const jumpBookmark = useCallback((slot: number) => {
    const mark = board.bookmarks.find(item => item.slot === slot);
    if (mark) surface.current?.animateTo({ x: mark.x, y: mark.y, zoom: mark.zoom });
  }, [board.bookmarks]);

  const fitSelected = useCallback(() => {
    if (selection.size) surface.current?.fit([...selection]);
  }, [selection]);

  // ------------------------------------------------------------ the element library: take pictures from it, keep a node's picture in it

  const [picking, setPicking] = useState(false);
  const closePicking = useCallback(() => setPicking(false), []);
  const [savingElement, setSavingElement] = useState<{ nodeId: string; name: string; url: string } | null>(null);
  const closeSavingElement = useCallback(() => setSavingElement(null), []);
  const onElementsTaken = useCallback(async (result: TakenElements) => {
    await reloadAndShow();
    setSelection(new Set(result.node_ids));
    setEdgeSelection(new Set());
    say(t('已从元素库取用 {0} 张图片。', [result.node_ids.length]));
  }, [reloadAndShow, say]);
  const onElementSaved = useCallback((element: SavedElement) => say(t('已存入元素库：{0}', [element.name])), [say]);
  const openSaveElement = useCallback((nodeId: string) => {
    const current = currentDoc();
    const node = current.nodes.find(item => item.id === nodeId);
    const picture = savablePicture(node, current, outputsRef.current);
    if (!node || !picture) {
      say(t('这个节点还没有图片结果，存不进元素库。'));
      return;
    }
    setSavingElement({ nodeId, name: node.payload.label ?? '', url: picture.url });
  }, [currentDoc, say]);

  // 裁剪、宫格拆分、下载、复制提示词、首尾帧模板、批量连到视频节点：逻辑都在 useCanvasNodeActions 里。
  const nodeActions = useCanvasNodeActions({ projectId, canvasId, currentDoc, outputs: outputsRef, edit, flush, currentVersion, reloadAndShow, say, select, surface });
  const { run: runNodeAction, nodeMenu: nodeActionMenu, paneMenu: paneActionMenu } = nodeActions;

  // ------------------------------------------------------------ menus

  const runMenu = useCallback((id: string, context: MenuContext) => {
    const ids = context.ids;
    const current = currentDoc();
    if (runNodeAction(id, context)) return;
    if (id.startsWith('add:')) {
      const kind = id.slice(4) as NodeKind;
      if (context.source) connectNew(context.source, kind, context.world);
      else addNode(kind, context.world);
      return;
    }
    if (id.startsWith('align:')) return applyLayout(align(current.nodes, ids, id.slice(6) as AlignKind));
    if (id.startsWith('distribute:')) return applyLayout(distribute(current.nodes, ids, id.slice(11) as DistributeAxis));
    if (id.startsWith('arrange:')) return applyLayout(arrange(current, ids, id.slice(8) as ArrangeKind));
    const edge = context.edgeId ? current.edges.find(item => item.id === context.edgeId) : undefined;
    switch (id) {
      case 'paste': pasteStored(context.world); break;
      case 'select-all': selectAll(); break;
      case 'fit-view': surface.current?.fit(); break;
      case 'undo': document_.undo(); break;
      case 'redo': document_.redo(); break;
      case 'run': if (context.nodeId) void runNodes([context.nodeId]); break;
      case 'run-selection': void runNodes([...ids]); break;
      case 'rename': if (context.nodeId) startRename(context.nodeId); break;
      case 'toggle-collapse': if (context.nodeId) toggleCollapse(context.nodeId); break;
      case 'fit-group': if (context.nodeId) edit(doc => fitGroupToMembers(doc, context.nodeId!)); break;
      case 'group': groupIds(ids); break;
      case 'ungroup': ungroupIds(ids); break;
      case 'copy': writeCopy(ids); break;
      case 'duplicate': duplicateIds(ids); break;
      case 'save-element': if (context.nodeId) openSaveElement(context.nodeId); break;
      case 'delete': removeIds(ids); break;
      case 'select-source': if (edge) select(new Set([edge.source]), new Set()); break;
      case 'select-target': if (edge) select(new Set([edge.target]), new Set()); break;
      case 'delete-edge': if (edge) removeIds(NO_IDS, new Set([edge.id])); break;
      default: break;
    }
  }, [
    addNode, applyLayout, connectNew, currentDoc, document_, duplicateIds, edit, groupIds, pasteStored, removeIds, runNodes, select, selectAll, startRename, toggleCollapse,
    ungroupIds, writeCopy, openSaveElement, runNodeAction,
  ]);

  const runMenuRef = useRef(runMenu);
  useEffect(() => { runMenuRef.current = runMenu; }, [runMenu]);

  const openMenu = useCallback((x: number, y: number, spec: MenuSpec[], context: MenuContext, label?: string) => {
    setMenu({ x, y, label, items: bindMenu(spec, id => runMenuRef.current(id, context)) });
  }, []);

  const onMenu = useCallback((request: SurfaceMenuRequest) => {
    const current = currentDoc();
    if (request.target === 'node' && request.id) {
      const node = current.nodes.find(item => item.id === request.id);
      if (!node) return;
      let ids = selection;
      if (!selection.has(node.id)) {
        ids = new Set([node.id]);
        select(ids, new Set());
      }
      const canRun = [...ids].some(id => RUNNABLE_KINDS.has(current.nodes.find(item => item.id === id)?.kind as NodeKind));
      const canSaveElement = Boolean(savablePicture(node, current, outputsRef.current));
      openMenu(request.clientX, request.clientY, nodeActionMenu(nodeMenu({ node, selectionCount: ids.size, canRun, canSaveElement }), node, ids), { world: request.world, ids, nodeId: node.id });
    } else if (request.target === 'edge' && request.id) {
      const edge = current.edges.find(item => item.id === request.id);
      if (!edge) return;
      select(new Set(), new Set([edge.id]));
      openMenu(request.clientX, request.clientY, edgeMenu({ edge }), { world: request.world, ids: NO_IDS, edgeId: edge.id });
    } else {
      const spec = canvasMenu({ canPaste: Boolean(readStoredClip() ?? clipboard), addKinds: PALETTE.map(item => item.kind), canUndo: document_.canUndo, canRedo: document_.canRedo });
      openMenu(request.clientX, request.clientY, paneActionMenu(spec), { world: request.world, ids: selection });
    }
  }, [currentDoc, document_.canRedo, document_.canUndo, nodeActionMenu, openMenu, paneActionMenu, select, selection]);

  // A connection dropped on empty canvas: offer the kinds that take what it carries, and make one there.
  const onConnectEmpty = useCallback((source: string, world: { x: number; y: number }, client: { x: number; y: number }) => {
    const current = currentDoc();
    const kinds = PALETTE.map(item => item.kind).filter(kind => createConnectedNode(current, source, kind, world).ok);
    if (!kinds.length) {
      say(t('没有能接收这个输出的节点类型。'));
      return;
    }
    openMenu(client.x, client.y, kinds.map(kind => ({ id: `add:${kind}`, label: kindLabel(kind) })), { world, ids: NO_IDS, source }, t('新建并连接'));
  }, [currentDoc, openMenu, say]);

  const closeMenu = useCallback(() => setMenu(null), []);

  // ------------------------------------------------------------ search, export, import

  const jumpToHit = useCallback((id: string) => {
    // A hit inside a folded group lands on the group.
    const shown = shownAs(currentDoc(), id);
    surface.current?.focusNode(shown);
    select(new Set([shown]), new Set());
  }, [currentDoc, select]);

  const boardTitle = board.id === 'main' && board.title === '主画布' ? t('主画布') : board.title;

  const exportBoard = useCallback(() => {
    const blob = exportCanvas(currentDoc(), { title: boardTitle, viewport: surface.current?.getView() ?? null, outputs: outputsRef.current });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = exportFileName(boardTitle);
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }, [boardTitle, currentDoc]);

  const importFile = useCallback(async (file: File) => {
    try {
      // 素材包（.zip）：服务端逐个查验、另存素材，再交回一份普通的画布文件，下面照常合并。
      const bundled = isBundleFile(file) ? await importBundle(projectId, canvasId, file) : null;
      const parsed = parseCanvasImport(bundled ? JSON.stringify(bundled.manifest) : await readText(file));
      const dropped = bundled ? bundled.report.failed.length + bundled.report.missing : 0;
      if (!parsed.doc.nodes.length) {
        say(t('导入的文件里没有节点。'));
        return;
      }
      const current = currentDoc();
      const merged = mergeImport(current, parsed.doc, importOffset(current.nodes, parsed.doc.nodes));
      const problem = limitProblem(merged.doc);
      if (problem) {
        say(problem);
        return;
      }
      edit(() => merged.doc);
      const folded = hiddenMemberIds(merged.doc);
      select(new Set(merged.ids.filter(id => !folded.has(id))), new Set());
      const ids = new Set(merged.ids);
      surface.current?.fitRects(merged.doc.nodes.filter(node => ids.has(node.id)));
      flashNodes(merged.ids);
      say(dropped ? t('已导入 {0} 个节点；{1} 个素材没通过检查，相应节点会显示为空。', [merged.ids.length, dropped]) : t('已导入 {0} 个节点。', [merged.ids.length]));
    } catch (error) {
      say(messageOf(error, t('导入失败')));
    }
  }, [canvasId, currentDoc, edit, flashNodes, projectId, say, select]);

  const changeBackground = useCallback((mode: CanvasBackgroundMode) => {
    setBackground(mode);
    rememberBackground(canvasId, mode);
  }, [canvasId]);

  const [sharing, setSharing] = useState(false);
  const closeShare = useCallback(() => setSharing(false), []);
  // 把项目分镜铺成节点：先把没存的改动存掉，再在那个版本上铺。
  const [storyboarding, setStoryboarding] = useState(false);
  const closeStoryboard = useCallback(() => setStoryboarding(false), []);
  const prepareStoryboard = useCallback(async () => {
    if (!await flush()) throw new Error(t('画布还没保存成功，先解决保存问题。'));
    return currentVersion();
  }, [currentVersion, flush]);
  // 导出：只导出画布（.json），或连同素材打包（.zip，见 canvas_bundle.py）。
  const [exportingBoard, setExportingBoard] = useState(false);
  const closeExport = useCallback(() => setExportingBoard(false), []);

  // Sync from the project: the button's count is asked again whenever a dialog that may have changed things closes.
  const [syncing, setSyncing] = useState(false);
  const [syncKey, setSyncKey] = useState(0);
  const closeSync = useCallback(() => {
    setSyncing(false);
    setSyncKey(value => value + 1);
  }, []);
  const syncCount = useSyncCount(projectId, canvasId, `${syncKey}:${storyboarding}`);

  // One-click film: the dialog puts the film's nodes in place, then they run through the usual quote and confirmation.
  const [filming, setFilming] = useState(false);
  const closeFilm = useCallback(() => setFilming(false), []);
  const filmBuilt = useCallback(async (built: FilmBuild) => {
    setFilming(false);
    await reloadAndShow();
    await runNodes(built.run);
  }, [reloadAndShow, runNodes]);

  const modal = Boolean(assessment || commit || desk || search || menu || sharing || storyboarding || syncing || filming || picking || savingElement || nodeActions.modal || exportingBoard);

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
        if (letter === '=' || letter === '+') {
          event.preventDefault();
          surface.current?.zoomStep(1);
        } else if (letter === '-' || letter === '_') {
          event.preventDefault();
          surface.current?.zoomStep(-1);
        } else if (event.code === 'Digit0' || letter === '0') {
          event.preventDefault();
          surface.current?.zoomTo(1);
        } else if (event.code === 'Digit1' || letter === '1') {
          event.preventDefault();
          surface.current?.fit();
        } else if (event.code === 'Digit2' || letter === '2') {
          event.preventDefault();
          fitSelected();
        } else if (letter === 'f') {
          event.preventDefault();
          setSearch(true);
        } else if (letter === 'z') {
          event.preventDefault();
          if (event.shiftKey) document_.redo();
          else document_.undo();
        } else if (letter === 'y') {
          event.preventDefault();
          document_.redo();
        } else if (letter === 'c') {
          if (writeCopy(selection)) event.preventDefault();
        } else if (letter === 'x') {
          if (writeCopy(selection)) {
            event.preventDefault();
            removeIds(selection, edgeSelection);
          }
        } else if (letter === 'v') {
          // Left to the browser, which follows with a paste event carrying the system clipboard. Without one
          // (no permission, nothing there) this tab's own last copy is pasted instead.
          const mark = pasteTick.current + 1;
          pasteTick.current = mark;
          const at = surface.current?.pointer() ?? null;
          if (pasteTimer.current) clearTimeout(pasteTimer.current);
          pasteTimer.current = setTimeout(() => {
            if (pasteTick.current === mark) pasteStored(at);
          }, PASTE_FALLBACK_MS);
        } else if (letter === 'd') {
          event.preventDefault();
          duplicateIds(selection);
        } else if (letter === 'a') {
          event.preventDefault();
          selectAll();
        } else if (letter === 'g') {
          event.preventDefault();
          if (event.shiftKey) ungroupIds(selection);
          else groupIds(selection);
        }
        return;
      }
      if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault();
        removeIds(selection, edgeSelection);
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
        edit(current => {
          const ids = carriedIds(current.nodes, selection);
          return refitGroups(current, shiftNodes(current, ids, dx, dy), ids);
        }, `nudge:${[...selection].join()}`);
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
  }, [
    document_, duplicateIds, edgeSelection, edit, fitSelected, flush, groupIds, jumpBookmark, modal, pasteStored, removeIds, saveBookmark, selectAll, selection, ungroupIds,
    writeCopy,
  ]);

  // The paste event carries the system clipboard: our own copy, pictures and clips, or plain text.
  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      if (modal || typing(event.target)) return;
      if (event.target instanceof Element && event.target !== document.body && !event.target.closest('.canvas-workspace')) return;
      const plan = pastePlan(event.clipboardData);
      // Nothing usable on the system clipboard: the Mod+V fallback still pastes this tab's own copy.
      if (!plan) return;
      pasteTick.current += 1;
      event.preventDefault();
      const at = surface.current?.pointer() ?? null;
      if (plan.kind === 'clip') placeClip(plan.clip, at);
      else if (plan.kind === 'files') placeFiles(plan.files, at ?? surface.current?.centre() ?? { x: 0, y: 0 });
      else addNode('note', at ?? undefined, { text: plan.text.slice(0, 8000) });
    };
    window.addEventListener('paste', onPaste);
    return () => window.removeEventListener('paste', onPaste);
  }, [addNode, modal, placeClip, placeFiles]);

  const onlySelected = selection.size === 1 ? doc.nodes.find(node => selection.has(node.id)) : undefined;
  // What "this node" means to the assistant in the side panel.
  const selectedNodes = useMemo(() => doc.nodes.filter(node => selection.has(node.id)), [doc.nodes, selection]);

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

  const opening = useCanvasOpen({ nodes: doc.nodes, onOpenShot });

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
            <button type="button" className="cn-icon" onClick={() => setSearch(true)} aria-label={t('搜索节点')} title={t('搜索节点')}><Search aria-hidden="true" /></button>
            <CanvasBeefToolbarExtras
              tool={tool} onTool={setTool} onBatch={() => setBatching(true)}
              canvasId={canvasId} accountId="" appearance={appearance} onAppearance={setAppearance}
            />
            <select className="cn-bg-select" aria-label={t('画布背景')} title={t('画布背景')} value={background} onChange={event => changeBackground(event.target.value as CanvasBackgroundMode)}>
              {BACKGROUND_MODES.map(mode => <option key={mode} value={mode}>{backgroundLabel(mode)}</option>)}
            </select>
            <span className="cn-sep" />
            <button type="button" className="cn-icon" disabled={!selection.size} onClick={() => duplicateIds(selection)} aria-label={t('就地复制')} title={t('就地复制')}><Copy aria-hidden="true" /></button>
            <button type="button" className="cn-icon" disabled={selection.size < 2} onClick={() => groupIds(selection)} aria-label={t('成组')} title={t('成组')}><Boxes aria-hidden="true" /></button>
            <button type="button" className="cn-icon" disabled={!selection.size && !edgeSelection.size} onClick={() => removeIds(selection, edgeSelection)} aria-label={t('删除所选')} title={t('删除所选')}><Trash2 aria-hidden="true" /></button>
            <span className="cn-sep" />
            <button type="button" className="cn-button is-primary" disabled={!selectedRunnable.length} onClick={() => { void runNodes(selectedRunnable); }}>
              <Play aria-hidden="true" /> {t('运行所选')}{selectedRunnable.length ? ` (${selectedRunnable.length})` : ''}
            </button>
            <button type="button" className="cn-button" disabled={!selection.size} onClick={() => { void openCommit([...selection]); }}>
              <Send aria-hidden="true" /> {t('提交所选')}{selection.size ? ` (${selection.size})` : ''}
            </button>
            <span className="cn-sep" />
            <button type="button" className="cn-icon" onClick={() => setStoryboarding(true)} aria-label={t('把分镜铺到画布')} title={t('把分镜铺到画布')}><Clapperboard aria-hidden="true" /></button>
            <button
              type="button" className={`cn-icon cn-sync-button${syncCount ? ' has-news' : ''}`} onClick={() => setSyncing(true)}
              aria-label={syncCount ? t('从项目同步（{0} 处变化）', [syncCount]) : t('从项目同步')} title={syncCount ? t('从项目同步（{0} 处变化）', [syncCount]) : t('从项目同步')}
            >
              <RefreshCw aria-hidden="true" />
              {syncCount > 0 && <span className="cn-badge" aria-hidden="true">{syncCount > 99 ? '99+' : syncCount}</span>}
            </button>
            <button type="button" className="cn-button cn-film-button" onClick={() => setFilming(true)} title={t('一键成片')}>
              <FilmIcon aria-hidden="true" /> {t('一键成片')}
            </button>
            <button type="button" className="cn-icon" onClick={() => setPicking(true)} aria-label={t('从元素库取用')} title={t('从元素库取用')}><Library aria-hidden="true" /></button>
            {nodeActions.toolbar}
            <button type="button" className="cn-icon" onClick={() => setExportingBoard(true)} aria-label={t('导出画布')} title={t('导出画布')}><Download aria-hidden="true" /></button>
            <button type="button" className="cn-icon" onClick={() => importInput.current?.click()} aria-label={t('导入画布')} title={t('导入画布')}><FileUp aria-hidden="true" /></button>
            <button type="button" className="cn-icon" onClick={() => setSharing(true)} aria-label={t('分享')} title={t('分享')}><Share2 aria-hidden="true" /></button>
            <input
              ref={importInput} type="file" hidden accept="application/json,.json,application/zip,.zip" aria-label={t('选择要导入的画布文件')}
              onChange={event => {
                const file = event.target.files?.[0];
                event.target.value = '';
                if (file) void importFile(file);
              }}
            />
            {runs.data.running > 0 && <span className="cn-status is-running">{t('{0} 个运行中', [runs.data.running])}</span>}
            <span className={`cn-save is-${status}`} role="status" title={status === 'error' ? document_.saveError : undefined}>
              {saveLabel(status)}{status === 'saved' && version ? ` · ${t('第 {0} 版', [version])}` : ''}
              {status === 'error' && document_.saveError ? `：${document_.saveError}` : ''}
            </span>
            {status === 'error' && !document_.loadError && <button type="button" className="cn-button" onClick={() => { void flush(); }}>{t('重试')}</button>}
            <CanvasPresencePeers peers={presence.peers} />
          </div>

          {status === 'conflict' && (
            <div className="cn-banner" role="alert">
              <strong>{t('这张画布已在别处被修改（其他窗口或助手）。')}</strong>
              <span>{t('你最近的修改还没保存，也没有覆盖任何内容。')}</span>
              <button type="button" className="cn-button" onClick={() => { void reload(); }}>{t('载入最新版本（放弃我的修改）')}</button>
              <button type="button" className="cn-button is-primary" onClick={() => { void forkConflict(); }}>{t('把我的版本另存为新画布')}</button>
              <CanvasBeefConflictActions
                projectId={projectId} canvasId={canvasId} mine={currentDoc()} clientId={presence.clientId}
                onOverwritten={record => { adopt(record); say(t('已用我的版本覆盖（第 {0} 版）', [record.version])); }}
              />
            </div>
          )}
          {document_.loadError && (
            <div className="cn-banner" role="alert">
              <strong>{document_.loadError}</strong>
              <button type="button" className="cn-button" onClick={() => { void reload(); }}>{t('重试')}</button>
            </div>
          )}

          <div
            className="cn-viewport" {...opening.gestures}
            data-board-theme={boardTheme ? appearance.theme : undefined} style={boardTheme ? appearanceStyle(boardTheme) : undefined}
          >
            <CanvasSurface
              ref={surface}
              nodes={doc.nodes}
              edges={doc.edges}
              selection={selection}
              edgeSelection={edgeSelection}
              initialView={null}
              background={background}
              flash={flash}
              renderNode={renderNode}
              onSelect={select}
              onMove={onMove}
              onResize={onResize}
              onConnect={onConnect}
              canConnect={canConnect}
              onConnectEmpty={onConnectEmpty}
              onMenu={onMenu}
              onViewSettled={view => rememberView(canvasId, view)}
              onDropFiles={placeFiles}
              onLivePointer={sendCursor}
              onLiveDrag={sendDrag}
              tool={tool}
            />
            {presence.peers.length > 0 && (
              <CanvasPresenceLayer
                surface={surface} peers={presence.peers} cursors={presence.cursors} drags={presence.drags} selections={presence.selections} nodes={shownNodes}
              />
            )}
            <SelectionToolbarHost
              surface={surface} nodes={shownNodes} selection={selection}
              onAlign={kind => applyLayout(align(currentDoc().nodes, selection, kind))}
              onDistribute={axis => applyLayout(distribute(currentDoc().nodes, selection, axis))}
              onArrange={kind => applyLayout(arrange(currentDoc(), selection, kind))}
              onGroup={() => groupIds(selection)}
              onUngroup={() => ungroupIds(selection)}
              onDuplicate={() => duplicateIds(selection)}
              onDelete={() => removeIds(selection, edgeSelection)}
              onConnectVideo={nodeActions.connectAction(selection)}
            />
            <CanvasBeefDocContext.Provider value={doc}>
              <CanvasComposerHost
                surface={surface} node={onlySelected ?? null} latest={onlySelected ? latest[onlySelected.id] : undefined}
                projectId={projectId} canvasId={canvasId} version={version} settled={status === 'saved' || status === 'idle'} refreshKey={String(runs.data.running)}
              />
            </CanvasBeefDocContext.Provider>
            <ZoomControlsHost surface={surface} hasSelection={selection.size > 0} onFitSelection={fitSelected} />
            {batching && (
              <CanvasBatchTable
                models={{ image: options?.enabled.image ?? [], video: options?.enabled.video ?? [] }}
                defaults={{ image: options?.models.image ?? '', video: options?.models.video ?? '' }}
                durations={options?.video_durations ?? []} maxCount={options?.versions?.max ?? 1}
                originOf={() => surface.current?.centre() ?? { x: 0, y: 0 }} makeId={() => makeId('n')}
                onCreate={async nodes => {
                  if (currentDoc().nodes.length + nodes.length > CANVAS_MAX_NODES) {
                    throw new Error(t('一张画布最多 {0} 个节点、{1} 条连线。', [CANVAS_MAX_NODES, CANVAS_MAX_EDGES]));
                  }
                  edit(current => ({ ...current, nodes: [...current.nodes, ...nodes] }));
                  setSelection(new Set(nodes.map(node => node.id)));
                  if (!await flush()) throw new Error(t('画布还没保存成功，先解决保存问题再运行。'));
                }}
                assess={ids => assessRun(projectId, canvasId, ids)}
                start={async (ids, confirmed) => {
                  const outcome = await startRun(projectId, canvasId, { nodeIds: ids, expectedVersion: currentVersion(), operationId: makeId('op'), confirm: true, confirmed });
                  if (outcome.status === 'started') runs.kick();
                  return outcome;
                }}
                onClose={() => setBatching(false)}
              />
            )}
            {previewing !== null && (
              <CanvasBeefVersionPreview
                projectId={projectId} canvasId={canvasId} version={previewing} current={doc}
                onRestore={older => { setPreviewing(null); void restore(older).catch(error => say(messageOf(error, t('恢复失败')))); }}
                onClose={() => setPreviewing(null)}
              />
            )}
          </div>

          <div className="cn-overlay-bottom">
            <MinimapHost surface={surface} nodes={shownNodes} selection={selection} />
            <BookmarkBar
              bookmarks={board.bookmarks}
              onJump={jumpBookmark}
              onSave={saveBookmark}
              onClear={slot => onBookmarks(board.bookmarks.filter(item => item.slot !== slot))}
            />
          </div>

          {sharing && <CanvasShareDialog projectId={projectId} canvasId={canvasId} canvasTitle={boardTitle} onClose={closeShare} />}
          {storyboarding && (
            <CanvasStoryboardDialog projectId={projectId} canvasId={canvasId} clientId={presence.clientId} prepare={prepareStoryboard} onApplied={reloadAndShow} onClose={closeStoryboard} />
          )}
          {exportingBoard && (
            <CanvasExportDialog projectId={projectId} canvasId={canvasId} title={boardTitle} prepare={prepareStoryboard} onExportJson={exportBoard} onClose={closeExport} />
          )}
          {syncing && (
            <CanvasProjectSyncDialog
              projectId={projectId} canvasId={canvasId} clientId={presence.clientId} prepare={prepareStoryboard} onApplied={reloadAndShow} onClose={closeSync}
              onJump={id => {
                closeSync();
                surface.current?.focusNode(id);
                setSelection(new Set([id]));
                setEdgeSelection(new Set());
              }}
            />
          )}
          {filming && (
            <CanvasFilmDialog
              projectId={projectId} canvasId={canvasId} clientId={presence.clientId} prepare={prepareStoryboard} onBuilt={filmBuilt} onClose={closeFilm}
              selectedClips={[...selection].filter(id => doc.nodes.find(node => node.id === id)?.kind === 'video_gen')}
            />
          )}
          {picking && (
            <CanvasElementPickerDialog projectId={projectId} canvasId={canvasId} prepare={prepareStoryboard} onApplied={onElementsTaken} onClose={closePicking} />
          )}
          {savingElement && (
            <CanvasSaveElementDialog
              projectId={projectId} canvasId={canvasId} nodeId={savingElement.nodeId} defaultName={savingElement.name} previewUrl={savingElement.url}
              prepare={prepareStoryboard} onSaved={onElementSaved} onClose={closeSavingElement}
            />
          )}
          {nodeActions.dialogs}
          {notice && (
            <div className="cn-notice" role="status">
              {notice}
              <button type="button" className="cn-button is-quiet" onClick={() => setNotice('')} aria-label={t('关闭提示')}><X aria-hidden="true" /></button>
            </div>
          )}
          {help && (
            <aside className="cn-help" aria-label={t('快捷键')}>
              <h3>{t('快捷键')}</h3>
              {shortcutGroups().map(group => (
                <section key={group.id}>
                  <h4>{group.label}</h4>
                  <dl>{group.items.map(item => <div key={item.id}><dt>{item.keys.join(' / ')}</dt><dd>{item.what}</dd></div>)}</dl>
                </section>
              ))}
            </aside>
          )}
        </div>

        <aside className={`cn-side${panel ? '' : ' is-collapsed'}`}>
          <div className="cn-tabs" role="tablist" aria-label={t('侧栏')}>
            {([['inspector', t('属性'), SlidersHorizontal], ['outline', t('大纲'), ListTree], ['versions', t('版本'), History], ['workflow', t('工作流'), Workflow], ['assistant', t('助手'), Bot]] as const).map(([id, label, Icon]) => (
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
              onSaveElement={savablePicture(onlySelected, doc, outputs) ? () => openSaveElement(onlySelected.id) : undefined}
              extraActions={<>
                {nodeActions.inspectorActions(onlySelected, doc, outputs)}
                {referenceLimits && onlySelected.kind === 'video_gen' && (
                  <CanvasBeefReferencePanel
                    target={onlySelected} nodes={doc.nodes} edges={doc.edges} limits={referenceLimits}
                    onApply={suggestions => edit(current => ({ ...current, edges: applySuggestions(current.edges, suggestions) }))}
                  />
                )}
              </>}
            />
          ) : (
            <section className="cn-panel"><p className="cn-hint">{selection.size ? t('已选中 {0} 个节点', [selection.size]) : t('选中一个节点查看属性和生成记录。')}</p></section>
          ))}
          {panel === 'outline' && (
            <OutlinePanel nodes={doc.nodes} selection={selection} onJump={id => { surface.current?.focusNode(id); setSelection(new Set([id])); setEdgeSelection(new Set()); }} />
          )}
          {panel === 'versions' && <VersionsPanel projectId={projectId} canvasId={canvasId} version={version} onRestore={restore} onPreview={setPreviewing} />}
          {panel === 'workflow' && (
            <WorkflowPanel
              projectId={projectId} canvasId={canvasId} refreshKey={`${version}:${JSON.stringify(latest)}`} flush={flush} currentVersion={currentVersion}
              onApplied={reloadAndShow} onRun={nodeIds => { void runNodes(nodeIds); }}
              onJump={id => { surface.current?.focusNode(id); setSelection(new Set([id])); setEdgeSelection(new Set()); }}
            />
          )}
          {/* Kept mounted so the conversation survives a look at another tab. */}
          <CanvasChatPanel
            taskId={taskId} canvasId={canvasId} selected={selectedNodes} hidden={panel !== 'assistant'} flush={flush}
            onCanvasChanged={remote => onRemoteVersion(remote)}
            onJump={id => { surface.current?.focusNode(id); setSelection(new Set([id])); setEdgeSelection(new Set()); }}
          />
        </aside>

        {menu && <CanvasContextMenu x={menu.x} y={menu.y} items={menu.items} label={menu.label} onClose={closeMenu} />}
        {opening.dialog}
        <CanvasSearchDialog open={search} nodes={doc.nodes} onJump={jumpToHit} onClose={() => setSearch(false)} />
        {assessment && <RunDialog assessment={assessment.value} onClose={closeAssessment} onConfirm={confirmRun} />}
        {commit && <CommitDialog projectId={projectId} canvasId={canvasId} nodeIds={commit} onClose={closeCommit} onCommit={sendCommit} />}
        {desk && (
          <Suspense fallback={<DeskLoading />}>
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
export function CanvasWorkspace({ taskId, onClose, onOpenShot }: { taskId: string; onClose: () => void; onOpenShot?: (shot: BoundShot) => void }) {
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
  const [modelsOpen, setModelsOpen] = useState(false);
  const closeModels = useCallback(() => setModelsOpen(false), []);
  // The models changed: what each node offers (and its 项目默认) is read again.
  const modelsSaved = useCallback(() => {
    if (projectId) fetchRunOptions(projectId).then(setOptions).catch(() => undefined);
  }, [projectId]);
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

  // A card's shot opens in the project behind this window: save first, as closing does.
  const openShot = useCallback(async (shot: BoundShot) => {
    if (!onOpenShot) return;
    if (await (editor.current?.flush() ?? Promise.resolve(true))) onOpenShot(shot);
    else setCloseBlocked(true);
  }, [onOpenShot]);

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
        {projectId && (
          <button type="button" className="cn-button" onClick={() => setModelsOpen(true)} title={t('项目模型')}>
            <Cpu aria-hidden="true" /> {t('模型')}
          </button>
        )}
        <button type="button" className="cn-icon" onClick={toggleTheme} aria-label={theme === 'dark' ? t('切换到浅色') : t('切换到深色')} title={theme === 'dark' ? t('切换到浅色') : t('切换到深色')}>
          {theme === 'dark' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
        </button>
        <button type="button" className="cn-button" onClick={() => { void close(); }}><X aria-hidden="true" /> {t('关闭')}</button>
      </header>
      {projectId && board ? (
        <CanvasEditor
          key={board.id} ref={editor} taskId={taskId} projectId={projectId} board={board} options={options} shots={shots}
          onBookmarks={onBookmarks} onForked={onForked} onVersion={onVersion} onOpenShot={onOpenShot ? openShot : undefined}
        />
      ) : (
        !problem && <p className="cn-loading">{t('读取中…')}</p>
      )}
      {modelsOpen && projectId && <CanvasModelsDialog projectId={projectId} onSaved={modelsSaved} onClose={closeModels} />}
    </div>
  );
}
