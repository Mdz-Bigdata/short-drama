import { useEffect, useMemo, useRef, useState } from 'react';
import { OrthographicCamera } from '@react-three/drei';
import { Canvas, useThree } from '@react-three/fiber';
import type { OrthographicCamera as OrthographicCameraThree } from 'three';

import type { StagePlan, StageShot } from '../../spatial/spatialTypes';
import { refKey, type SelectionRef } from '../deskTypes';
import { lightReach, paneReach } from '../lib/stageMath';
import { visibleActors } from '../lib/visibleActors';
import { LensStage } from './LensStage';
import { webglAvailable } from './stageLook';
import { StageLights, ViewportBoundary, ViewportUnavailable } from './ViewportShell';

export type OrthoSide = 'top' | 'front';

const LABELS: Record<OrthoSide, string> = { top: '顶视', front: '正视' };
const NO_SELECTION: SelectionRef[] = [];
const STAND_BACK_M = 200;

/** Fit the whole set in the pane: an orthographic zoom is pixels per metre, so it depends on the pane's size. */
function OrthoRig({ side, x, z, radius }: { side: OrthoSide; x: number; z: number; radius: number }) {
  const lens = useRef<OrthographicCameraThree>(null);
  const size = useThree(state => state.size);
  const invalidate = useThree(state => state.invalidate);
  useEffect(() => {
    const camera = lens.current;
    if (!camera) return;
    camera.zoom = Math.min(size.width, size.height) / (radius * 2.2);
    if (side === 'top') {
      // -Z (the far side of the set) at the top of the pane, as on the floor plan.
      camera.up.set(0, 0, -1);
      camera.position.set(x, STAND_BACK_M, z);
      camera.lookAt(x, 0, z);
    } else {
      camera.up.set(0, 1, 0);
      camera.position.set(x, radius * 0.6, z + STAND_BACK_M);
      camera.lookAt(x, radius * 0.6, z);
    }
    camera.updateProjectionMatrix();
    invalidate();
  }, [invalidate, radius, side, size.height, size.width, x, z]);
  return <OrthographicCamera ref={lens} makeDefault near={0.1} far={STAND_BACK_M * 2 + 400} />;
}

/** A plan or front elevation of the stage at the current instant: for reading the layout, not for editing it. */
export default function OrthoViewport({ plan, framing = plan, shot, hidden, side, selection = NO_SELECTION }: {
  plan: StagePlan;
  /** The plan as stored, not as played: the pane is framed on where its set and cast stand in it, so it holds still through playback. */
  framing?: StagePlan;
  shot?: StageShot;
  hidden: string[];
  side: OrthoSide;
  /** What is picked on the desk, marked here too so it can be found on the plan. Reading only: nothing is picked from this pane. */
  selection?: SelectionRef[];
}) {
  const [canRender] = useState(webglAvailable);
  const actors = useMemo(() => visibleActors(plan, shot, hidden), [hidden, plan, shot]);
  const selectedKeys = useMemo(() => new Set(selection.map(refKey)), [selection]);
  // Framed on the set and the cast on their marks, so a cast standing clear of the set (or a set with no pieces) is still in the pane.
  const shotId = shot?.shot_id;
  const { center, radius } = useMemo(() => paneReach(framing, shotId, hidden), [framing, hidden, shotId]);
  const lit = lightReach(plan, shotId, actors);
  // A context that cannot be made fails outside React, where the boundary below never hears of it.
  if (!canRender) return <ViewportUnavailable message={`当前浏览器或设备不支持 WebGL，无法显示${LABELS[side]}图。`} />;
  return (
    <div className="desk-viewport is-ortho" role="region" aria-label={LABELS[side]}>
      <ViewportBoundary fallback={<ViewportUnavailable message={`${LABELS[side]}图渲染失败，请关闭后重新打开导演台。`} />}>
        <Canvas shadows frameloop="demand" dpr={[1, 1.5]} gl={{ antialias: true, powerPreference: 'high-performance' }}>
          <StageLights reach={lit.radius} center={lit.center} />
          <OrthoRig side={side} x={center[0]} z={center[1]} radius={radius} />
          <LensStage plan={plan} actors={actors} hidden={hidden} selection={selectedKeys} />
        </Canvas>
      </ViewportBoundary>
      <span className="desk-viewport__tag">{LABELS[side]}</span>
    </div>
  );
}
