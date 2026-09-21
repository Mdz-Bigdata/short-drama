import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import { PerspectiveCamera } from '@react-three/drei';
import { Canvas, useThree } from '@react-three/fiber';

import { parseAspect } from '../../spatial/floorPlanGeometry';
import { actorsInShot, type StageActor, type StageCamera, type StagePlan, type StageShot } from '../../spatial/spatialTypes';
import { backdropOf } from '../deskOperations';
import type { LensFrameInfo, LensHandle } from '../deskTypes';
import { captureStill } from '../lib/capture';
import { Backdrop } from './Backdrop';
import { ActorFigure } from './figures/ActorFigure';
import { StageProp } from './props/StageProp';
import { figureHeight } from '../lib/figureHeight';
import { webglAvailable } from './stageLook';
import { ContextLossGuard, StageLights, ViewportBoundary, ViewportUnavailable } from './ViewportShell';

export interface LensViewportProps {
  plan: StagePlan;
  shot?: StageShot;
  camera?: StageCamera;
  hidden: string[];
  /** The DOM composition guides, laid over the frame. */
  overlay?: ReactNode;
  onReady?: (handle: LensHandle | null) => void;
  /** Changes whenever a clip export asks for a new instant; echoed back once the scene holds it. */
  frameStamp?: number;
  onFrameShown?: (stamp: number, info: LensFrameInfo) => void;
  /** The backdrop is a framing reference, so it stays out of a delivered still or clip by default. */
  backdropInCapture?: boolean;
}

function LookAt({ target }: { target: [number, number, number] }) {
  const camera = useThree(state => state.camera);
  const invalidate = useThree(state => state.invalidate);
  useEffect(() => {
    camera.lookAt(target[0], target[1], target[2]);
    camera.updateProjectionMatrix();
    invalidate();
  }, [camera, invalidate, target]);
  return null;
}

function frameInfo(actors: StageActor[]): LensFrameInfo {
  return {
    // Crowd members are furniture with heads; naming forty of them would bury the frame.
    labels: actors.filter(actor => !actor.crowd_id).map(actor => ({ text: actor.name, position: [actor.position[0], figureHeight(actor) + 0.1, actor.position[1]] })),
    figures: actors.map(actor => ({ actor, height: figureHeight(actor) })),
  };
}

function CaptureBridge({ aspect, actors, onReady }: { aspect: number; actors: StageActor[]; onReady?: (handle: LensHandle | null) => void }) {
  const gl = useThree(state => state.gl);
  const scene = useThree(state => state.scene);
  const camera = useThree(state => state.camera);
  useEffect(() => {
    onReady?.({
      capture: options => {
        const info = frameInfo(actors);
        return captureStill({ gl, scene, camera, aspect, monochrome: options.monochrome, labels: options.labels ? info.labels : [], figures: info.figures });
      },
      renderer: () => ({ gl, scene, camera }),
    });
    return () => onReady?.(null);
  }, [actors, aspect, camera, gl, onReady, scene]);
  return null;
}

/**
 * The last thing in the scene, so its effect runs after every figure has taken its pose and the
 * lens has been aimed: when it reports a stamp, a render of this scene is that instant.
 */
function FrameAck({ stamp, actors, onShown }: { stamp: number; actors: StageActor[]; onShown: (stamp: number, info: LensFrameInfo) => void }) {
  useEffect(() => { onShown(stamp, frameInfo(actors)); }, [actors, onShown, stamp]);
  return null;
}

export default function LensViewport({ plan, shot, camera, hidden, overlay, onReady, frameStamp, onFrameShown, backdropInCapture = false }: LensViewportProps) {
  const [canRender] = useState(webglAvailable);
  const [contextLost, setContextLost] = useState(false);
  const aspect = parseAspect(plan.aspect_ratio);
  const actors = useMemo(
    () => actorsInShot(plan, shot).filter(actor => !hidden.includes(actor.crowd_id ? `crowd:${actor.crowd_id}` : `actor:${actor.name}`)),
    [hidden, plan, shot],
  );
  const target = useMemo<[number, number, number]>(() => (camera ? [camera.target[0], camera.target[1], camera.target[2]] : [0, 1, 0]), [camera]);

  if (!canRender) return <ViewportUnavailable message="当前浏览器或设备不支持 WebGL，无法显示机位画面。" />;
  if (contextLost) return <ViewportUnavailable message="图形上下文已中断。" onRetry={() => setContextLost(false)} />;
  if (!camera) return <div className="desk-viewport__fallback" role="status"><strong>本镜还没有机位</strong><span>在右侧「机位」里添加一个。</span></div>;

  return (
    <div className="desk-viewport is-lens" role="region" aria-label="机位视角">
      <ViewportBoundary fallback={<ViewportUnavailable message="机位画面渲染失败，请关闭后重新打开导演台。" />}>
        {/* The canvas itself takes the delivery aspect, so what is inside it is the frame. */}
        <div className="desk-viewport__pane">
          <div className="desk-viewport__frame" style={{ '--desk-aspect': String(aspect) } as CSSProperties}>
            {/* The drawing buffer is kept so a still can be read back after the render that made it. */}
            <Canvas dpr={[1, 1.5]} frameloop="demand" gl={{ antialias: true, powerPreference: 'high-performance', preserveDrawingBuffer: true }}>
              <StageLights />
              <PerspectiveCamera makeDefault fov={camera.fov_deg} near={0.05} far={500} position={camera.position} />
              <LookAt target={target} />
              <CaptureBridge aspect={aspect} actors={actors} onReady={onReady} />
              <ContextLossGuard onLost={() => setContextLost(true)} />
              {/* After LookAt, so the underlay is squared to a lens that has already been aimed. */}
              <Backdrop backdrop={backdropOf(plan)} inCapture={backdropInCapture} />
              <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.005, 0]}>
                <planeGeometry args={[200, 200]} />
                <meshStandardMaterial color="#0a111b" roughness={1} />
              </mesh>
              {plan.landmarks.filter(item => !hidden.includes(`landmark:${item.name}`)).map(item => (
                <StageProp key={item.id} landmark={item} labelled={false} selected={false} />
              ))}
              {actors.map(actor => (
                <ActorFigure key={actor.id} actor={actor} labelled={false} selected={false} subject={false} />
              ))}
              {frameStamp !== undefined && onFrameShown && <FrameAck stamp={frameStamp} actors={actors} onShown={onFrameShown} />}
            </Canvas>
            {overlay}
          </div>
        </div>
      </ViewportBoundary>
      <div className="desk-viewport__hint">
        {shot ? `第 ${shot.shot_id} 镜 · ` : ''}{camera.label || camera.id} · {camera.lens_mm}mm · {plan.aspect_ratio}
      </div>
    </div>
  );
}
