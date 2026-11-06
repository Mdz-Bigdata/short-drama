import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

import { dragLook, lookTarget, type LookAngles } from '../panoramaView';
import { t } from '../../../i18n';

interface Props {
  url: string;
  alt: string;
}

function webglAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(window.WebGLRenderingContext && (canvas.getContext('webgl2') || canvas.getContext('webgl')));
  } catch {
    return false;
  }
}

/** The panorama on the inside of a sphere, looked around by dragging; without WebGL, the flat picture. */
export default function PanoramaViewer({ url, alt }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const [flat] = useState(() => !webglAvailable());
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const element = host.current;
    if (!element || flat) return undefined;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, 2, 0.1, 100);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    element.appendChild(renderer.domElement);
    const geometry = new THREE.SphereGeometry(50, 64, 32);
    // Flipped so the picture faces inward and reads the right way round from the centre.
    geometry.scale(-1, 1, 1);
    const material = new THREE.MeshBasicMaterial();
    scene.add(new THREE.Mesh(geometry, material));

    let look: LookAngles = { yaw: 0, pitch: 0 };
    let dragging: { x: number; y: number } | null = null;
    const draw = () => {
      const [x, y, z] = lookTarget(look);
      camera.lookAt(x, y, z);
      renderer.render(scene, camera);
    };
    const fit = () => {
      const width = element.clientWidth || 1;
      const height = element.clientHeight || 1;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
      draw();
    };
    const observer = new ResizeObserver(fit);
    observer.observe(element);

    let disposed = false;
    const texture = new THREE.TextureLoader().setCrossOrigin('anonymous').load(url, () => {
      if (disposed) return;
      texture.colorSpace = THREE.SRGBColorSpace;
      material.map = texture;
      material.needsUpdate = true;
      draw();
    }, undefined, () => { if (!disposed) setFailed(true); });

    const canvas = renderer.domElement;
    const onDown = (event: PointerEvent) => {
      dragging = { x: event.clientX, y: event.clientY };
      canvas.setPointerCapture?.(event.pointerId);
    };
    const onMove = (event: PointerEvent) => {
      if (!dragging) return;
      look = dragLook(look, event.clientX - dragging.x, event.clientY - dragging.y);
      dragging = { x: event.clientX, y: event.clientY };
      draw();
    };
    const onUp = () => { dragging = null; };
    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointermove', onMove);
    canvas.addEventListener('pointerup', onUp);
    canvas.addEventListener('pointercancel', onUp);
    fit();

    return () => {
      disposed = true;
      observer.disconnect();
      canvas.removeEventListener('pointerdown', onDown);
      canvas.removeEventListener('pointermove', onMove);
      canvas.removeEventListener('pointerup', onUp);
      canvas.removeEventListener('pointercancel', onUp);
      texture.dispose();
      material.dispose();
      geometry.dispose();
      renderer.dispose();
      element.removeChild(canvas);
    };
  }, [url, flat]);

  if (flat || failed) {
    return <img className="panorama-viewer__flat" src={url} alt={alt} />;
  }
  return <div ref={host} className="panorama-viewer" role="img" aria-label={t('{0}，拖动可环视', [alt])} />;
}
