// One small hidden canvas that draws the monitor wall, one monitor at a time.
//
// Every monitor can see a different instant of a different shot, so unlike the comparison strip the
// stage itself changes between pictures: the wall hands this canvas one monitor, the stage is put
// into that monitor's state, and the frame is read back once the stage has stopped changing (every
// figure posed, every model in). Then the wall hands over the next one. Like a still, a monitor
// carries no helpers, labels or backdrop.

import { useEffect, useMemo, useRef, useState } from 'react';
import { PerspectiveCamera } from '@react-three/drei';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import type { Object3D, PerspectiveCamera as ThreeCamera, Scene, WebGLRenderer } from 'three';

import type { Monitor } from '../lib/monitors';
import { captureSize, HELPER_FLAG } from '../lib/capture';
import { stageReach } from '../lib/stageMath';
import { visibleActors } from '../lib/visibleActors';
import { holdHumanoidModel } from './figures/humanoidSource';
import { LensStage } from './LensStage';
import { webglAvailable } from './stageLook';
import { ContextLossGuard, StageLights, ViewportBoundary } from './ViewportShell';

/** Long edge of a monitor: the wall is a narrow column. */
export const MONITOR_LONG_EDGE = 280;
const MONITOR_QUALITY = 0.78;
/** How long the stage has to stay still before a drawn frame counts as the monitor's picture. */
const SETTLE_MS = 120;

export interface MonitorRendererProps {
  /** The monitor to draw now; `null` when every monitor is up to date. */
  monitor: Monitor | null;
  hidden: string[];
  /** Delivery aspect (width / height). */
  aspect: number;
  onDrawn: (key: string, signature: string, dataUrl: string) => void;
  /** Why the wall has no pictures, in the operator's words. */
  onUnavailable?: (message: string) => void;
}

/** Poses the lens for one monitor, draws the stage without its helpers and reads the frame back. */
function drawMonitor(gl: WebGLRenderer, scene: Scene, lens: ThreeCamera, monitor: Monitor, width: number, height: number): string {
  const wanted = monitor.camera;
  gl.setPixelRatio(1);
  gl.setSize(width, height, false);
  lens.fov = wanted.fov_deg;
  lens.aspect = width / height;
  lens.position.set(wanted.position[0], wanted.position[1], wanted.position[2]);
  lens.lookAt(wanted.target[0], wanted.target[1], wanted.target[2]);
  lens.updateProjectionMatrix();
  const helpers: Object3D[] = [];
  scene.traverse(object => {
    if (object.userData[HELPER_FLAG] && object.visible) {
      object.visible = false;
      helpers.push(object);
    }
  });
  try {
    // Drawn and read back in one task, so the buffer still holds this very frame.
    gl.render(scene, lens);
    return gl.domElement.toDataURL('image/jpeg', MONITOR_QUALITY);
  } finally {
    helpers.forEach(object => { object.visible = true; });
  }
}

/**
 * Draws the monitor on every frame the stage asks for (a commit, a figure finishing its model, a
 * clip taking its pose) and reports the picture once the stage has stopped changing for a moment,
 * so the wall moves on only with a finished frame.
 */
function Snap({ monitor, width, height, onDrawn }: { monitor: Monitor; width: number; height: number; onDrawn: MonitorRendererProps['onDrawn'] }) {
  const gl = useThree(state => state.gl);
  const scene = useThree(state => state.scene);
  const camera = useThree(state => state.camera);
  const invalidate = useThree(state => state.invalidate);
  const latest = useRef({ monitor, onDrawn });
  useEffect(() => { latest.current = { monitor, onDrawn }; }, [monitor, onDrawn]);
  const timer = useRef(0);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  // Another monitor is another picture: ask for a frame even if nothing in the scene had to move.
  useEffect(() => { invalidate(); }, [invalidate, monitor.key, monitor.signature]);
  // Priority 1: this frame callback does the drawing, R3F's own render is skipped.
  useFrame(() => {
    const { monitor: wanted, onDrawn: report } = latest.current;
    const url = drawMonitor(gl, scene, camera as ThreeCamera, wanted, width, height);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => report(wanted.key, wanted.signature, url), SETTLE_MS);
  }, 1);
  return null;
}

export default function MonitorRenderer({ monitor, hidden, aspect, onDrawn, onUnavailable }: MonitorRendererProps) {
  const [canRender] = useState(webglAvailable);
  const [contextLost, setContextLost] = useState(false);
  const { width, height } = captureSize(aspect, MONITOR_LONG_EDGE);
  const actors = useMemo(() => (monitor ? visibleActors(monitor.plan, monitor.shot, hidden) : []), [hidden, monitor]);
  const lit = useMemo(() => stageReach({ actors, landmarks: monitor?.plan.landmarks ?? [] }), [actors, monitor]);
  // A skinned figure shows a stand-in until the shared model is in, so nothing is drawn before it is.
  const wantsModel = Boolean(monitor?.plan.actors.some(actor => actor.figure === 'humanoid'));
  const [modelReady, setModelReady] = useState(false);
  useEffect(() => {
    if (!wantsModel) return undefined;
    const hold = holdHumanoidModel();
    let alive = true;
    void hold.ready.then(() => { if (alive) setModelReady(true); });
    return () => { alive = false; hold.release(); };
  }, [wantsModel]);
  const drawable = monitor && (!wantsModel || modelReady);

  useEffect(() => {
    if (!canRender) onUnavailable?.('当前浏览器或设备不支持 WebGL，监视器没有画面。');
    else if (contextLost) onUnavailable?.('图形上下文已中断，监视器停止更新；收起再打开监视器可重试。');
  }, [canRender, contextLost, onUnavailable]);

  if (!canRender || contextLost) return null;

  return (
    <div className="desk-monitors__renderer" aria-hidden="true" style={{ width, height }}>
      <ViewportBoundary fallback={null}>
        {/* On demand: a frame is drawn whenever the stage changes, and each one is a monitor's picture. */}
        <Canvas shadows dpr={1} frameloop="demand" gl={{ antialias: true, preserveDrawingBuffer: true }}>
          <StageLights reach={lit.radius} center={lit.center} />
          <PerspectiveCamera makeDefault fov={40} near={0.05} far={500} position={[0, 1.5, 5]} />
          <ContextLossGuard onLost={() => setContextLost(true)} />
          {monitor && <LensStage plan={monitor.plan} actors={actors} hidden={hidden} />}
          {drawable && <Snap monitor={monitor} width={width} height={height} onDrawn={onDrawn} />}
        </Canvas>
      </ViewportBoundary>
    </div>
  );
}
