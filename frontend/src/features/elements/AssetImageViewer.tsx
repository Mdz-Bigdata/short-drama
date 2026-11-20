import { Maximize2, Minus, Plus, RotateCcw, X } from 'lucide-react';
import {
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  useEffect,
  useId,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';

import './AssetImageViewer.css';
import { centreOn, INITIAL_VIEW, MAX_ZOOM, MIN_ZOOM, wheelZoomFactor, zoomAtPointer, zoomBy, ZOOM_STEP, type ViewPoint } from './assetImageZoom';
import { t } from '../../i18n';


export interface AssetImageViewerAsset {
  kind: 'actor' | 'scene' | 'prop' | 'costume' | 'effect' | 'product' | 'extra' | 'vehicle' | 'stunt' | 'set_dressing' | 'makeup';
  name: string;
  description: string;
  imageUrl: string;
}

/* 五类资产在查看器里的中文名；服装/特效沿用原有文案 */
const viewerKindLabels: Record<AssetImageViewerAsset['kind'], string> = {
  actor: '数字演员',
  scene: '拍摄场地',
  prop: '拍摄道具',
  costume: '服装',
  effect: '特效',
  product: '商品',
  extra: '群演',
  vehicle: '车辆',
  stunt: '特技',
  set_dressing: '置景',
  makeup: '化妆',
};

interface Props {
  asset: AssetImageViewerAsset;
  onClose: () => void;
}

// 写进样式的百分比留两位小数就够。
function percent(value: number): number {
  return Math.round(value * 100) / 100;
}

// 倍数留四位：样式里不必带十几位小数，慢滚的每一小步又都还看得出来。
function scaleOf(zoom: number): number {
  return Math.round(zoom * 10000) / 10000;
}

/** 指针在舞台里的位置(百分比)；舞台还没有尺寸时没有位置。 */
function pointerIn(stage: HTMLElement, event: { clientX: number; clientY: number }): ViewPoint | null {
  const bounds = stage.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return null;
  const share = (offset: number, size: number) => Math.min(100, Math.max(0, (offset / size) * 100));
  return { x: share(event.clientX - bounds.left, bounds.width), y: share(event.clientY - bounds.top, bounds.height) };
}


export default function AssetImageViewer({ asset, onClose }: Props) {
  const [view, setView] = useState(INITIAL_VIEW);
  const { zoom, origin, focus } = view;
  const dialogRef = useRef<HTMLElement>(null);
  const stageRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const descriptionId = useId();
  const kindLabel = viewerKindLabels[asset.kind];

  useEffect(() => {
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeButtonRef.current?.focus();

    return () => {
      document.body.style.overflow = previousOverflow;
      returnFocusRef.current?.focus();
    };
  }, []);

  // React 的 onWheel 是被动监听，拦不住浏览器跟着缩放整页，所以滚轮直接挂在舞台上。
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return undefined;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      const pointer = pointerIn(stage, event);
      // 触控板捏合是带 ctrl 的滚轮事件。
      const factor = wheelZoomFactor(event.deltaY, event.ctrlKey);
      setView(current => (pointer ? zoomAtPointer(current, pointer, current.zoom * factor) : zoomBy(current, current.zoom * (factor - 1))));
    };
    stage.addEventListener('wheel', wheel, { passive: false });
    return () => stage.removeEventListener('wheel', wheel);
  }, []);

  const changeZoom = (delta: number) => setView(current => zoomBy(current, delta));

  const resetView = () => setView(INITIAL_VIEW);

  const inspectDetail = (event: ReactMouseEvent<HTMLButtonElement>) => {
    // 键盘按下的点击没有指针位置(坐标全是 0)：绕当前中心放大，不跳去左上角。
    const fromKeyboard = event.detail === 0 && event.clientX === 0 && event.clientY === 0;
    const pointer = fromKeyboard ? null : pointerIn(event.currentTarget, event);
    setView(current => {
      if (!pointer) return zoomBy(current, ZOOM_STEP);
      return current.zoom >= MAX_ZOOM ? centreOn(current, pointer) : zoomAtPointer(current, pointer, current.zoom + ZOOM_STEP);
    });
  };

  const handleDialogKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key === '+' || event.key === '=') {
      event.preventDefault();
      changeZoom(ZOOM_STEP);
      return;
    }
    if (event.key === '-') {
      event.preventDefault();
      changeZoom(-ZOOM_STEP);
      return;
    }
    if (event.key === '0') {
      event.preventDefault();
      resetView();
      return;
    }
    if (event.key !== 'Tab') return;

    const controls = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
    ) ?? []);
    if (controls.length === 0) return;
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return createPortal(
    <div
      className="asset-image-viewer__backdrop"
      role="presentation"
      onMouseDown={event => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={dialogRef}
        className="asset-image-viewer"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        onKeyDown={handleDialogKeyDown}
      >
        <header className="asset-image-viewer__header">
          <div>
            <span>{kindLabel.toUpperCase()} / PANORAMA DETAIL</span>
            <h2 id={titleId}>{asset.name} · {kindLabel}全景细节</h2>
            <p id={descriptionId}>{asset.description}</p>
          </div>
          <button ref={closeButtonRef} type="button" aria-label={t('关闭全景查看器')} onClick={onClose}>
            <X aria-hidden="true" />
          </button>
        </header>

        <div className="asset-image-viewer__canvas">
          <button
            ref={stageRef}
            type="button"
            className={`asset-image-viewer__stage${zoom > MIN_ZOOM ? ' is-zoomed' : ''}`}
            aria-label={`点击${kindLabel}全景图局部放大`}
            onClick={inspectDetail}
          >
            <img
              src={asset.imageUrl}
              alt={`${asset.name} ${kindLabel}全景图`}
              draggable={false}
              style={{
                transform: `scale(${scaleOf(zoom)})`,
                transformOrigin: `${percent(origin.x)}% ${percent(origin.y)}%`,
              }}
            />
          </button>
          <div className="asset-image-viewer__position" aria-live="polite">
            <Maximize2 aria-hidden="true" />
            <span>观察位置 X {Math.round(focus.x)}% · Y {Math.round(focus.y)}%</span>
          </div>
        </div>

        <footer className="asset-image-viewer__controls">
          <div>
            <button type="button" aria-label={t('缩小')} onClick={() => changeZoom(-ZOOM_STEP)} disabled={zoom <= MIN_ZOOM}>
              <Minus aria-hidden="true" />
            </button>
            <output role="status" aria-label={t('当前缩放比例')} aria-live="polite">{zoom.toFixed(1)}×</output>
            <button type="button" aria-label={t('放大')} onClick={() => changeZoom(ZOOM_STEP)} disabled={zoom >= MAX_ZOOM}>
              <Plus aria-hidden="true" />
            </button>
            <button type="button" className="asset-image-viewer__reset" onClick={resetView}>
              <RotateCcw aria-hidden="true" /> {t('全景复位')}
            </button>
          </div>
          <p>{t('点击任意细节定位并放大；支持滚轮、键盘 + / − 缩放，按 0 复位，Esc 关闭。')}</p>
        </footer>
      </section>
    </div>,
    document.body,
  );
}
