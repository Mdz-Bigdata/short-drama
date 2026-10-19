import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { Camera, X } from 'lucide-react';

import { parseAspect } from '../../spatial/floorPlanGeometry';
import type { StagePlan, StageShot } from '../../spatial/spatialTypes';
import { refKey, type EditRequest, type SelectionRef } from '../deskTypes';
import { ANGLE_PRESETS, type AnglePresetId } from '../lib/anglePresets';
import { isCompareCancelled } from '../lib/compareQueue';
import type { CompareHandle } from '../three/CompareRenderer';

// three.js stays out of the desk's first load; the comparison canvas arrives when the strip opens.
const CompareRenderer = lazy(() => import('../three/CompareRenderer'));

interface Props {
  /** The plan as drawn: what the lenses see right now. */
  plan: StagePlan;
  shot?: StageShot;
  hidden: string[];
  /** The stored revision; a new one is what makes every thumbnail stale. */
  revision: number;
  selection: SelectionRef[];
  editable: boolean;
  onCommit: (request: EditRequest) => void;
  onSelect: (ref: SelectionRef, additive: boolean) => void;
  /** The same quick-angle add the 机位 tab uses, so a comparison can be built in a few clicks. */
  onAddPreset: (preset: AnglePresetId) => void;
  onClose: () => void;
}

// A burst of edits (a drag, a few undo steps) redraws the thumbnails once, after the last of them.
const DEBOUNCE_MS = 300;

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function CameraComparePanel({ plan, shot, hidden, revision, selection, editable, onCommit, onSelect, onAddPreset, onClose }: Props) {
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState('');
  const [ready, setReady] = useState(false);
  // The run the thumbnails on screen belong to; anything newer is still being drawn.
  const [drawnKey, setDrawnKey] = useState('');
  const handle = useRef<CompareHandle | null>(null);
  const onReady = useCallback((next: CompareHandle | null) => {
    handle.current = next;
    setReady(Boolean(next));
  }, []);

  // The filming lens first, then the candidates in the order they were added.
  const cameras = useMemo(
    () => (shot ? [shot.camera_id, ...(shot.alt_camera_ids || [])].flatMap(id => plan.cameras.filter(camera => camera.id === id)) : []),
    [plan.cameras, shot],
  );
  // The playhead redraws the plan many times a second; the thumbnails only follow the stored
  // revision, the shot and its list of lenses, so the newest cameras are read through a ref.
  const latest = useRef(cameras);
  useEffect(() => { latest.current = cameras; }, [cameras]);
  const runKey = cameras.length ? `${revision}:${shot?.shot_id ?? ''}:${cameras.map(camera => camera.id).join('\n')}` : '';
  const rendering = ready && runKey !== '' && drawnKey !== runKey;

  useEffect(() => {
    if (!ready || !runKey) return undefined;
    let stale = false;
    const timer = window.setTimeout(() => {
      const renderer = handle.current;
      if (!renderer) { setDrawnKey(runKey); return; }
      renderer.renderThumbnails(latest.current, (id, url) => { if (!stale) setThumbs(current => ({ ...current, [id]: url })); })
        .then(made => { if (!stale) { setThumbs(made); setNotice(''); } })
        .catch(error => { if (!stale && !isCompareCancelled(error)) setNotice(messageOf(error, '缩略图生成失败。')); })
        .finally(() => { if (!stale) setDrawnKey(runKey); });
    }, DEBOUNCE_MS);
    return () => {
      // A newer revision or another shot: whatever this run would have drawn is of the past.
      stale = true;
      window.clearTimeout(timer);
      handle.current?.cancel();
    };
  }, [ready, runKey]);

  const selected = new Set(selection.map(refKey));
  const aspect = parseAspect(plan.aspect_ratio);
  const candidates = shot?.alt_camera_ids?.length ?? 0;

  const quickAdd = shot && (
    <div className="desk-compare__add">
      <span>快速添加候选</span>
      <div className="desk-chips" role="group" aria-label="快速添加候选机位">
        {ANGLE_PRESETS.map(preset => (
          <button key={preset.id} type="button" className="desk-chip" disabled={!editable || shot.subjects.length === 0} title={shot.subjects.length ? undefined : '空镜没有拍摄对象，无法按角度放置机位'} onClick={() => onAddPreset(preset.id)}>{preset.label}</button>
        ))}
      </div>
    </div>
  );

  return (
    <section className="desk-compare" role="region" aria-label="机位对比" style={{ '--desk-aspect': String(aspect) } as CSSProperties}>
      <div className="desk-compare__head">
        <h2><Camera aria-hidden="true" /> 机位对比 {shot && <small>第 {shot.shot_id} 镜 · {cameras.length} 个机位</small>}</h2>
        <span className="desk-compare__status" role="status">{rendering ? '正在生成缩略图…' : notice}</span>
        <button type="button" className="desk-icon" aria-label="关闭机位对比" title="关闭机位对比（4）" onClick={onClose}><X aria-hidden="true" /></button>
      </div>
      {!shot && <p className="desk-compare__empty">本场还没有镜头。</p>}
      {shot && cameras.length === 0 && <p className="desk-compare__empty">本镜还没有机位。</p>}
      {cameras.length > 0 && (
        <ul className="desk-compare__grid" aria-label="本镜机位">
          {cameras.map(camera => {
            const main = camera.id === shot?.camera_id;
            const label = camera.label || camera.id;
            const picked = selected.has(`camera:${camera.id}`) || selected.has(`camera-target:${camera.id}`);
            return (
              <li key={camera.id} className={`desk-compare__card ${main ? 'is-filming' : ''} ${picked ? 'is-selected' : ''}`} aria-current={picked ? 'true' : undefined}>
                <div className="desk-compare__thumb">
                  {thumbs[camera.id] ? <img src={thumbs[camera.id]} alt={`${label} 的画面`} /> : <span>{rendering ? '生成中…' : '暂无缩略图'}</span>}
                </div>
                <div className="desk-compare__meta">
                  <strong title={label}>{label}</strong>
                  <span className={`desk-compare__badge ${main ? 'is-filming' : ''}`}>{main ? '主机位' : '候选'}</span>
                  <small>{camera.lens_mm}mm</small>
                </div>
                <div className="desk-compare__actions">
                  <button type="button" className="desk-chip" aria-pressed={picked} aria-label={`选中 ${label}`} onClick={() => onSelect({ kind: 'camera', id: camera.id }, false)}>选中</button>
                  {!main && shot && (
                    <>
                      <button
                        type="button" className="desk-chip" aria-label={`使用此机位 ${label}`} disabled={!editable}
                        onClick={() => onCommit({ label: '设为主机位', operations: [{ op: 'use_camera', shot_id: shot.shot_id, camera_id: camera.id }] })}
                      >使用此机位</button>
                      <button
                        type="button" className="desk-chip is-danger" aria-label={`删除 ${label}`} disabled={!editable}
                        onClick={() => onCommit({ label: '删除候选机位', operations: [{ op: 'remove_camera', camera_id: camera.id }], barrier: true })}
                      >删除</button>
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {shot && candidates === 0 && (
        <p className="desk-compare__empty">
          本镜还没有候选机位。候选机位是同一镜的备选镜头：先用下面的快速角度添加几个，缩略图并排后挑一个「使用此机位」，它就替换主机位。
        </p>
      )}
      {quickAdd}
      {shot && (
        <Suspense fallback={null}>
          <CompareRenderer plan={plan} shot={shot} hidden={hidden} aspect={aspect} onReady={onReady} onUnavailable={setNotice} />
        </Suspense>
      )}
    </section>
  );
}
