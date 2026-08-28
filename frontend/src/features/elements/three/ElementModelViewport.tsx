import { Component, useEffect, useRef, useState, type ReactNode } from 'react';
import { Bounds, Center, Grid, OrbitControls, PerformanceMonitor, useBounds } from '@react-three/drei';
import { Canvas, useThree } from '@react-three/fiber';
import { Box, Gauge, Grid3X3, Maximize2, Pause, Play, RotateCcw } from 'lucide-react';
import type { Object3D } from 'three';
// three-stdlib's loaders are API-identical but do not embed `new URL` decoder
// fallbacks, which made Vite ship a duplicate ~1.3MB draco runtime in dist.
import { GLTFLoader } from 'three-stdlib';

import { API_BASE } from '../../../api/client';
import { disposeModelResources } from './disposeModelResources';


interface Props {
  name: string;
  contentUrl: string;
  posterUrl?: string;
}

interface ModelRequestState {
  scene: Object3D | null;
  loading: boolean;
  error: string;
}


function webgl2Available(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(window.WebGL2RenderingContext && canvas.getContext('webgl2'));
  } catch {
    return false;
  }
}

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  return reduced;
}

function useAuthenticatedModel(path: string | null, reloadToken: number): ModelRequestState {
  const requestKey = `${path ?? 'disabled'}:${reloadToken}`;
  const [state, setState] = useState<ModelRequestState & { requestKey: string }>({
    requestKey,
    scene: null,
    loading: Boolean(path),
    error: '',
  });

  useEffect(() => {
    if (!path) return undefined;
    const controller = new AbortController();
    let parsedScene: Object3D | null = null;

    const load = async () => {
      try {
        const response = await fetch(`${API_BASE}${path}`, {
          credentials: 'include',
          signal: controller.signal,
          headers: { Accept: 'model/gltf-binary' },
        });
        if (!response.ok) {
          let detail = `模型读取失败 (${response.status})`;
          try {
            const payload = await response.json() as { detail?: string };
            if (payload.detail) detail = payload.detail;
          } catch {
            // Keep the bounded status message when the response is not JSON.
          }
          throw new Error(detail);
        }
        const buffer = await response.arrayBuffer();
        if (controller.signal.aborted) return;
        const gltf = await new GLTFLoader().parseAsync(buffer, '');
        parsedScene = gltf.scene;
        if (controller.signal.aborted) {
          disposeModelResources(parsedScene);
          parsedScene = null;
          return;
        }
        setState({ requestKey, scene: parsedScene, loading: false, error: '' });
      } catch (error) {
        if (controller.signal.aborted) return;
        setState({
          requestKey,
          scene: null,
          loading: false,
          error: error instanceof Error ? error.message : '模型读取失败',
        });
      }
    };

    void load();

    return () => {
      controller.abort();
      if (parsedScene) {
        disposeModelResources(parsedScene);
        parsedScene = null;
      }
    };
  }, [path, reloadToken, requestKey]);

  return state.requestKey === requestKey
    ? state
    : { scene: null, loading: Boolean(path), error: '' };
}

function FitCamera({ signal }: { signal: number }) {
  const bounds = useBounds();
  useEffect(() => {
    const frame = window.requestAnimationFrame(() => { bounds.refresh().clip().fit(); });
    return () => window.cancelAnimationFrame(frame);
  }, [bounds, signal]);
  return null;
}

function ContextLossGuard({ onLost }: { onLost: () => void }) {
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

interface BoundaryProps {
  children: ReactNode;
  fallback: ReactNode;
}

class ModelErrorBoundary extends Component<BoundaryProps, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error) {
    console.error('3D model render failed', error);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function ModelFallback({ message, posterUrl, onRetry }: { message: string; posterUrl?: string; onRetry?: () => void }) {
  return (
    <div className="model-fallback" role="status">
      {posterUrl ? <img src={posterUrl} alt="3D 资产参考图" /> : <Box size={54} />}
      <strong>3D 预览暂不可用</strong>
      <span>{message}</span>
      {onRetry && <button type="button" onClick={onRetry}>重试加载</button>}
    </div>
  );
}


export default function ElementModelViewport({ name, contentUrl, posterUrl }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const reducedMotion = useReducedMotion();
  const [reloadToken, setReloadToken] = useState(0);
  const [resetSignal, setResetSignal] = useState(0);
  const [autoRotate, setAutoRotate] = useState(false);
  const [showGrid, setShowGrid] = useState(true);
  const [lowQuality, setLowQuality] = useState(() => window.matchMedia('(max-width: 700px)').matches);
  const [contextLost, setContextLost] = useState(false);
  const [canRender] = useState(webgl2Available);
  const model = useAuthenticatedModel(canRender ? contentUrl : null, reloadToken);
  const scene = model.scene;

  const retry = () => {
    setContextLost(false);
    setReloadToken(value => value + 1);
  };

  const enterFullscreen = () => {
    void container.current?.requestFullscreen?.();
  };

  const poster = posterUrl ? `${API_BASE}${posterUrl}` : undefined;
  const fallback = (
    <ModelFallback
      message={contextLost ? '图形上下文已中断，请重试恢复。' : '模型无法解析，可保留参考图并替换 GLB。'}
      posterUrl={poster}
      onRetry={retry}
    />
  );

  return (
    <div className="element-model-viewport" ref={container} role="region" aria-label={`${name} 3D 模型交互预览`}>
      {model.loading ? (
        <div className="model-fetch-state" role="status"><Gauge className="spin" /> 正在安全读取并解析 GLB…</div>
      ) : model.error ? (
        <ModelFallback message={model.error} posterUrl={poster} onRetry={retry} />
      ) : !canRender ? (
        <ModelFallback message="当前浏览器或设备不支持 WebGL 2，已切换为参考图。" posterUrl={poster} />
      ) : contextLost ? fallback : !scene ? fallback : (
        <ModelErrorBoundary key={`${contentUrl}:${reloadToken}`} fallback={fallback}>
          <Canvas
            dpr={lowQuality ? 1 : [1, 1.5]}
            frameloop={autoRotate && !reducedMotion ? 'always' : 'demand'}
            camera={{ position: [4.5, 2.8, 6], fov: 38, near: 0.01, far: 10_000 }}
            gl={{ antialias: !lowQuality, powerPreference: 'high-performance' }}
          >
            <color attach="background" args={['#04070d']} />
            <fog attach="fog" args={['#04070d', 14, 34]} />
            <ambientLight intensity={1.05} />
            <hemisphereLight args={['#b8e8ff', '#0b0d14', 1.7]} />
            <directionalLight position={[5, 8, 4]} intensity={2.8} color="#d9f6ff" />
            <spotLight position={[-6, 5, 1]} intensity={35} angle={0.45} penumbra={0.9} color="#3d7cff" />
            <spotLight position={[4, 2, -5]} intensity={24} angle={0.55} penumbra={1} color="#00f2fe" />
            <Bounds fit clip observe margin={1.25}>
              <Center>
                <primitive object={scene} />
              </Center>
              <FitCamera signal={resetSignal} />
            </Bounds>
            {showGrid && (
              <Grid
                position={[0, -1.4, 0]}
                args={[28, 28]}
                cellSize={0.5}
                cellThickness={0.4}
                cellColor="#1b4764"
                sectionSize={2.5}
                sectionThickness={0.8}
                sectionColor="#087f9a"
                fadeDistance={28}
                fadeStrength={1.5}
                infiniteGrid
              />
            )}
            <OrbitControls
              makeDefault
              enableDamping
              autoRotate={autoRotate && !reducedMotion}
              autoRotateSpeed={0.75}
              minDistance={0.05}
              maxDistance={5_000}
            />
            <PerformanceMonitor onDecline={() => setLowQuality(true)} />
            <ContextLossGuard onLost={() => setContextLost(true)} />
          </Canvas>
        </ModelErrorBoundary>
      )}

      <div className="model-view-controls" aria-label="3D 视图控制">
        <button type="button" onClick={() => setResetSignal(value => value + 1)}><RotateCcw size={15} /> 重置</button>
        <button
          type="button"
          aria-pressed={autoRotate && !reducedMotion}
          disabled={reducedMotion}
          onClick={() => setAutoRotate(value => !value)}
        >{autoRotate ? <Pause size={15} /> : <Play size={15} />} 环绕</button>
        <button type="button" aria-pressed={showGrid} onClick={() => setShowGrid(value => !value)}><Grid3X3 size={15} /> 网格</button>
        <button type="button" aria-pressed={lowQuality} onClick={() => setLowQuality(value => !value)}><Gauge size={15} /> 省电</button>
        <button type="button" onClick={enterFullscreen}><Maximize2 size={15} /> 全屏</button>
      </div>

      <div className="model-gesture-hint">拖动旋转 · 滚轮或双指缩放 · 右键平移</div>
    </div>
  );
}
