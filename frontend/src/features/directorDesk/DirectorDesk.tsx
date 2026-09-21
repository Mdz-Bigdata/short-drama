import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react';
import { createPortal } from 'react-dom';
import {
  Camera, Columns2, Download, Eye, Keyboard, Magnet, Maximize, MousePointer2, Move3d, PersonStanding, Redo2, RefreshCw,
  Rotate3d, Ruler, Undo2, Upload, X,
} from 'lucide-react';

import { parseAspect } from '../spatial/floorPlanGeometry';
import { exportSpatialPlan, importSpatialPlan, type SpatialExportFormat } from '../spatial/spatialApi';
import { FUNCTION_LABELS, actorsInShot, type LandmarkShape, type StageOperation } from '../spatial/spatialTypes';
import { applyAll, backdropOf } from './deskOperations';
import { refKey, type DeskLayout, type DeskTool, type DeskViewHandle, type LensFrameInfo, type LensHandle, type SelectionRef } from './deskTypes';
import { anglePresetCamera, type AnglePresetId } from './lib/anglePresets';
import type { ClipStage } from './lib/clipExport';
import { cameraPathOf, stagePlanAt, timelineOf } from './lib/sampling';
import { snapToGrid } from './lib/snapping';
import { keyIndexAtFrame, retargetToKeys } from './lib/timelineEdits';
import { CompositionGuides } from './overlays/CompositionGuides';
import { BackdropSection } from './panels/BackdropSection';
import { CameraPanel } from './panels/CameraPanel';
import { CapturesPanel } from './panels/CapturesPanel';
import { CrowdDialog, type CrowdRequest } from './panels/CrowdDialog';
import { Inspector } from './panels/Inspector';
import { Outliner } from './panels/Outliner';
import { PosePanel } from './panels/PosePanel';
import { TimelinePanel } from './panels/TimelinePanel';
import { SHAPE_LABELS } from './three/stageLook';
import { useDeskPlayback } from './useDeskPlayback';
import { useDeskSession } from './useDeskSession';
import './DirectorDesk.css';

// three.js only loads once a stage is actually on screen.
const DeskViewport = lazy(() => import('./three/DeskViewport'));
const LensViewport = lazy(() => import('./three/LensViewport'));

type SideTab = 'inspector' | 'pose' | 'camera' | 'captures';

const LAYOUTS: Array<{ id: DeskLayout; label: string; icon: typeof Eye }> = [
  { id: 'director', label: '导演', icon: Eye }, { id: 'split', label: '并排', icon: Columns2 }, { id: 'lens', label: '机位', icon: Camera },
];
const TOOLS: Array<{ id: DeskTool; label: string; key: string; icon: typeof Eye }> = [
  { id: 'select', label: '选择', key: 'v', icon: MousePointer2 }, { id: 'move', label: '移动', key: 'w', icon: Move3d },
  { id: 'rotate', label: '旋转', key: 'e', icon: Rotate3d }, { id: 'scale', label: '缩放', key: 'r', icon: Maximize },
  { id: 'pose', label: '姿势', key: 'p', icon: PersonStanding }, { id: 'measure', label: '测量', key: 'm', icon: Ruler },
];
const SHORTCUTS: Array<[string, string]> = [
  ['V', '选择'], ['W', '移动'], ['E', '旋转'], ['R', '缩放'], ['M', '测量'], ['P', '姿势'],
  ['1 / 2 / 3', '导演 / 并排 / 机位视图'], ['空格', '播放或暂停'], ['Delete', '删除所选'],
  ['Ctrl / ⌘ + Z', '撤销'], ['Ctrl / ⌘ + Shift + Z', '重做'], ['Esc', '依次退出测量、选择，再关闭导演台'],
];
/** A project file bigger than this is not one of ours; the same limit the spatial dialog uses. */
const MAX_IMPORT_BYTES = 5 * 1024 * 1024;
const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])';
const SIDE_TABS: Array<{ id: SideTab; label: string }> = [{ id: 'inspector', label: '属性' }, { id: 'pose', label: '姿势' }, { id: 'camera', label: '机位' }, { id: 'captures', label: '截图库' }];
// A lens scene that has not shown the instant it was asked for within this long never will.
const FRAME_TIMEOUT_MS = 8000;
const SAVE_LABELS = { idle: '', saving: '保存中…', saved: '已保存', error: '未保存' } as const;
const DEFAULT_SIZES: Record<LandmarkShape, [number, number, number]> = {
  box: [1, 1, 1], cylinder: [0.6, 0.6, 1], sphere: [0.6, 0.6, 0.6], cone: [0.6, 0.6, 1], wedge: [1, 1.5, 0.5], plane: [2, 0.05, 2],
};

function typing(target: EventTarget | null) {
  return target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));
}

function freeName(base: string, taken: Set<string>) {
  let number = 1;
  while (taken.has(`${base} ${number}`)) number += 1;
  return `${base} ${number}`;
}

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function DirectorDesk({ taskId, sceneId, initialShotId, onClose }: {
  taskId: string;
  sceneId: string;
  initialShotId?: number;
  onClose: () => void;
}) {
  const { state, dispatch, commit, undo, redo, reload, editable } = useDeskSession(taskId, sceneId);
  // The drag (or slider) in progress: drawn in both views, sent to nobody until it is let go.
  const [preview, setPreview] = useState<StageOperation[] | null>(null);
  const [sideTab, setSideTab] = useState<SideTab>('inspector');
  const [crowdOpen, setCrowdOpen] = useState(false);
  const [poseShotOnly, setPoseShotOnly] = useState(false);
  const [footLock, setFootLock] = useState(true);
  const [viewReady, setViewReady] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  // The backdrop is a framing reference, so it is left out of what goes to generation by default.
  const [backdropInCapture, setBackdropInCapture] = useState(false);
  const [transferBusy, setTransferBusy] = useState(false);
  const deskHandle = useRef<DeskViewHandle | null>(null);
  const lensHandle = useRef<LensHandle | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const projectFile = useRef<HTMLInputElement>(null);
  const wantedShot = useRef(initialShotId);

  const [timelineCollapsed, setTimelineCollapsed] = useState(false);
  // A clip export drives the stage one instant at a time; while it does, the playhead is not asked.
  const [exportFrame, setExportFrame] = useState<{ stamp: number; time: number } | null>(null);
  const frameWaiters = useRef(new Map<number, (info: LensFrameInfo) => void>());
  const frameStamp = useRef(0);

  const { plan: basePlan, selection, tool, layout } = state;
  const shotId = state.shotId;
  // Three plans: `basePlan` is what is stored (unconfirmed edits included), `storedPlan` adds the
  // drag in progress, and `plan` is `storedPlan` as it looks at the playhead — what gets drawn.
  const storedPlan = useMemo(() => (basePlan && preview ? applyAll(basePlan, preview) : basePlan), [basePlan, preview]);
  const timeline = useMemo(() => timelineOf(storedPlan ?? {}, shotId), [shotId, storedPlan]);
  const playback = useDeskPlayback(timeline.duration_s, timeline.fps, `${sceneId}:${shotId ?? ''}`);
  const now = exportFrame ? exportFrame.time : playback.time;
  const plan = useMemo(() => (storedPlan ? stagePlanAt(storedPlan, shotId, now) : storedPlan), [now, shotId, storedPlan]);
  const stagedBase = useMemo(() => (basePlan ? stagePlanAt(basePlan, shotId, now) : basePlan), [basePlan, now, shotId]);
  const shot = useMemo(() => plan?.shots.find(item => item.shot_id === shotId), [plan, shotId]);
  const storedShot = useMemo(() => storedPlan?.shots.find(item => item.shot_id === shotId), [shotId, storedPlan]);
  const lens = plan?.cameras.find(item => item.id === (state.lensCameraId || shot?.camera_id));
  const cameraPath = useMemo(() => (storedPlan ? cameraPathOf(storedPlan, storedShot) : null), [storedPlan, storedShot]);
  const primary = selection[selection.length - 1];
  const exporting = exportFrame !== null;

  // Which track the selected thing is on, and whether the playhead sits on one of its keys: that decides
  // whether an edit lands in the key or in the base plan, and the side panels say so.
  const primaryKeys = primary?.kind === 'actor' ? timeline.actors[primary.name]
    : (primary?.kind === 'camera' || primary?.kind === 'camera-target') && primary.id === storedShot?.camera_id ? timeline.camera : undefined;
  const onKey = Boolean(primaryKeys?.length) && keyIndexAtFrame(primaryKeys || [], playback.frame, timeline.fps) >= 0;
  const keyNote = !primaryKeys?.length ? ''
    : onKey ? '播放头停在这条轨道的关键帧上：移动、旋转和数值修改都写入这一帧。'
      : '这条轨道有关键帧，而播放头不在关键帧上：现在的修改写入基础站位，画面仍按关键帧显示。要改动画，请先在时间线「打关键帧」，再调整。';
  // On a key the panels show (and edit) what the key holds; anywhere else, the base plan they would write to.
  const panelPlan = onKey ? plan : storedPlan;
  const panelShot = onKey ? shot : storedShot;

  // The storyboard opens the desk on the shot it was looking at.
  useEffect(() => {
    if (wantedShot.current !== undefined && basePlan?.shots.some(item => item.shot_id === wantedShot.current)) {
      dispatch({ type: 'setShot', shotId: wantedShot.current });
    }
    if (basePlan) wantedShot.current = undefined;
  }, [basePlan, dispatch]);

  const baseShot = useMemo(() => basePlan?.shots.find(item => item.shot_id === shotId), [basePlan, shotId]);
  const retarget = useCallback((operations: StageOperation[]) => (
    basePlan ? retargetToKeys(basePlan, baseShot, playback.time, operations).operations : operations
  ), [basePlan, baseShot, playback.time]);
  const previewEdit = useCallback((operations: StageOperation[] | null) => setPreview(operations ? retarget(operations) : null), [retarget]);
  const commitEdit = useCallback((request: Parameters<typeof commit>[0]) => {
    setPreview(null);
    commit({ ...request, operations: retarget(request.operations) });
  }, [commit, retarget]);

  const onFrameShown = useCallback((stamp: number, info: LensFrameInfo) => {
    const waiter = frameWaiters.current.get(stamp);
    frameWaiters.current.delete(stamp);
    waiter?.(info);
  }, []);
  // Whoever is still waiting for a frame when the desk closes is waiting for nothing.
  useEffect(() => {
    const waiters = frameWaiters.current;
    return () => waiters.clear();
  }, []);
  const pausePlayback = playback.pause;
  const getClipStage = useCallback((): ClipStage | null => {
    const handle = lensHandle.current;
    if (!handle) return null;
    pausePlayback();
    return {
      ...handle.renderer(),
      showFrame: time => new Promise((resolve, reject) => {
        frameStamp.current += 1;
        const stamp = frameStamp.current;
        const timer = window.setTimeout(() => {
          frameWaiters.current.delete(stamp);
          reject(new Error('机位画面没有响应，导出已中止；请保持「并排」或「机位」布局后重试。'));
        }, FRAME_TIMEOUT_MS);
        frameWaiters.current.set(stamp, info => { window.clearTimeout(timer); resolve(info); });
        setExportFrame({ stamp, time });
      }),
      release: () => {
        frameWaiters.current.clear();
        setExportFrame(null);
      },
    };
  }, [pausePlayback]);

  const removeSelected = useCallback(() => {
    if (!basePlan || !primary || !editable) return;
    if (primary.kind === 'landmark') commitEdit({ label: `删除 ${primary.name}`, operations: [{ op: 'remove_landmark', name: primary.name }] });
    if (primary.kind === 'camera' && shot?.alt_camera_ids?.includes(primary.id)) commitEdit({ label: '删除候选机位', operations: [{ op: 'remove_camera', camera_id: primary.id }], barrier: true });
  }, [basePlan, commitEdit, editable, primary, shot]);

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    // The desk covers the page, so Tab has to stay inside it: anything behind is not reachable anyway.
    const trap = (event: KeyboardEvent) => {
      const root = rootRef.current;
      if (event.key !== 'Tab' || !root) return;
      const stops = [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(item => item.offsetParent !== null || item === document.activeElement);
      if (!stops.length) return;
      const [first, last] = [stops[0], stops[stops.length - 1]];
      const active = document.activeElement;
      if (!event.shiftKey && (active === last || !root.contains(active))) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && (active === first || !root.contains(active))) {
        event.preventDefault();
        last.focus();
      }
    };
    document.addEventListener('keydown', trap, true);
    return () => {
      document.removeEventListener('keydown', trap, true);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, []);

  // Posing happens with the joints in view: the tool brings its panel along.
  const pickTool = useCallback((next: DeskTool) => {
    dispatch({ type: 'setTool', tool: next });
    if (next === 'pose') setSideTab('pose');
  }, [dispatch]);

  const togglePlay = playback.playing ? playback.pause : playback.play;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (typing(event.target) || crowdOpen || exporting) return;
      const key = event.key.toLowerCase();
      if ((event.metaKey || event.ctrlKey) && key === 'z') {
        event.preventDefault();
        if (event.shiftKey) redo(); else undo();
        return;
      }
      if ((event.metaKey || event.ctrlKey) && key === 'y') { event.preventDefault(); redo(); return; }
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      // Escape backs out one step at a time; the last step is closing the desk.
      if (key === 'escape') {
        if (shortcutsOpen) setShortcutsOpen(false);
        else if (state.measure.length) dispatch({ type: 'clearMeasure' });
        else if (selection.length) dispatch({ type: 'clearSelection' });
        else onClose();
        return;
      }
      if (key === 'delete' || key === 'backspace') { removeSelected(); return; }
      if (key === ' ') { event.preventDefault(); togglePlay(); return; }
      if (key === '?' || (key === '/' && event.shiftKey)) { setShortcutsOpen(value => !value); return; }
      const layout = LAYOUTS[['1', '2', '3'].indexOf(key)];
      if (layout) { dispatch({ type: 'setLayout', layout: layout.id }); return; }
      const wanted = TOOLS.find(item => item.key === key);
      if (wanted) pickTool(wanted.id);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [crowdOpen, dispatch, exporting, onClose, pickTool, redo, removeSelected, selection.length, shortcutsOpen, state.measure.length, togglePlay, undo]);

  const downloadProject = (format: SpatialExportFormat) => {
    if (transferBusy) return;
    setTransferBusy(true);
    void exportSpatialPlan(taskId, sceneId, format)
      .then(data => {
        const url = URL.createObjectURL(new Blob([JSON.stringify(data.document, null, 2)], { type: 'application/json' }));
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = data.fileName;
        anchor.click();
        URL.revokeObjectURL(url);
        dispatch({ type: 'notice', message: data.note || '已导出本场工程。' });
      })
      .catch(error => dispatch({ type: 'notice', message: messageOf(error, '导出失败。') }))
      .finally(() => setTransferBusy(false));
  };

  const uploadProject = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || !basePlan || transferBusy) return;
    if (file.size > MAX_IMPORT_BYTES) { dispatch({ type: 'notice', message: '工程文件不能超过 5 MB。' }); return; }
    let document: unknown;
    try {
      document = JSON.parse(await file.text());
    } catch {
      dispatch({ type: 'notice', message: '工程文件不是合法的 JSON。' });
      return;
    }
    setTransferBusy(true);
    try {
      await importSpatialPlan(taskId, sceneId, basePlan.revision, document);
      // The import is a server-side edit of its own, so the session starts again from what it wrote.
      await reload();
      dispatch({ type: 'notice', message: '已按工程文件更新站位与机位；背景与模型绑定不在工程格式里，保持不变。' });
    } catch (error) {
      dispatch({ type: 'notice', message: messageOf(error, '导入失败。') });
    } finally {
      setTransferBusy(false);
    }
  };

  const select = useCallback((ref: SelectionRef, additive: boolean) => {
    dispatch({ type: 'select', ref, additive });
    if (ref.kind === 'camera' || ref.kind === 'camera-target') setSideTab(current => (current === 'captures' ? current : 'inspector'));
  }, [dispatch]);
  const onDeskReady = useCallback((handle: DeskViewHandle | null) => { deskHandle.current = handle; setViewReady(Boolean(handle)); }, []);
  const onLensReady = useCallback((handle: LensHandle | null) => { lensHandle.current = handle; }, []);
  const getLens = useCallback(() => lensHandle.current, []);

  /** Where new things land: under the point the director view is orbiting, on the grid. */
  const dropPoint = (): [number, number] => {
    const target = deskHandle.current?.viewPose().target;
    return snapToGrid(target ? [target[0], target[2]] : [0, 0], state.snap.gridSize);
  };

  const addProp = (shape: LandmarkShape) => {
    if (!basePlan) return;
    const name = freeName(SHAPE_LABELS[shape], new Set([...basePlan.landmarks.map(item => item.name), ...basePlan.actors.map(actor => actor.name)]));
    commitEdit({
      label: `添加 ${name}`,
      operations: [{ op: 'add_landmark', name, kind: 'prop', shape, position: dropPoint(), size: DEFAULT_SIZES[shape], yaw_deg: 0, color: '' }],
    });
    dispatch({ type: 'select', ref: { kind: 'landmark', name } });
    setSideTab('inspector');
  };

  const addCrowd = (request: CrowdRequest) => {
    setCrowdOpen(false);
    commitEdit({ label: `添加群演 ${request.label}`, operations: [{ op: 'add_crowd', ...request, center: dropPoint(), yaw_deg: 0 }], barrier: true });
  };

  const addCameraFromView = () => {
    const pose = deskHandle.current?.viewPose();
    if (!pose || !shot) return;
    commitEdit({ label: '从当前视角添加机位', operations: [{ op: 'add_camera', shot_id: shot.shot_id, position: pose.position, target: pose.target, lens_mm: 35 }], barrier: true });
  };

  const addPresetCamera = (preset: AnglePresetId) => {
    if (!basePlan || !shot) return;
    const cast = actorsInShot(basePlan, shot).filter(actor => !actor.crowd_id);
    const subjects = shot.subjects.flatMap(name => cast.filter(actor => actor.name === name));
    const placement = anglePresetCamera(preset, subjects, parseAspect(basePlan.aspect_ratio), cast.filter(actor => !shot.subjects.includes(actor.name)));
    if (!placement) return;
    commitEdit({ label: `添加${placement.label}机位`, operations: [{ op: 'add_camera', shot_id: shot.shot_id, ...placement, label: `第${shot.shot_id}镜 · ${placement.label}` }], barrier: true });
  };

  const measured = state.measure.length === 2
    ? Math.hypot(...state.measure[0].point.map((value, index) => value - state.measure[1].point[index]))
    : null;

  const canEdit = editable && !exporting;

  const body = () => {
    if (state.loadError) {
      return (
        <div className="desk-empty" role="alert">
          <p>{state.loadError}</p>
          <button type="button" className="desk-button" onClick={() => { void reload(); }}><RefreshCw aria-hidden="true" /> 重新读取</button>
        </div>
      );
    }
    if (!plan || !basePlan || !storedPlan || !stagedBase || !panelPlan) return <p className="desk-empty" role="status">正在读取空间舞台…</p>;
    const loading = <p className="desk-empty" role="status">正在加载 3D 视图…</p>;
    return (
      <div className="desk-body">
        <Outliner
          plan={storedPlan} shot={storedShot} selection={selection} hidden={state.hidden} locked={state.locked} editable={canEdit}
          onSelect={select}
          onToggleHidden={key => dispatch({ type: 'toggleHidden', key })}
          onToggleLocked={key => dispatch({ type: 'toggleLocked', key })}
          onAddProp={addProp} onAddCrowd={() => setCrowdOpen(true)}
        />
        <main className={`desk-stage is-${layout}`}>
          {layout !== 'lens' && (
            <Suspense fallback={loading}>
              <DeskViewport
                plan={plan} basePlan={stagedBase} shot={shot} selection={selection} tool={tool} snap={state.snap}
                hidden={state.hidden} locked={state.locked} readOnly={!canEdit} measure={state.measure} lensCameraId={lens?.id || ''}
                poseShotOnly={poseShotOnly} footLock={footLock} cameraPath={cameraPath} playing={playback.playing}
                onSelect={select} onClearSelection={() => dispatch({ type: 'clearSelection' })}
                onPreview={previewEdit}
                onCommit={operations => commitEdit({ label: tool === 'pose' ? '摆姿势' : tool === 'rotate' ? '旋转' : tool === 'scale' ? '缩放' : '移动', operations })}
                onMeasure={point => dispatch({ type: 'measure', point })}
                onReady={onDeskReady}
              />
            </Suspense>
          )}
          {layout !== 'director' && (
            <Suspense fallback={loading}>
              <LensViewport
                plan={plan} shot={shot} camera={lens} hidden={state.hidden} onReady={onLensReady}
                frameStamp={exportFrame?.stamp} onFrameShown={onFrameShown} backdropInCapture={backdropInCapture}
                overlay={<CompositionGuides deliveryAspect={parseAspect(plan.aspect_ratio)} guides={state.guides} />}
              />
            </Suspense>
          )}
        </main>
        <aside className="desk-side" aria-label="属性与机位">
          <div className="desk-side__tabs" role="tablist" aria-label="右侧面板">
            {SIDE_TABS.map(item => (
              <button key={item.id} type="button" role="tab" aria-selected={sideTab === item.id} className={sideTab === item.id ? 'is-active' : ''} onClick={() => setSideTab(item.id)}>{item.label}</button>
            ))}
          </div>
          <div className="desk-side__panel">
            {keyNote && sideTab !== 'captures' && <p className={`desk-keynote ${onKey ? 'is-key' : ''}`} role="note">{keyNote}</p>}
            {sideTab === 'inspector' && <Inspector plan={panelPlan} shot={panelShot} selection={selection} editable={canEdit} error={state.inspectorError} taskId={taskId} onCommit={commitEdit} onSelect={select} />}
            {sideTab === 'pose' && (
              <PosePanel
                plan={panelPlan} shot={panelShot} selection={selection} editable={canEdit} shotOnly={poseShotOnly} footLock={footLock}
                onShotOnly={setPoseShotOnly} onFootLock={setFootLock} onCommit={commitEdit} onPreview={previewEdit}
              />
            )}
            {sideTab === 'camera' && (
              <CameraPanel
                plan={panelPlan} shot={panelShot} lens={panelPlan.cameras.find(item => item.id === lens?.id)} guides={state.guides} editable={canEdit} canUseView={viewReady && layout !== 'lens'}
                backdrop={(
                  <BackdropSection
                    taskId={taskId} sceneId={sceneId} backdrop={backdropOf(storedPlan)} editable={canEdit}
                    inCapture={backdropInCapture} onInCapture={setBackdropInCapture} onCommit={commitEdit} onPreview={previewEdit}
                  />
                )}
                onCommit={commitEdit} onPreview={previewEdit}
                onLook={cameraId => dispatch({ type: 'setLensCamera', cameraId })}
                onAddFromView={addCameraFromView} onAddPreset={addPresetCamera}
                onGuides={guides => dispatch({ type: 'setGuides', guides })}
              />
            )}
            {sideTab === 'captures' && (
              <CapturesPanel
                taskId={taskId} sceneId={sceneId} shotId={shotId} camera={lens} cameras={storedPlan.cameras}
                planRevision={basePlan.revision} saving={state.pending.length > 0} getLens={getLens}
                aspect={parseAspect(storedPlan.aspect_ratio)} durationS={timeline.duration_s} fps={timeline.fps} getClipStage={getClipStage}
              />
            )}
            {/* A 422 must be seen wherever the user is, not only on the tab that caused it. */}
            {sideTab !== 'inspector' && state.inspectorError && <p className="desk-inspector__error" role="alert">{state.inspectorError}</p>}
          </div>
        </aside>
      </div>
    );
  };

  return createPortal(
    <div ref={rootRef} className="director-desk" role="dialog" aria-modal="true" aria-labelledby="director-desk-title">
      <header className="desk-topbar">
        <div className="desk-topbar__title">
          <span>DIRECTOR DESK / 3D 导演台</span>
          <h1 id="director-desk-title">{sceneId} · {basePlan?.location || '3D 导演台'}</h1>
        </div>
        {basePlan && (
          <label className="desk-topbar__shot">
            <span>镜头</span>
            <select aria-label="镜头" value={shotId ?? ''} onChange={event => dispatch({ type: 'setShot', shotId: Number(event.target.value) })}>
              {basePlan.shots.map(item => <option key={item.shot_id} value={item.shot_id}>第 {item.shot_id} 镜 · {FUNCTION_LABELS[item.function]} · {item.subjects.join('、') || '空镜'}</option>)}
            </select>
          </label>
        )}
        <div className="desk-segment" role="radiogroup" aria-label="视图布局">
          {LAYOUTS.map(item => (
            <button key={item.id} type="button" role="radio" aria-checked={layout === item.id} className={layout === item.id ? 'is-active' : ''} onClick={() => dispatch({ type: 'setLayout', layout: item.id })}>
              <item.icon aria-hidden="true" /> {item.label}
            </button>
          ))}
        </div>
        <div className="desk-segment" role="radiogroup" aria-label="工具">
          {TOOLS.map(item => (
            <button key={item.id} type="button" role="radio" aria-checked={tool === item.id} title={`${item.label}（${item.key.toUpperCase()}）`} className={tool === item.id ? 'is-active' : ''} onClick={() => pickTool(item.id)}>
              <item.icon aria-hidden="true" /> {item.label}
            </button>
          ))}
        </div>
        <div className="desk-topbar__snap" role="group" aria-label="吸附">
          <Magnet aria-hidden="true" />
          <label><input type="checkbox" checked={state.snap.grid} onChange={event => dispatch({ type: 'setSnap', snap: { grid: event.target.checked } })} /> 网格</label>
          <select aria-label="网格间距" value={state.snap.gridSize} onChange={event => dispatch({ type: 'setSnap', snap: { gridSize: Number(event.target.value) } })}>
            {[0.1, 0.25, 0.5, 1].map(value => <option key={value} value={value}>{value} m</option>)}
          </select>
          <label><input type="checkbox" checked={state.snap.faces} onChange={event => dispatch({ type: 'setSnap', snap: { faces: event.target.checked } })} /> 贴面</label>
          <label><input type="checkbox" checked={state.snap.angle} onChange={event => dispatch({ type: 'setSnap', snap: { angle: event.target.checked } })} /> 15°</label>
        </div>
        <div className="desk-topbar__actions">
          <button type="button" className="desk-icon" aria-label="撤销" title={state.undo.length ? `撤销：${state.undo[state.undo.length - 1].label}` : '撤销'} disabled={!editable || !state.undo.length} onClick={undo}><Undo2 aria-hidden="true" /></button>
          <button type="button" className="desk-icon" aria-label="重做" title={state.redo.length ? `重做：${state.redo[state.redo.length - 1].label}` : '重做'} disabled={!editable || !state.redo.length} onClick={redo}><Redo2 aria-hidden="true" /></button>
          <span className={`desk-topbar__save is-${state.saveState}`} role="status" aria-label="保存状态">
            {SAVE_LABELS[state.saveState]}{basePlan ? `${SAVE_LABELS[state.saveState] ? ' · ' : ''}第 ${basePlan.revision} 版` : ''}
          </span>
          <div className="desk-topbar__transfer" role="group" aria-label="工程文件">
            <button type="button" className="desk-icon" aria-label="导出 3D 导演台工程" title="导出 3D 导演台工程（JSON）" disabled={!basePlan || transferBusy} onClick={() => downloadProject('director-desk')}><Download aria-hidden="true" /></button>
            <button type="button" className="desk-icon" aria-label="导出 CoStage 工程" title="导出 CoStage 工程（JSON）" disabled={!basePlan || transferBusy} onClick={() => downloadProject('costage')}><Download aria-hidden="true" /><span aria-hidden="true">C</span></button>
            <button type="button" className="desk-icon" aria-label="导入工程文件" title="导入 3D 导演台 / CoStage 工程" disabled={!editable || transferBusy} onClick={() => projectFile.current?.click()}><Upload aria-hidden="true" /></button>
            <input ref={projectFile} type="file" accept="application/json,.json" hidden aria-label="导入导演台工程文件" onChange={event => { void uploadProject(event); }} />
          </div>
          <button type="button" className="desk-icon" aria-label="快捷键" aria-expanded={shortcutsOpen} title="快捷键（?）" onClick={() => setShortcutsOpen(value => !value)}><Keyboard aria-hidden="true" /></button>
          <button type="button" className="desk-icon" aria-label="重新读取" onClick={() => { void reload(); }}><RefreshCw aria-hidden="true" /></button>
          <button ref={closeRef} type="button" className="desk-icon" aria-label="关闭 3D 导演台" onClick={onClose}><X aria-hidden="true" /></button>
        </div>
        {shortcutsOpen && (
          <div className="desk-shortcuts" role="dialog" aria-label="快捷键">
            <h2>快捷键</h2>
            <dl>
              {SHORTCUTS.map(([key, what]) => <div key={key}><dt><kbd>{key}</kbd></dt><dd>{what}</dd></div>)}
            </dl>
            <button type="button" className="desk-button" onClick={() => setShortcutsOpen(false)}>知道了</button>
          </div>
        )}
      </header>
      {state.readOnly && (
        <p className="desk-banner is-locked" role="alert">
          只读：{state.readOnly}。生成结束后点「重新读取」即可继续编辑。
        </p>
      )}
      {state.response && !state.response.persisted && <p className="desk-banner">本场尚未保存空间方案，当前为按剧本即时规划的预览；第一次调整后会保存。</p>}
      {state.response?.boardStale && <p className="desk-banner is-warning">站位已修改，本场已完成的九宫格仍按旧站位绘制。</p>}
      {state.notice && <p className="desk-banner is-warning" role="status">{state.notice}</p>}
      {exporting && <p className="desk-banner is-warning" role="status">正在逐帧导出白模视频，舞台暂时不能编辑。</p>}
      {body()}
      {storedPlan && (
        <TimelinePanel
          plan={storedPlan} shot={storedShot} playback={playback} selection={selection} editable={canEdit}
          collapsed={timelineCollapsed} onCollapsed={setTimelineCollapsed} onCommit={commitEdit} onSelect={select}
        />
      )}
      <footer className="desk-statusbar">
        <span>
          {selection.length === 0 ? '未选择' : selection.length === 1 ? `已选：${refKey(primary).split(':').slice(1).join(':')}` : `已选 ${selection.length} 项`}
        </span>
        {tool === 'measure' && (
          <span role="status" aria-label="测量结果">
            {measured !== null ? `${state.measure[0].label} → ${state.measure[1].label}：${measured.toFixed(2)} m` : state.measure.length === 1 ? `起点：${state.measure[0].label}，再点一个终点` : '测量：点击起点'}
          </span>
        )}
      </footer>
      {crowdOpen && basePlan && (
        <CrowdDialog
          defaultLabel={freeName('群演', new Set((basePlan.crowds || []).map(crowd => crowd.label)))}
          onSubmit={addCrowd} onClose={() => setCrowdOpen(false)}
        />
      )}
    </div>,
    document.body,
  );
}
