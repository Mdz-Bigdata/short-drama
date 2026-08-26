import { Canvas } from '@react-three/fiber';
import {
  Box,
  Camera,
  ChevronDown,
  ExternalLink,
  Heart,
  Pause,
  Play,
  RotateCcw,
} from 'lucide-react';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from 'react';

import MuseumCellScene, { type MuseumModelStatus } from './MuseumCellScene';
import {
  getMuseumItemById,
  museumAsset,
  museumCatalog,
  type MuseumCatalogItem,
} from './museumCatalog';
import './MuseumAssetExperience.css';


type MuseumAssetExperienceProps = {
  kind: 'scene' | 'prop';
};


function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => (
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(query).matches
      : false
  ));

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener?.('change', update);
    return () => media.removeEventListener?.('change', update);
  }, [query]);

  return matches;
}


function supportsWebGL2() {
  if (typeof window === 'undefined' || !window.WebGL2RenderingContext) return false;
  try {
    return Boolean(document.createElement('canvas').getContext('webgl2'));
  } catch {
    return false;
  }
}


function ArtifactThumbnail({ item }: { item: MuseumCatalogItem }) {
  return (
    <span className="museum-thumbnail" aria-hidden="true">
      <img src={museumAsset(item.thumbnail)} alt="" loading="lazy" />
    </span>
  );
}


function ArtifactRail({
  selected,
  onSelect,
}: {
  selected: MuseumCatalogItem;
  onSelect: (id: string) => void;
}) {
  return (
    <nav className="museum-catalog" aria-label="文物目录">
      <div className="museum-section-kicker">典藏目录 · 08</div>
      {museumCatalog.map((item, index) => (
        <button
          type="button"
          key={item.id}
          className={item.id === selected.id ? 'is-active' : undefined}
          aria-current={item.id === selected.id ? 'true' : undefined}
          aria-label={`切换到${item.name}`}
          onClick={() => onSelect(item.id)}
        >
          <span className="museum-catalog-index">{String(index + 1).padStart(2, '0')}</span>
          <ArtifactThumbnail item={item} />
          <span className="museum-catalog-copy">
            <strong>{item.name}</strong>
            <small>{item.type}</small>
          </span>
          <span className="museum-era">{item.era}</span>
        </button>
      ))}
    </nav>
  );
}


function MobileArtifactSwitcher({
  selected,
  onSelect,
}: {
  selected: MuseumCatalogItem;
  onSelect: (id: string) => void;
}) {
  return (
    <nav className="museum-mobile-switcher" aria-label="移动端文物切换">
      {museumCatalog.map(item => (
        <button
          type="button"
          key={item.id}
          className={item.id === selected.id ? 'is-active' : undefined}
          aria-current={item.id === selected.id ? 'true' : undefined}
          aria-label={`移动端切换到${item.name}`}
          onClick={() => onSelect(item.id)}
        >
          <ArtifactThumbnail item={item} />
          <strong>{item.name}</strong>
          <small>{item.era}</small>
        </button>
      ))}
    </nav>
  );
}


function MuseumPlaque({ item }: { item: MuseumCatalogItem }) {
  return (
    <article className="museum-plaque" aria-label={`${item.name}展签`}>
      <span className="museum-section-kicker">01 · 它是什么</span>
      <h2>{item.name}</h2>
      <p className="museum-plaque-type">{item.type}</p>
      <p className="museum-plaque-intro">{item.intro}</p>
      <dl>
        <div>
          <dt>年代</dt>
          <dd>{item.dynasty}</dd>
        </div>
        <div>
          <dt>出土地</dt>
          <dd>{item.origin}</dd>
        </div>
        <div>
          <dt>现藏</dt>
          <dd>
            {item.museum}
            {item.museumAbroad && <em>流落海外</em>}
          </dd>
        </div>
      </dl>
    </article>
  );
}


function MuseumStageFallback({
  item,
  state,
  webglAvailable,
}: {
  item: MuseumCatalogItem;
  state: MuseumModelStatus;
  webglAvailable: boolean;
}) {
  if (state.state === 'ready' && webglAvailable) return null;

  const title = !webglAvailable
    ? '当前设备暂不支持 WebGL 2'
    : state.state === 'error'
      ? '3D 模型暂时无法显示'
      : '正在唤醒数字文物';
  const detail = !webglAvailable
    ? '已切换为高清藏品海报，展签和全部资料仍可浏览。'
    : state.state === 'error'
      ? state.message
      : `正在加载 ${item.name} · 本地 Draco 解码器`;

  return (
    <div className={`museum-stage-fallback ${state.state === 'loading' ? 'is-loading' : ''}`}>
      <img src={museumAsset(item.thumbnail)} alt={`${item.name}海报`} />
      <div>
        {state.state === 'loading' && <span className="museum-loader" aria-hidden="true" />}
        <strong>{title}</strong>
        <p>{detail}</p>
      </div>
    </div>
  );
}


function MuseumStage({
  item,
  autoRotate,
  resetKey,
  lowQuality,
  webglAvailable,
  modelStatus,
  onStatusChange,
  onAutoRotateChange,
  onReset,
  onCapture,
}: {
  item: MuseumCatalogItem;
  autoRotate: boolean;
  resetKey: number;
  lowQuality: boolean;
  webglAvailable: boolean;
  modelStatus: MuseumModelStatus;
  onStatusChange: (status: MuseumModelStatus) => void;
  onAutoRotateChange: () => void;
  onReset: () => void;
  onCapture: () => void;
}) {
  return (
    <section className="museum-stage" aria-label={`${item.name}三维展台`}>
      <div className="museum-stage-heading">
        <span>{item.dynasty}</span>
        <strong>{item.name}</strong>
        <small>可信静态 GLB · 本地 Draco</small>
      </div>

      <div className="museum-canvas-shell">
        {webglAvailable && (
          <Canvas
            className="museum-canvas"
            dpr={lowQuality ? 1 : [1, 2]}
            frameloop={autoRotate ? 'always' : 'demand'}
            shadows={!lowQuality}
            gl={{
              antialias: !lowQuality,
              alpha: true,
              powerPreference: lowQuality ? 'low-power' : 'high-performance',
              preserveDrawingBuffer: true,
            }}
            camera={{ position: [0, 0.2, 5.8], fov: 38 }}
          >
            <MuseumCellScene
              item={item}
              autoRotate={autoRotate}
              resetKey={resetKey}
              lowQuality={lowQuality}
              onStatusChange={onStatusChange}
            />
          </Canvas>
        )}
        <MuseumStageFallback item={item} state={modelStatus} webglAvailable={webglAvailable} />
        <span className="museum-stage-number">{museumCatalog.findIndex(entry => entry.id === item.id) + 1}/8</span>
      </div>

      <div className="museum-stage-tools" role="toolbar" aria-label="三维展台控制">
        <button
          type="button"
          className={autoRotate ? 'is-active' : undefined}
          aria-pressed={autoRotate}
          onClick={onAutoRotateChange}
        >
          {autoRotate ? <Pause size={16} /> : <Play size={16} />}
          {autoRotate ? '暂停旋转' : '自动旋转'}
        </button>
        <button type="button" onClick={onReset}>
          <RotateCcw size={16} />
          重置视角
        </button>
        <button type="button" onClick={onCapture} disabled={modelStatus.state !== 'ready'}>
          <Camera size={16} />
          保存截图
        </button>
      </div>
      <p className="museum-stage-hint">
        <Box size={14} />
        拖动旋转 · 滚轮或双指缩放 · 右键或双指移动
      </p>
    </section>
  );
}


function QuestionItem({ question, answer }: { question: string; answer: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={open ? 'museum-question is-open' : 'museum-question'}>
      <button type="button" aria-expanded={open} onClick={() => setOpen(value => !value)}>
        <span>{question}</span>
        <ChevronDown size={16} aria-hidden="true" />
      </button>
      {open && <p>{answer}</p>}
    </div>
  );
}


function MuseumInsightPanel({
  item,
  activeDetail,
  favorite,
  onSelectDetail,
  onToggleFavorite,
}: {
  item: MuseumCatalogItem;
  activeDetail: string;
  favorite: boolean;
  onSelectDetail: (id: string) => void;
  onToggleFavorite: () => void;
}) {
  const detail = item.organelles.find(entry => entry.id === activeDetail) ?? item.organelles[0];

  return (
    <aside className="museum-insights">
      <section className="museum-panel museum-detail-panel">
        <header>
          <span className="museum-section-kicker">02 · 看门道 · 细节</span>
          <button
            type="button"
            className={favorite ? 'is-favorite' : undefined}
            aria-label={favorite ? `取消收藏${item.name}` : `收藏${item.name}`}
            aria-pressed={favorite}
            onClick={onToggleFavorite}
          >
            <Heart size={20} fill={favorite ? 'currentColor' : 'none'} />
          </button>
        </header>
        <div className="museum-detail-tabs" role="tablist" aria-label="文物细节标签">
          {item.organelles.map(entry => (
            <button
              type="button"
              role="tab"
              key={entry.id}
              aria-selected={entry.id === detail.id}
              aria-label={`查看细节：${entry.name}`}
              className={entry.id === detail.id ? 'is-active' : undefined}
              onClick={() => onSelectDetail(entry.id)}
            >
              <i style={{ backgroundColor: entry.color }} />
              {entry.name}
            </button>
          ))}
        </div>
        <div className="museum-detail-copy" role="tabpanel">
          <span>{detail.subtitle}</span>
          <h3>{detail.name}</h3>
          <p>{detail.note}</p>
        </div>
      </section>

      {item.story && (
        <section className="museum-panel museum-story-panel">
          <span className="museum-section-kicker">03 · 听它说 · 文物的故事</span>
          {item.story.split('\n\n').map(paragraph => <p key={paragraph}>{paragraph}</p>)}
        </section>
      )}

      {item.qa && (
        <section className="museum-panel museum-qa-panel">
          <span className="museum-section-kicker">04 · 你可能好奇</span>
          {item.qa.map(entry => (
            <QuestionItem key={entry.q} question={entry.q} answer={entry.a} />
          ))}
        </section>
      )}

      <section className="museum-panel museum-source-panel">
        <span className="museum-section-kicker">05 · 数字资产来源</span>
        <p>模型来源：{item.modelAsset.sourceLabel}</p>
        <a href={item.modelAsset.sourceUrl} target="_blank" rel="noreferrer">
          查看 3D 模型来源
          <ExternalLink size={14} />
        </a>
      </section>
    </aside>
  );
}


export default function MuseumAssetExperience({ kind }: MuseumAssetExperienceProps) {
  const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)');
  const narrowScreen = useMediaQuery('(max-width: 760px)');
  const lowMemory = typeof navigator !== 'undefined'
    && ((navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 8) <= 4;
  const lowQuality = narrowScreen || lowMemory;
  const webglAvailable = useMemo(() => supportsWebGL2(), []);
  const initialItem = getMuseumItemById('owlZun');
  const [selectedId, setSelectedId] = useState(initialItem.id);
  const [activeDetail, setActiveDetail] = useState(initialItem.defaultOrganelle);
  const [favorites, setFavorites] = useState<Set<string>>(() => new Set());
  const [autoRotateChoice, setAutoRotateChoice] = useState<boolean | null>(null);
  const [resetKey, setResetKey] = useState(0);
  const [modelStatus, setModelStatus] = useState<MuseumModelStatus>(
    webglAvailable ? { state: 'loading' } : { state: 'error', message: 'WebGL 2 unavailable' },
  );
  const [toast, setToast] = useState<string | null>(null);
  const rootRef = useRef<HTMLElement>(null);
  const toastTimer = useRef<number | null>(null);
  const selectedItem = useMemo(() => getMuseumItemById(selectedId), [selectedId]);

  useEffect(() => () => {
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
  }, []);

  const showToast = useCallback((message: string) => {
    setToast(message);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2400);
  }, []);

  const selectItem = useCallback((id: string) => {
    const next = getMuseumItemById(id);
    setSelectedId(next.id);
    setActiveDetail(next.defaultOrganelle);
    setModelStatus(webglAvailable
      ? { state: 'loading' }
      : { state: 'error', message: 'WebGL 2 unavailable' });
  }, [webglAvailable]);

  const toggleFavorite = useCallback(() => {
    setFavorites(current => {
      const next = new Set(current);
      if (next.has(selectedItem.id)) next.delete(selectedItem.id);
      else next.add(selectedItem.id);
      return next;
    });
  }, [selectedItem.id]);

  const captureScreenshot = useCallback(() => {
    const canvas = rootRef.current?.querySelector('canvas');
    if (!canvas || modelStatus.state !== 'ready') {
      showToast('模型尚未就绪，请稍后再试。');
      return;
    }
    try {
      const link = document.createElement('a');
      link.href = canvas.toDataURL('image/png');
      link.download = `${selectedItem.name}-3d-museum.png`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      showToast('高清截图已保存。');
    } catch {
      showToast('截图失败，请检查浏览器下载权限。');
    }
  }, [modelStatus.state, selectedItem.name, showToast]);

  const shellStyle = { '--museum-accent': selectedItem.accent } as CSSProperties;
  const rotationEnabled = autoRotateChoice ?? !reducedMotion;

  return (
    <section
      ref={rootRef}
      className={`museum-experience museum-experience--${kind}`}
      style={shellStyle}
      aria-label={`${kind === 'scene' ? '场景' : '道具'}三维数字博物馆`}
    >
      <header className="museum-header">
        <div className="museum-brand">
          <img src={museumAsset('/museum/logo.png')} alt="数字博物馆标志" />
          <div>
            <p>穿越千年，触摸文明的温度</p>
            <h1>{kind === 'scene' ? '场景资产 · 文物数字展厅' : '道具资产 · 文物数字展厅'}</h1>
          </div>
        </div>
        <div className="museum-header-meta">
          <strong>08</strong>
          <span>件中国文物<br />3D 数字典藏</span>
          <a
            href="https://www.zybkpro.top/threejs/museum/"
            target="_blank"
            rel="noreferrer"
            aria-label="打开 zybkpro.top 原始在线展厅"
          >
            zybkpro.top 在线来源
            <ExternalLink size={13} />
          </a>
        </div>
      </header>

      <MobileArtifactSwitcher selected={selectedItem} onSelect={selectItem} />

      <div className="museum-layout">
        <aside className="museum-left-rail">
          <ArtifactRail selected={selectedItem} onSelect={selectItem} />
          <MuseumPlaque item={selectedItem} />
        </aside>

        <MuseumStage
          item={selectedItem}
          autoRotate={rotationEnabled}
          resetKey={resetKey}
          lowQuality={lowQuality}
          webglAvailable={webglAvailable}
          modelStatus={modelStatus}
          onStatusChange={setModelStatus}
          onAutoRotateChange={() => {
            setAutoRotateChoice(value => !(value ?? !reducedMotion));
          }}
          onReset={() => setResetKey(value => value + 1)}
          onCapture={captureScreenshot}
        />

        <MuseumInsightPanel
          item={selectedItem}
          activeDetail={activeDetail}
          favorite={favorites.has(selectedItem.id)}
          onSelectDetail={setActiveDetail}
          onToggleFavorite={toggleFavorite}
        />
      </div>

      <div className="museum-toast" aria-live="polite" aria-atomic="true">
        {toast}
      </div>
    </section>
  );
}
