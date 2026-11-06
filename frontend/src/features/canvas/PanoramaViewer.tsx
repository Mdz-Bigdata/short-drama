import { Canvas, useThree } from '@react-three/fiber';
import { useEffect, useRef, useState } from 'react';
import { BackSide, SRGBColorSpace, TextureLoader, type PerspectiveCamera, type Texture } from 'three';

import { apiUrl } from '../../api/client';

const SPHERE_RADIUS = 50;
const MIN_FOV = 30;
const MAX_FOV = 100;

function Sphere({ url }: { url: string }) {
  const { invalidate } = useThree();
  const [texture, setTexture] = useState<Texture | null>(null);
  useEffect(() => {
    let live = true;
    const loader = new TextureLoader();
    loader.crossOrigin = 'anonymous';
    let loaded: Texture | null = null;
    loader.load(apiUrl(url), result => {
      if (!live) {
        result.dispose();
        return;
      }
      result.colorSpace = SRGBColorSpace;
      loaded = result;
      setTexture(result);
      invalidate();
    });
    return () => {
      live = false;
      loaded?.dispose();
    };
  }, [invalidate, url]);
  if (!texture) return null;
  return (
    <mesh>
      <sphereGeometry args={[SPHERE_RADIUS, 48, 32]} />
      <meshBasicMaterial map={texture} side={BackSide} toneMapped={false} />
    </mesh>
  );
}

function LookControls() {
  const { camera, gl, invalidate } = useThree();
  const look = useRef({ yaw: 0, pitch: 0, dragging: false, lastX: 0, lastY: 0 });

  useEffect(() => {
    const element = gl.domElement;
    const lens = camera as PerspectiveCamera;
    const state = look.current;
    const apply = () => {
      camera.rotation.order = 'YXZ';
      camera.rotation.set(state.pitch, state.yaw, 0);
      invalidate();
    };
    const down = (event: PointerEvent) => {
      state.dragging = true;
      state.lastX = event.clientX;
      state.lastY = event.clientY;
      element.setPointerCapture?.(event.pointerId);
    };
    const move = (event: PointerEvent) => {
      if (!state.dragging) return;
      state.yaw += (event.clientX - state.lastX) * 0.004;
      state.pitch = Math.max(-1.5, Math.min(1.5, state.pitch + (event.clientY - state.lastY) * 0.004));
      state.lastX = event.clientX;
      state.lastY = event.clientY;
      apply();
    };
    const up = () => { state.dragging = false; };
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      event.stopPropagation();
      lens.fov = Math.max(MIN_FOV, Math.min(MAX_FOV, lens.fov + event.deltaY * 0.05));
      lens.updateProjectionMatrix();
      invalidate();
    };
    element.addEventListener('pointerdown', down);
    element.addEventListener('pointermove', move);
    element.addEventListener('pointerup', up);
    element.addEventListener('pointercancel', up);
    element.addEventListener('wheel', wheel, { passive: false });
    return () => {
      element.removeEventListener('pointerdown', down);
      element.removeEventListener('pointermove', move);
      element.removeEventListener('pointerup', up);
      element.removeEventListener('pointercancel', up);
      element.removeEventListener('wheel', wheel);
    };
  }, [camera, gl, invalidate]);
  return null;
}

/** An equirectangular picture from inside its sphere. Only one is ever mounted: browsers allow few WebGL contexts. */
export default function PanoramaViewer({ url }: { url: string }) {
  return (
    <div className="cn-panorama" data-no-drag data-no-wheel>
      {/* offsetSize: the node sits inside a scaled world, and a measured (scaled) box would draw a smaller picture. */}
      <Canvas frameloop="demand" resize={{ offsetSize: true }} camera={{ fov: 75, near: 0.1, far: SPHERE_RADIUS * 2, position: [0, 0, 0.001] }}>
        <LookControls />
        <Sphere url={url} />
      </Canvas>
    </div>
  );
}
