import { Maximize2, Minus, Plus, RotateCcw, X } from 'lucide-react';
import {
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type WheelEvent as ReactWheelEvent,
  useEffect,
  useId,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';

import './AssetImageViewer.css';


export interface AssetImageViewerAsset {
  kind: 'actor' | 'scene' | 'prop' | 'costume' | 'effect';
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
};

interface Props {
  asset: AssetImageViewerAsset;
  onClose: () => void;
}

interface FocusPoint {
  x: number;
  y: number;
}

const MIN_ZOOM = 1;
const MAX_ZOOM = 4;
const ZOOM_STEP = 0.5;

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function roundZoom(value: number): number {
  return Math.round(value * 10) / 10;
}


export default function AssetImageViewer({ asset, onClose }: Props) {
  const [zoom, setZoom] = useState(MIN_ZOOM);
  const [focusPoint, setFocusPoint] = useState<FocusPoint>({ x: 50, y: 50 });
  const dialogRef = useRef<HTMLElement>(null);
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

  const changeZoom = (delta: number) => {
    setZoom(current => roundZoom(clamp(current + delta, MIN_ZOOM, MAX_ZOOM)));
  };

  const resetView = () => {
    setZoom(MIN_ZOOM);
    setFocusPoint({ x: 50, y: 50 });
  };

  const updateFocusPoint = (clientX: number, clientY: number, target: HTMLElement) => {
    const bounds = target.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    setFocusPoint({
      x: Math.round(clamp(((clientX - bounds.left) / bounds.width) * 100, 0, 100)),
      y: Math.round(clamp(((clientY - bounds.top) / bounds.height) * 100, 0, 100)),
    });
  };

  const inspectDetail = (event: ReactMouseEvent<HTMLButtonElement>) => {
    updateFocusPoint(event.clientX, event.clientY, event.currentTarget);
    changeZoom(ZOOM_STEP);
  };

  const zoomWithWheel = (event: ReactWheelEvent<HTMLButtonElement>) => {
    event.preventDefault();
    updateFocusPoint(event.clientX, event.clientY, event.currentTarget);
    changeZoom(event.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP);
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
          <button ref={closeButtonRef} type="button" aria-label="关闭全景查看器" onClick={onClose}>
            <X aria-hidden="true" />
          </button>
        </header>

        <div className="asset-image-viewer__canvas">
          <button
            type="button"
            className={`asset-image-viewer__stage${zoom > MIN_ZOOM ? ' is-zoomed' : ''}`}
            aria-label={`点击${kindLabel}全景图局部放大`}
            onClick={inspectDetail}
            onWheel={zoomWithWheel}
          >
            <img
              src={asset.imageUrl}
              alt={`${asset.name} ${kindLabel}全景图`}
              draggable={false}
              style={{
                transform: `scale(${zoom})`,
                transformOrigin: `${focusPoint.x}% ${focusPoint.y}%`,
              }}
            />
          </button>
          <div className="asset-image-viewer__position" aria-live="polite">
            <Maximize2 aria-hidden="true" />
            <span>观察位置 X {focusPoint.x}% · Y {focusPoint.y}%</span>
          </div>
        </div>

        <footer className="asset-image-viewer__controls">
          <div>
            <button type="button" aria-label="缩小" onClick={() => changeZoom(-ZOOM_STEP)} disabled={zoom <= MIN_ZOOM}>
              <Minus aria-hidden="true" />
            </button>
            <output role="status" aria-label="当前缩放比例" aria-live="polite">{zoom.toFixed(1)}×</output>
            <button type="button" aria-label="放大" onClick={() => changeZoom(ZOOM_STEP)} disabled={zoom >= MAX_ZOOM}>
              <Plus aria-hidden="true" />
            </button>
            <button type="button" className="asset-image-viewer__reset" onClick={resetView}>
              <RotateCcw aria-hidden="true" /> 全景复位
            </button>
          </div>
          <p>点击任意细节定位并放大；支持滚轮、键盘 + / − 缩放，按 0 复位，Esc 关闭。</p>
        </footer>
      </section>
    </div>,
    document.body,
  );
}
