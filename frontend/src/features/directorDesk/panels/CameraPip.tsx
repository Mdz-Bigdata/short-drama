import { lazy, Suspense, type CSSProperties } from 'react';
import { Maximize2, Pause, Play, X } from 'lucide-react';

import { parseAspect } from '../../spatial/floorPlanGeometry';
import type { StageCamera, StagePlan, StageShot } from '../../spatial/spatialTypes';

const LensViewport = lazy(() => import('../three/LensViewport'));

interface Props {
  /** The plan at the playhead, the same one the director view draws. */
  plan: StagePlan;
  shot?: StageShot;
  camera?: StageCamera;
  hidden: string[];
  playing: boolean;
  onTogglePlay: () => void;
  /** Make the camera view the whole stage (the 机位 layout). */
  onExpand: () => void;
  onClose: () => void;
}

/**
 * The current camera's frame in a small window over the director view, so an actor can be dragged
 * in the room while the frame it lands in is watched. It draws what the camera view would, live.
 */
export function CameraPip({ plan, shot, camera, hidden, playing, onTogglePlay, onExpand, onClose }: Props) {
  const label = camera ? camera.label || camera.id : '本镜还没有机位';
  return (
    <section className="desk-pip" role="region" aria-label="当前机位画中画" style={{ '--desk-aspect': String(parseAspect(plan.aspect_ratio)) } as CSSProperties}>
      <div className="desk-pip__head">
        <span className="desk-pip__title" title={label}>{shot ? `第 ${shot.shot_id} 镜 · ` : ''}{label}</span>
        <button type="button" className="desk-icon" aria-label={playing ? '暂停' : '播放'} title={playing ? '暂停（空格）' : '播放（空格）'} onClick={onTogglePlay}>
          {playing ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
        </button>
        <button type="button" className="desk-icon" aria-label="放大到机位视图" title="放大到机位视图（3）" onClick={onExpand}><Maximize2 aria-hidden="true" /></button>
        <button type="button" className="desk-icon" aria-label="关闭画中画" title="关闭画中画" onClick={onClose}><X aria-hidden="true" /></button>
      </div>
      <div className="desk-pip__frame">
        <Suspense fallback={<p className="desk-empty" role="status">正在加载机位画面…</p>}>
          <LensViewport plan={plan} shot={shot} camera={camera} hidden={hidden} />
        </Suspense>
      </div>
    </section>
  );
}
