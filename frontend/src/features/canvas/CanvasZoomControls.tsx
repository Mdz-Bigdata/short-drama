// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/components/canvas/canvas-zoom-controls.tsx.
import { useEffect, useId, useRef, useState } from 'react';
import { Focus, Minus, Plus, ScanSearch } from 'lucide-react';

import { t } from '../../i18n';
import { MAX_ZOOM, MIN_ZOOM } from './canvasGeometry';
import { ZOOM_PRESETS } from './canvasViewportAnimation';
import './CanvasZoomControls.css';

export interface CanvasZoomControlsProps {
  zoom: number;
  onZoomTo: (zoom: number) => void;
  onStep: (dir: 1 | -1) => void;
  onFitAll: () => void;
  onFitSelection?: () => void;
  hasSelection: boolean;
}

const MIN_PERCENT = Math.round(MIN_ZOOM * 100);
const MAX_PERCENT = Math.round(MAX_ZOOM * 100);

export function CanvasZoomControls({ zoom, onZoomTo, onStep, onFitAll, onFitSelection, hasSelection }: CanvasZoomControlsProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const popoverId = useId();
  const percent = Math.round(zoom * 100);

  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', close, true);
    document.addEventListener('keydown', closeOnEscape, true);
    return () => {
      document.removeEventListener('pointerdown', close, true);
      document.removeEventListener('keydown', closeOnEscape, true);
    };
  }, [open]);

  const zoomTo = (next: number) => onZoomTo(Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, next)));

  return (
    <div
      ref={root}
      className="cz-root"
      role="toolbar"
      aria-label={t('画布缩放')}
      data-canvas-no-zoom
      onPointerDown={event => event.stopPropagation()}
      onWheel={event => event.stopPropagation()}
    >
      {open && (
        <div id={popoverId} className="cz-popover" role="dialog" aria-label={t('精确缩放')}>
          <div className="cz-popover-head">
            <span>{t('缩放比例')}</span>
            <span className="cz-popover-value">{percent}%</span>
          </div>
          <input
            className="cz-range"
            type="range"
            min={MIN_PERCENT}
            max={MAX_PERCENT}
            step={1}
            value={Math.min(MAX_PERCENT, Math.max(MIN_PERCENT, percent))}
            aria-label={t('缩放比例')}
            onChange={event => zoomTo(Number(event.target.value) / 100)}
          />
          <div className="cz-presets">
            {ZOOM_PRESETS.map(level => (
              <button
                key={level}
                type="button"
                className="cz-preset"
                aria-pressed={Math.abs(zoom - level) < 0.005}
                onClick={() => zoomTo(level)}
              >
                {Math.round(level * 100)}%
              </button>
            ))}
          </div>
        </div>
      )}
      <button type="button" className="cz-button" aria-label={t('缩小')} title={t('缩小')} disabled={zoom <= MIN_ZOOM + 1e-6} onClick={() => onStep(-1)}>
        <Minus size={14} aria-hidden />
      </button>
      <button
        type="button"
        className="cz-percent"
        aria-label={t('精确缩放')}
        aria-expanded={open}
        aria-controls={open ? popoverId : undefined}
        aria-haspopup="dialog"
        title={t('精确缩放')}
        onClick={() => setOpen(value => !value)}
      >
        {percent}%
      </button>
      <button type="button" className="cz-button" aria-label={t('放大')} title={t('放大')} disabled={zoom >= MAX_ZOOM - 1e-6} onClick={() => onStep(1)}>
        <Plus size={14} aria-hidden />
      </button>
      <span className="cz-divider" aria-hidden />
      <button type="button" className="cz-button" aria-label={t('适应画布')} title={t('适应画布')} onClick={onFitAll}>
        <Focus size={14} aria-hidden />
      </button>
      {onFitSelection && (
        <button type="button" className="cz-button" aria-label={t('适应选区')} title={t('适应选区')} disabled={!hasSelection} onClick={onFitSelection}>
          <ScanSearch size={14} aria-hidden />
        </button>
      )}
    </div>
  );
}
