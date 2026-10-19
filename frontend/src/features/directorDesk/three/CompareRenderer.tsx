// One small hidden canvas that draws the comparison thumbnails for every lens of a shot in turn.
//
// Browsers allow only a handful of WebGL contexts per page, so the comparison cannot give each
// camera a canvas of its own. Instead this canvas holds the same stage the camera view draws and
// is posed, drawn and read back once per lens, on request. Like a still, a thumbnail carries no
// helpers, labels or backdrop: it is the frame, nothing else.

import { useEffect, useMemo, useState } from 'react';
import { PerspectiveCamera } from '@react-three/drei';
import { Canvas, useThree } from '@react-three/fiber';
import type { Object3D, PerspectiveCamera as ThreeCamera } from 'three';

import type { StageCamera, StagePlan, StageShot } from '../../spatial/spatialTypes';
import { captureSize, HELPER_FLAG } from '../lib/capture';
import { createCompareQueue } from '../lib/compareQueue';
import { visibleActors } from '../lib/visibleActors';
import { LensStage } from './LensStage';
import { webglAvailable } from './stageLook';
import { ContextLossGuard, StageLights, ViewportBoundary } from './ViewportShell';

/** Long edge of a thumbnail: enough to judge a framing, small enough that six lenses draw in a blink. */
export const THUMBNAIL_LONG_EDGE = 360;
const THUMBNAIL_QUALITY = 0.8;

export interface CompareHandle {
  /** Thumbnails keyed by camera id; `onEach` hears each one as it is drawn. Rejects when superseded. */
  renderThumbnails: (cameras: StageCamera[], onEach?: (id: string, dataUrl: string) => void) => Promise<Record<string, string>>;
  cancel: () => void;
}

export interface CompareRendererProps {
  plan: StagePlan;
  shot?: StageShot;
  hidden: string[];
  /** Delivery aspect (width / height): the thumbnails show the frame that would be filmed. */
  aspect: number;
  onReady?: (handle: CompareHandle | null) => void;
  /** Why no thumbnail can be drawn here, in the operator's words. */
  onUnavailable?: (message: string) => void;
}

function RenderBridge({ width, height, onReady }: { width: number; height: number; onReady?: (handle: CompareHandle | null) => void }) {
  const gl = useThree(state => state.gl);
  const scene = useThree(state => state.scene);
  const camera = useThree(state => state.camera);

  useEffect(() => {
    const lens = camera as ThreeCamera;
    const queue = createCompareQueue<StageCamera, string>(wanted => {
      // The drawing buffer is pinned to the thumbnail size, whatever the hidden container measures.
      gl.setPixelRatio(1);
      gl.setSize(width, height, false);
      lens.fov = wanted.fov_deg;
      lens.aspect = width / height;
      lens.position.set(wanted.position[0], wanted.position[1], wanted.position[2]);
      lens.lookAt(wanted.target[0], wanted.target[1], wanted.target[2]);
      lens.updateProjectionMatrix();
      // The stage draws no helpers of its own, but a figure's marks are hidden here the way a still hides them.
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
        return gl.domElement.toDataURL('image/jpeg', THUMBNAIL_QUALITY);
      } finally {
        helpers.forEach(object => { object.visible = true; });
      }
    });
    onReady?.({ renderThumbnails: queue.run, cancel: queue.cancel });
    return () => {
      queue.cancel();
      onReady?.(null);
    };
  }, [camera, gl, height, onReady, scene, width]);
  return null;
}

export default function CompareRenderer({ plan, shot, hidden, aspect, onReady, onUnavailable }: CompareRendererProps) {
  const [canRender] = useState(webglAvailable);
  const [contextLost, setContextLost] = useState(false);
  const actors = useMemo(() => visibleActors(plan, shot, hidden), [hidden, plan, shot]);
  const { width, height } = captureSize(aspect, THUMBNAIL_LONG_EDGE);

  useEffect(() => {
    if (!canRender) onUnavailable?.('当前浏览器或设备不支持 WebGL，无法生成机位缩略图。');
    else if (contextLost) onUnavailable?.('图形上下文已中断，缩略图停止更新；关闭后重新打开机位对比可重试。');
  }, [canRender, contextLost, onUnavailable]);

  // The cards and their buttons work without pictures; only the thumbnails go missing.
  if (!canRender || contextLost) return null;

  return (
    <div className="desk-compare__renderer" aria-hidden="true" style={{ width, height }}>
      <ViewportBoundary fallback={null}>
        {/* Nothing draws on its own: every frame is one requested thumbnail. */}
        <Canvas dpr={1} frameloop="never" gl={{ antialias: true, preserveDrawingBuffer: true }}>
          <StageLights />
          <PerspectiveCamera makeDefault fov={40} near={0.05} far={500} position={[0, 1.5, 5]} />
          <RenderBridge width={width} height={height} onReady={onReady} />
          <ContextLossGuard onLost={() => setContextLost(true)} />
          <LensStage plan={plan} actors={actors} hidden={hidden} />
        </Canvas>
      </ViewportBoundary>
    </div>
  );
}
