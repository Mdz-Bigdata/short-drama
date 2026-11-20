import { Component, useEffect, useRef, type ReactNode } from 'react';
import { useThree } from '@react-three/fiber';
import { Box } from 'lucide-react';
import type { DirectionalLight } from 'three';

import type { GroundPoint } from '../../spatial/spatialTypes';
import { shadowRig } from '../lib/stageMath';

export function ContextLossGuard({ onLost }: { onLost: () => void }) {
  const canvas = useThree(state => state.gl.domElement);
  useEffect(() => {
    const lost = (event: Event) => {
      event.preventDefault();
      onLost();
    };
    canvas.addEventListener('webglcontextlost', lost);
    return () => canvas.removeEventListener('webglcontextlost', lost);
  }, [canvas, onLost]);
  return null;
}

export class ViewportBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error) {
    console.error('director desk viewport failed', error);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export function ViewportUnavailable({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="desk-viewport__fallback" role="status">
      <Box size={42} aria-hidden="true" />
      <strong>3D 视图暂不可用</strong>
      <span>{message}</span>
      {onRetry && <button type="button" className="desk-button" onClick={onRetry}>重试</button>}
    </div>
  );
}

const ORIGIN: GroundPoint = [0, 0];

/**
 * Neutral light: a grey box has to read as a grey box, since what the lens sees goes to image and
 * video models as a reference. `reach` is how far the set spreads and `center` where its middle is,
 * so a street, or a set built away from the origin, still gets its shadows.
 */
export function StageLights({ reach = 12, center = ORIGIN }: { reach?: number; center?: GroundPoint }) {
  const invalidate = useThree(state => state.invalidate);
  const key = useRef<DirectionalLight>(null);
  const rig = shadowRig(reach, center);
  const { span, far } = rig;
  const [x, , z] = rig.target;
  useEffect(() => {
    const light = key.current;
    if (!light) return;
    // The light aims at its target, which is not in the scene, so nothing else refreshes where that is.
    light.target.position.set(x, 0, z);
    light.target.updateMatrixWorld();
    // three reads the shadow box once, when it first builds the shadow map; a set that grew needs it read again.
    light.shadow.camera.updateProjectionMatrix();
    invalidate();
  }, [far, invalidate, span, x, z]);
  return (
    <>
      <color attach="background" args={['#e7e7ea']} />
      <ambientLight intensity={0.7} />
      <hemisphereLight args={['#ffffff', '#b9b9be', 1.1]} />
      <directionalLight
        ref={key} position={rig.position} intensity={2.2} castShadow shadow-mapSize={[2048, 2048]} shadow-bias={-0.0005}
        shadow-camera-left={-span} shadow-camera-right={span} shadow-camera-top={span} shadow-camera-bottom={-span} shadow-camera-near={0.5} shadow-camera-far={far}
      />
    </>
  );
}
