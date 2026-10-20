import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react';
import { createPortal } from 'react-dom';
import {
  ArrowLeftRight, Axis3d, Camera, CircleCheck, Download, Eye, LayoutGrid, RefreshCw, RotateCcw, TriangleAlert, Upload, Users, X,
} from 'lucide-react';

import { ApiError } from '../../api/client';
import { FloorPlan, type FloorMove } from './FloorPlan';
import { isOverhead } from './floorPlanGeometry';
import {
  exportSpatialPlan, fetchSpatialPlan, importSpatialPlan, patchSpatialPlan, rebuildSpatialPlan, redrawSpatialScene,
  type SpatialExportFormat,
} from './spatialApi';
import {
  FUNCTION_LABELS, MOVE_LABELS, POSTURE_LABELS,
  type SpatialPlanResponse, type StageOperation, type StagePosture, type StageShot,
} from './spatialTypes';
import './SpatialStageDialog.css';
import { t } from '../../i18n';

// three.js only loads when someone actually opens a 3D view.
const SpatialStageViewport = lazy(() => import('./three/SpatialStageViewport'));

type ViewMode = 'plan' | 'director' | 'camera';

const VIEWS: Array<{ id: ViewMode; label: string; icon: typeof LayoutGrid }> = [
  { id: 'plan', label: '俯视图', icon: LayoutGrid },
  { id: 'director', label: '导演视角', icon: Eye },
  { id: 'camera', label: '机位视角', icon: Camera },
];
const MAX_IMPORT_BYTES = 5 * 1024 * 1024;

function message(error: unknown, fallback: string) {
  return error instanceof ApiError || error instanceof Error ? error.message || fallback : fallback;
}

function axisBadge(shot: StageShot, establishedSide: number) {
  if (shot.axis_side === 0) return { label: '轴上', tone: 'neutral' };
  return shot.axis_side === (establishedSide || shot.axis_side)
    ? { label: '同侧', tone: 'ok' }
    : { label: shot.crossing === 'none' ? t('越轴') : t('对侧'), tone: shot.crossing === 'none' ? 'bad' : 'neutral' };
}

export function SpatialStageDialog({ taskId, sceneId, onClose, onRedrawRequested }: {
  taskId: string;
  sceneId: string;
  onClose: () => void;
  /** The scene was sent back to stage 4; the workspace should refresh its boards. */
  onRedrawRequested?: () => void;
}) {
  const [response, setResponse] = useState<SpatialPlanResponse | null>(null);
  const [loadError, setLoadError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<ViewMode>('plan');
  const [shotId, setShotId] = useState<number | null>(null);
  const [autoSolve, setAutoSolve] = useState(true);
  const [pairDistance, setPairDistance] = useState('');
  const closeRef = useRef<HTMLButtonElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // State is only set from the request's callbacks, never synchronously inside the effect.
  const load = useCallback((signal?: AbortSignal) => (
    fetchSpatialPlan(taskId, sceneId, signal)
      .then(data => {
        setResponse(data);
        setLoadError('');
        setShotId(current => (current && data.plan.shots.some(shot => shot.shot_id === current) ? current : data.plan.shots[0]?.shot_id ?? null));
      })
      .catch(error => {
        if (signal?.aborted) return;
        setLoadError(message(error, '空间调度读取失败。'));
      })
  ), [sceneId, taskId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKey);
      previousFocus?.focus();
    };
  }, [onClose]);

  const plan = response?.plan;
  const shot = useMemo(() => plan?.shots.find(item => item.shot_id === shotId), [plan, shotId]);
  const camera = plan?.cameras.find(item => item.id === shot?.camera_id);
  const failed = useMemo(() => (plan?.checks || []).filter(check => !check.passed), [plan]);
  const flagged = useMemo(() => new Map(failed.flatMap(check => check.shot_ids.map(id => [id, check.severity] as const))), [failed]);
  const principals = plan && plan.axis.kind === 'dialogue' ? [plan.axis.from_name, plan.axis.to_name] : [];

  const run = async (work: () => Promise<SpatialPlanResponse>, done = '') => {
    if (busy) return;
    setBusy(true);
    setNotice('');
    try {
      const data = await work();
      setResponse(data);
      setShotId(current => (current && data.plan.shots.some(item => item.shot_id === current) ? current : data.plan.shots[0]?.shot_id ?? null));
      setNotice(done);
    } catch (error) {
      setNotice(
        error instanceof ApiError && error.status === 409
          ? `${message(error, '空间方案已变化。')}（可点「重新读取」）`
          : message(error, '操作失败，请稍后重试。'),
      );
    } finally {
      setBusy(false);
    }
  };

  const apply = (operations: StageOperation[], done = '') => {
    if (!plan) return;
    void run(() => patchSpatialPlan(taskId, sceneId, plan.revision, operations), done);
  };

  const withSolve = (operations: StageOperation[]) => (autoSolve ? [...operations, { op: 'solve_camera' }] : operations);

  const handleMove = (move: FloorMove) => {
    if (!plan) return;
    if (move.kind === 'camera') {
      const moved = plan.cameras.find(item => item.id === move.cameraId);
      if (!moved) return;
      apply([{ op: 'move_camera', camera_id: move.cameraId, position: [move.position[0], moved.position[1], move.position[1]] }]);
      return;
    }
    if (move.kind === 'landmark') {
      apply([{ op: 'move_landmark', name: move.name, position: move.position }]);
      return;
    }
    const operations: StageOperation[] = [{ op: 'move_actor', name: move.name, position: move.position }];
    // People playing a scene to each other keep facing each other when one of them is moved.
    if (principals.includes(move.name) && plan.formation.startsWith('面对面')) {
      const [first, second] = principals;
      operations.push({ op: 'orient_toward', name: first, target: second }, { op: 'orient_toward', name: second, target: first });
    }
    apply(withSolve(operations));
  };

  const download = async (format: SpatialExportFormat) => {
    if (busy) return;
    setBusy(true);
    setNotice('');
    try {
      const data = await exportSpatialPlan(taskId, sceneId, format);
      const url = URL.createObjectURL(new Blob([JSON.stringify(data.document, null, 2)], { type: 'application/json' }));
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = data.fileName;
      anchor.click();
      URL.revokeObjectURL(url);
      setNotice(data.note || t('已导出。'));
    } catch (error) {
      setNotice(message(error, '导出失败。'));
    } finally {
      setBusy(false);
    }
  };

  const importFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || !plan) return;
    if (file.size > MAX_IMPORT_BYTES) {
      setNotice(t('工程文件不能超过 5 MB。'));
      return;
    }
    let project: unknown;
    try {
      project = JSON.parse(await file.text());
    } catch {
      setNotice(t('工程文件不是合法的 JSON。'));
      return;
    }
    void run(() => importSpatialPlan(taskId, sceneId, plan.revision, project), '已按工程文件更新站位与机位。');
  };

  const redraw = () => {
    if (!window.confirm(t('将把 {0} 退回第 4 阶段，按当前站位重新生成本场九宫格；已生成的本场分镜图与视频片段会标记为过期。继续吗？', [sceneId]))) return;
    void run(() => redrawSpatialScene(taskId, sceneId), '本场已退回第 4 阶段，请重跑分镜阶段。').then(() => onRedrawRequested?.());
  };

  const body = () => {
    if (loadError) {
      return (
        <div className="spatial-dialog__empty" role="alert">
          <p>{loadError}</p>
          <button type="button" className="spatial-button" onClick={() => { void load(); }}><RefreshCw aria-hidden="true" /> {t('重新读取')}</button>
        </div>
      );
    }
    if (!plan) return <p className="spatial-dialog__empty" role="status">{t('正在读取空间调度…')}</p>;

    return (
      <div className="spatial-dialog__grid">
        <aside className="spatial-shots" aria-label={t('本场镜头机位')}>
          <h2>{t('镜头机位')} <small>{plan.coverage === 'template' ? '标准覆盖预览' : `${plan.shots.length} 镜`}</small></h2>
          <ul>
            {plan.shots.map(item => {
              const lens = plan.cameras.find(candidate => candidate.id === item.camera_id);
              const badge = axisBadge(item, plan.axis.camera_side);
              const severity = flagged.get(item.shot_id);
              return (
                <li key={item.shot_id}>
                  <button
                    type="button"
                    className={`spatial-shot ${item.shot_id === shotId ? 'is-selected' : ''}`}
                    aria-pressed={item.shot_id === shotId}
                    onClick={() => setShotId(item.shot_id)}
                  >
                    <span className="spatial-shot__number">{item.shot_id}</span>
                    <span className="spatial-shot__main">
                      <strong>{FUNCTION_LABELS[item.function]} · {lens?.shot_size || '—'}</strong>
                      <small>{item.subjects.join('、') || '空镜'} · {lens ? `${lens.lens_mm}mm` : ''} · {MOVE_LABELS[lens?.move.kind || 'static'] || '固定'}</small>
                    </span>
                    {plan.axis.kind !== 'none' && <span className={`spatial-badge is-${badge.tone}`}>{badge.label}</span>}
                    {severity && <TriangleAlert className={`spatial-shot__flag is-${severity}`} aria-label={severity === 'error' ? t('有错误') : t('有提示')} />}
                  </button>
                </li>
              );
            })}
          </ul>
        </aside>

        <main className="spatial-stage">
          <div className="spatial-stage__views" role="tablist" aria-label={t('视图')}>
            {VIEWS.map(item => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={view === item.id}
                className={view === item.id ? 'is-active' : ''}
                disabled={item.id === 'camera' && !camera}
                onClick={() => setView(item.id)}
              >
                <item.icon aria-hidden="true" /> {item.label}
              </button>
            ))}
            <label className="spatial-stage__auto">
              <input type="checkbox" checked={autoSolve} onChange={event => setAutoSolve(event.target.checked)} />
              {t('移动人物后自动重解机位')}
            </label>
          </div>
          <div className="spatial-stage__canvas">
            {view === 'plan' ? (
              <FloorPlan plan={plan} shot={shot} locked={busy} onSelectShot={setShotId} onMove={handleMove} />
            ) : (
              <Suspense fallback={<p className="spatial-dialog__empty" role="status">{t('正在加载 3D 视图…')}</p>}>
                <SpatialStageViewport plan={plan} shot={shot} mode={view} />
              </Suspense>
            )}
          </div>
          {shot && (
            <dl className="spatial-stage__text">
              <div><dt>{t('构图')}</dt><dd>{shot.text.composition}</dd></div>
              <div><dt>{t('轴线')}</dt><dd>{shot.text.action_axis}</dd></div>
              <div><dt>{t('视线')}</dt><dd>{shot.text.eyeline}</dd></div>
              <div><dt>{t('调度')}</dt><dd>{shot.text.blocking}</dd></div>
              <div><dt>{t('机位')}</dt><dd>{shot.text.camera_start}{camera && camera.move.kind !== 'static' ? ` → ${shot.text.camera_end}` : ''}{camera && isOverhead(camera) ? '（顶拍，中性机位）' : ''}</dd></div>
            </dl>
          )}
        </main>

        <aside className="spatial-inspector" aria-label={t('站位与校验')}>
          <section>
            <h2><Users aria-hidden="true" /> {t('站位')}</h2>
            <p className="spatial-inspector__formation">{plan.formation || '—'}</p>
            <ul className="spatial-actors">
              {plan.actors.map(actor => (
                <li key={actor.id}>
                  <span>
                    <strong>{actor.name}</strong>
                    <small>{actor.screen_side === 'left' ? t('恒在画左') : actor.screen_side === 'right' ? t('恒在画右') : actor.role === 'crowd' ? t('群体') : t('后景')}</small>
                  </span>
                  <select
                    aria-label={`${actor.name} 姿态`}
                    value={actor.posture}
                    disabled={busy}
                    onChange={event => apply(withSolve([{ op: 'move_actor', name: actor.name, posture: event.target.value as StagePosture }]))}
                  >
                    {(Object.keys(POSTURE_LABELS) as StagePosture[]).map(key => <option key={key} value={key}>{POSTURE_LABELS[key]}</option>)}
                  </select>
                </li>
              ))}
            </ul>
            {principals.length === 2 && (
              <div className="spatial-inspector__row">
                <label>
                  {t('相距（米）')}
                  <input
                    type="number" min={0.4} max={20} step={0.1} inputMode="decimal"
                    value={pairDistance}
                    placeholder={plan.formation.match(/相距([\d.]+)米/)?.[1] || '1.5'}
                    onChange={event => setPairDistance(event.target.value)}
                  />
                </label>
                <button
                  type="button" className="spatial-button" disabled={busy}
                  onClick={() => apply(withSolve([{
                    op: 'face_pair', first: principals[0], second: principals[1],
                    ...(Number(pairDistance) > 0 ? { distance: Number(pairDistance) } : {}),
                  }]), '已让两人面对面站定。')}
                >{t('面对面站定')}</button>
              </div>
            )}
            <div className="spatial-inspector__actions">
              {plan.axis.kind !== 'none' && (
                <button type="button" className="spatial-button" disabled={busy} onClick={() => apply([{ op: 'flip_camera_side' }, { op: 'solve_camera' }], '机位已换到轴线另一侧，人物左右关系随之互换。')}>
                  <ArrowLeftRight aria-hidden="true" /> {t('轴线换边')}
                </button>
              )}
              <button type="button" className="spatial-button" disabled={busy} onClick={() => apply([{ op: 'solve_camera' }], '已按当前站位重解全部机位。')}>
                <Axis3d aria-hidden="true" /> {t('重解全部机位')}
              </button>
              {shot && camera && camera.subjects.length === 1 && (
                <button
                  type="button" className="spatial-button" disabled={busy}
                  onClick={() => apply([{ op: 'solve_camera', shot_id: shot.shot_id, over_shoulder: camera.function !== 'over_shoulder' }])}
                >{camera.function === 'over_shoulder' ? t('本镜改为单人') : t('本镜改为过肩')}</button>
              )}
            </div>
          </section>

          <section>
            <h2>{failed.some(check => check.severity === 'error') ? <TriangleAlert aria-hidden="true" /> : <CircleCheck aria-hidden="true" />} 空间校验</h2>
            <ul className="spatial-checks">
              {plan.checks.map(check => (
                <li key={check.code} className={check.passed ? 'is-passed' : `is-${check.severity}`}>
                  <strong>{check.passed ? t('通过') : check.severity === 'error' ? t('错误') : t('提示')}</strong>
                  <span>{check.detail}</span>
                </li>
              ))}
            </ul>
          </section>

          <section>
            <h2>{t('工程')}</h2>
            <div className="spatial-inspector__actions">
              <button type="button" className="spatial-button" disabled={busy} onClick={() => { void download('director-desk'); }}><Download aria-hidden="true" /> {t('导出 3D 导演台')}</button>
              <button type="button" className="spatial-button" disabled={busy} onClick={() => { void download('costage'); }}><Download aria-hidden="true" /> {t('导出 CoStage')}</button>
              <button type="button" className="spatial-button" disabled={busy} onClick={() => fileRef.current?.click()}><Upload aria-hidden="true" /> {t('导入工程')}</button>
              <input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={event => { void importFile(event); }} aria-label={t('导入导演台工程文件')} />
              <button type="button" className="spatial-button" disabled={busy} onClick={() => { if (window.confirm(t('放弃手动调整，按剧本与分镜表重新自动规划本场？'))) void run(() => rebuildSpatialPlan(taskId, sceneId, plan.revision), '已重新自动规划。'); }}>
                <RotateCcw aria-hidden="true" /> {t('重新自动规划')}
              </button>
              {response?.boardStatus === 'done' && (
                <button type="button" className="spatial-button is-primary" disabled={busy} onClick={redraw}>
                  <RefreshCw aria-hidden="true" /> {t('按当前站位重画本场')}
                </button>
              )}
            </div>
          </section>
        </aside>
      </div>
    );
  };

  return createPortal(
    <div className="spatial-dialog__backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="spatial-dialog" role="dialog" aria-modal="true" aria-labelledby="spatial-dialog-title">
        <header className="spatial-dialog__header">
          <div>
            <span>{t('SPATIAL STAGE / 空间调度')}</span>
            <h1 id="spatial-dialog-title">{sceneId} · 空间调度</h1>
            {plan && <p>{plan.location || '未命名场地'} · {plan.aspect_ratio} · {plan.source === 'edited' ? t('已手动调整') : t('自动规划')} · 第 {plan.revision} 版</p>}
          </div>
          <div className="spatial-dialog__header-actions">
            <button type="button" className="spatial-button" onClick={() => { void load(); }} disabled={busy}><RefreshCw aria-hidden="true" /> {t('重新读取')}</button>
            <button ref={closeRef} type="button" className="spatial-dialog__close" onClick={onClose} aria-label={t('关闭空间调度')}><X aria-hidden="true" /></button>
          </div>
        </header>
        {response && !response.persisted && <p className="spatial-dialog__banner">{t('本场尚未保存空间方案，当前为按剧本即时规划的预览；任意一次调整或运行第 4 阶段后会保存。')}</p>}
        {response?.boardStale && <p className="spatial-dialog__banner is-warning">{t('站位已修改，本场已完成的九宫格仍按旧站位绘制；点「按当前站位重画本场」后重跑分镜阶段即可更新。')}</p>}
        {notice && <p className="spatial-dialog__notice" role="status">{notice}</p>}
        <div className="spatial-dialog__body">{body()}</div>
      </div>
    </div>,
    document.body,
  );
}
