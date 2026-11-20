import { Component, memo, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Bounds, Center, Environment, Grid, Lightformer, OrbitControls, PerformanceMonitor, useBounds } from '@react-three/drei';
import { Canvas, useThree } from '@react-three/fiber';
import { Box, Gauge, Grid3X3, Maximize2, Pause, Play, RotateCcw } from 'lucide-react';
import { BackSide, type Object3D } from 'three';
// three-stdlib's loaders are API-identical but do not embed `new URL` decoder
// fallbacks, which made Vite ship a duplicate ~1.3MB draco runtime in dist.
import { GLTFLoader } from 'three-stdlib';

import { API_BASE, apiUrl } from '../../../api/client';
import { disposeModelResources } from './disposeModelResources';
import { floorGridFor, largestSide } from './stageFloor';
import { STAGE_AMBIENT, STAGE_LIGHTS, STAGE_PANELS, STAGE_SURROUND } from './stageLights';
import { t } from '../../../i18n';


interface Props {
  name: string;
  contentUrl: string;
  posterUrl?: string;
}

// 和 ElementLibraryPage.css 的 --asset-stage-dark 同色：容器先铺这个底，画布出第一帧前不闪白。
const STAGE_BACKGROUND = '#0f0c12';

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

// 地面贴在模型脚下(Center top 把模型底面放到 y=0)，格子和淡出距离按模型的大小算。
function StageFloor({ scene }: { scene: Object3D }) {
  const floor = useMemo(() => floorGridFor(largestSide(scene)), [scene]);
  return (
    <Grid
      position={[0, -floor.drop, 0]}
      args={[28, 28]}
      cellSize={floor.cellSize}
      cellThickness={0.4}
      cellColor="#fef9fa"
      sectionSize={floor.sectionSize}
      sectionThickness={0.8}
      sectionColor="#e14962"
      fadeDistance={floor.fadeDistance}
      fadeStrength={1.5}
      infiniteGrid
    />
  );
}

// memo：环境贴图只在挂载时渲染一次，开关网格、省电这些重绘不必重做。
const StageLighting = memo(function StageLighting() {
  return (
    <>
      <ambientLight intensity={STAGE_AMBIENT.intensity} />
      <hemisphereLight args={[STAGE_AMBIENT.sky, STAGE_AMBIENT.ground, STAGE_AMBIENT.hemisphere]} />
      <directionalLight position={STAGE_LIGHTS.key.position} intensity={STAGE_LIGHTS.key.intensity} />
      <directionalLight position={STAGE_LIGHTS.fill.position} intensity={STAGE_LIGHTS.fill.intensity} />
      <directionalLight position={STAGE_LIGHTS.rim.position} intensity={STAGE_LIGHTS.rim.intensity} color={STAGE_LIGHTS.rim.color} />
      {/* 本地画出来的环境贴图，不取外网 HDR：没有它，金属材质无物可反射，近乎全黑。 */}
      <Environment resolution={256}>
        <mesh scale={40}>
          <sphereGeometry args={[1, 32, 16]} />
          <meshBasicMaterial color={STAGE_SURROUND} side={BackSide} toneMapped={false} />
        </mesh>
        {STAGE_PANELS.map(panel => (
          <Lightformer
            key={panel.position.join(',')}
            form="rect"
            position={panel.position}
            scale={panel.size}
            intensity={panel.intensity}
          />
        ))}
      </Environment>
    </>
  );
});

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
      {posterUrl ? <img src={posterUrl} alt={t('3D 资产参考图')} /> : <Box size={54} />}
      <strong>{t('3D 预览暂不可用')}</strong>
      <span>{message}</span>
      {onRetry && <button type="button" onClick={onRetry}>{t('重试加载')}</button>}
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

  const poster = posterUrl ? apiUrl(posterUrl) : undefined;
  const fallback = (
    <ModelFallback
      message={contextLost ? t('图形上下文已中断，请重试恢复。') : t('模型无法解析，可保留参考图并替换 GLB。')}
      posterUrl={poster}
      onRetry={retry}
    />
  );

  return (
    <div className="element-model-viewport" ref={container} role="region" aria-label={`${name} 3D 模型交互预览`}>
      {model.loading ? (
        <div className="model-fetch-state" role="status"><Gauge className="spin" /> {t('正在安全读取并解析 GLB…')}</div>
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
            <color attach="background" args={[STAGE_BACKGROUND]} />
            <StageLighting />
            <Bounds fit clip observe margin={1.25}>
              <Center top>
                <primitive object={scene} />
              </Center>
              <FitCamera signal={resetSignal} />
            </Bounds>
            {showGrid && <StageFloor scene={scene} />}
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

      <div className="model-view-controls" aria-label={t('3D 视图控制')}>
        <button type="button" onClick={() => setResetSignal(value => value + 1)}><RotateCcw size={15} /> {t('重置')}</button>
        <button
          type="button"
          aria-pressed={autoRotate && !reducedMotion}
          disabled={reducedMotion}
          onClick={() => setAutoRotate(value => !value)}
        >{autoRotate ? <Pause size={15} /> : <Play size={15} />} 环绕</button>
        <button type="button" aria-pressed={showGrid} onClick={() => setShowGrid(value => !value)}><Grid3X3 size={15} /> {t('网格')}</button>
        <button type="button" aria-pressed={lowQuality} onClick={() => setLowQuality(value => !value)}><Gauge size={15} /> {t('省电')}</button>
        <button type="button" onClick={enterFullscreen}><Maximize2 size={15} /> {t('全屏')}</button>
      </div>

      <div className="model-gesture-hint">{t('拖动旋转 · 滚轮或双指缩放 · 右键平移')}</div>
    </div>
  );
}
