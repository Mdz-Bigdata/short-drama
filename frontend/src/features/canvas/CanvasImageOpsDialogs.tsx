import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { Loader2 } from 'lucide-react';

import { apiUrl } from '../../api/client';
import { t } from '../../i18n';
import {
  CROP_ASPECTS, CROP_HANDLES, DEFAULT_CROP, aspectFits, cropPixels, fitAspect, moveRect, resizeRect, roundRect, unitRatio,
  type CropAspectId, type CropHandle, type CropRect,
} from './canvasCropMath';
import { cropNode, splitNode, type ImagePieces } from './canvasImageOpsApi';
import './CanvasNodeActions.css';

/** Rows and columns a split may have, each; 1 × 1 is the picture itself and is not a split. */
export const GRID_MAX = 12;
const GRID_PRESETS: ReadonlyArray<readonly [number, number]> = [[2, 2], [3, 3], [4, 4], [1, 3], [3, 1]];
const NUDGE = 0.01;
const NUDGE_FAST = 0.05;

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function useEscape(onClose: () => void) {
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onClose]);
}

interface ImageOpProps {
  projectId: string;
  canvasId: string;
  nodeId: string;
  /** The node's name, for the dialog's heading. */
  nodeLabel: string;
  /** The picture as the canvas shows it. */
  imageUrl: string;
  /** Saves what is unsaved and answers the version to work on: the server reads the picture from the stored canvas. */
  prepare: () => Promise<number>;
  onApplied: (result: ImagePieces) => void | Promise<void>;
  onClose: () => void;
}

function aspectLabel(id: CropAspectId) {
  return id === 'free' ? t('自由') : id;
}

/**
 * Crop a node's picture: drag the rectangle or its handles, optionally held to a shape, and confirm.
 *
 * The cut is made on the server from the stored picture (`backend/app/service/canvas_image_ops.py`),
 * and the piece arrives as a new media node beside this one. After NovaNova Studio's canvas crop (MIT).
 */
export function CanvasCropDialog({ projectId, canvasId, nodeId, nodeLabel, imageUrl, prepare, onApplied, onClose }: ImageOpProps) {
  const panel = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const [rect, setRect] = useState<CropRect>(DEFAULT_CROP);
  const [aspect, setAspect] = useState<CropAspectId>('free');
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(null);
  const [broken, setBroken] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const drag = useRef<{ stop: () => void } | null>(null);

  useEscape(onClose);
  useEffect(() => { panel.current?.focus(); }, []);
  useEffect(() => () => drag.current?.stop(), []);

  const ratioOf = useCallback((id: CropAspectId) => unitRatio(CROP_ASPECTS.find(item => item.id === id)?.ratio ?? null, natural), [natural]);
  const locked = ratioOf(aspect);

  const pickAspect = (id: CropAspectId) => {
    setAspect(id);
    setRect(current => fitAspect(current, ratioOf(id)));
  };

  /** Follow the pointer from a press on the rectangle (move) or one of its handles (resize) until it lifts. */
  const press = (event: ReactPointerEvent<HTMLElement>, handle: CropHandle | null) => {
    if (event.button !== 0 || busy) return;
    const box = stage.current?.getBoundingClientRect();
    if (!box || !box.width || !box.height) return;
    event.preventDefault();
    event.stopPropagation();
    drag.current?.stop();
    const start = { x: event.clientX, y: event.clientY, rect };
    const move = (moved: PointerEvent) => {
      const dx = (moved.clientX - start.x) / box.width;
      const dy = (moved.clientY - start.y) / box.height;
      setRect(handle ? resizeRect(start.rect, handle, dx, dy, locked) : moveRect(start.rect, dx, dy));
    };
    const stop = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
      drag.current = null;
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop);
    window.addEventListener('pointercancel', stop);
    drag.current = { stop };
  };

  const nudge = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (!event.key.startsWith('Arrow') || busy) return;
    event.preventDefault();
    event.stopPropagation();
    const step = event.shiftKey ? NUDGE_FAST : NUDGE;
    const dx = event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0;
    const dy = event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : 0;
    setRect(current => moveRect(current, dx, dy));
  };

  const apply = async () => {
    if (busy || !natural) return;
    setBusy(true);
    setProblem('');
    try {
      const version = await prepare();
      const result = await cropNode(projectId, canvasId, nodeId, roundRect(rect), version);
      await onApplied(result);
      onClose();
    } catch (error) {
      setProblem(messageOf(error, t('裁剪失败')));
      setBusy(false);
    }
  };

  const title = t('裁剪：{0}', [nodeLabel]);
  const pixels = natural ? cropPixels(rect, natural) : null;
  const percent = (value: number) => `${value * 100}%`;
  return (
    <div className="cn-dialog-backdrop">
      <div ref={panel} className="cn-dialog cio-dialog" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
        <h2>{title}</h2>
        <p className="cn-hint">{t('拖动方框或它的边角选出要留下的部分。裁出来的是一个新的素材节点，放在这个节点右边；原图不变。')}</p>
        <div className="cio-aspects" role="group" aria-label={t('裁剪比例')}>
          {CROP_ASPECTS.map(item => (
            <button
              key={item.id} type="button" className="cn-button" aria-pressed={aspect === item.id}
              disabled={busy || (item.ratio !== null && (!natural || !aspectFits(unitRatio(item.ratio, natural))))}
              onClick={() => pickAspect(item.id)}
            >
              {aspectLabel(item.id)}
            </button>
          ))}
        </div>
        <div className="cio-frame">
          <div ref={stage} className="cio-stage">
            <img
              className="cio-image" src={apiUrl(imageUrl)} alt={nodeLabel} draggable={false}
              onLoad={event => setNatural({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}
              onError={() => setBroken(true)}
            />
            {natural && (
              <div
                className="cio-crop" role="group" tabIndex={0} aria-label={t('裁剪范围')}
                style={{ left: percent(rect.x), top: percent(rect.y), width: percent(rect.w), height: percent(rect.h) }}
                data-rect={`${rect.x},${rect.y},${rect.w},${rect.h}`}
                onPointerDown={event => press(event, null)} onKeyDown={nudge}
              >
                {CROP_HANDLES.map(handle => (
                  <span key={handle} className={`cio-handle is-${handle}`} data-handle={handle} aria-hidden="true" onPointerDown={event => press(event, handle)} />
                ))}
              </div>
            )}
          </div>
        </div>
        {pixels && <p className="cn-dialog__cost">{t('裁出 {0} × {1} 像素', [pixels.width, pixels.height])}</p>}
        {broken && <p className="cn-error" role="alert">{t('图片加载失败，裁不了。')}</p>}
        {problem && <p className="cn-error" role="alert">{problem}</p>}
        <footer className="cn-dialog__foot">
          <button type="button" className="cn-button" onClick={onClose}>{t('取消')}</button>
          <button type="button" className="cn-button is-primary" disabled={busy || !natural} onClick={() => { void apply(); }}>
            {busy && <Loader2 className="cn-spin" aria-hidden="true" />} {t('裁剪')}
          </button>
        </footer>
      </div>
    </div>
  );
}

function wholeCount(value: string): number | null {
  if (!/^\d{1,3}$/.test(value.trim())) return null;
  const number = Number(value.trim());
  return number >= 1 && number <= GRID_MAX ? number : null;
}

/**
 * Cut a node's picture into rows × columns: every cell becomes a media node, laid out beside this one
 * as the grid they came from. After NovaNova Studio's grid split (MIT); cut on the server.
 */
export function CanvasGridSplitDialog({ projectId, canvasId, nodeId, nodeLabel, imageUrl, prepare, onApplied, onClose }: ImageOpProps) {
  const first = useRef<HTMLInputElement>(null);
  const [rowsText, setRowsText] = useState('2');
  const [columnsText, setColumnsText] = useState('2');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');

  useEscape(onClose);
  useEffect(() => { first.current?.focus(); first.current?.select(); }, []);

  const rows = wholeCount(rowsText);
  const columns = wholeCount(columnsText);
  const single = rows === 1 && columns === 1;
  const valid = rows !== null && columns !== null && !single;

  const apply = async () => {
    if (busy || !valid) return;
    setBusy(true);
    setProblem('');
    try {
      const version = await prepare();
      const result = await splitNode(projectId, canvasId, nodeId, { rows: rows!, columns: columns! }, version);
      await onApplied(result);
      onClose();
    } catch (error) {
      setProblem(messageOf(error, t('拆分失败')));
      setBusy(false);
    }
  };

  const title = t('宫格拆分：{0}', [nodeLabel]);
  return (
    <div className="cn-dialog-backdrop">
      <form className="cn-dialog cio-dialog" role="dialog" aria-modal="true" aria-label={title} onSubmit={event => { event.preventDefault(); void apply(); }}>
        <h2>{title}</h2>
        <p className="cn-hint">{t('按行数和列数把这张图切开，每一格变成一个新的素材节点，照原来的排法放在这个节点右边；原图不变。')}</p>
        <div className="cio-counts">
          <label className="cn-field">
            <span>{t('行数')}</span>
            <input ref={first} type="number" inputMode="numeric" min={1} max={GRID_MAX} step={1} value={rowsText} onChange={event => setRowsText(event.target.value)} />
          </label>
          <label className="cn-field">
            <span>{t('列数')}</span>
            <input type="number" inputMode="numeric" min={1} max={GRID_MAX} step={1} value={columnsText} onChange={event => setColumnsText(event.target.value)} />
          </label>
          <div className="cio-presets" role="group" aria-label={t('常用宫格')}>
            {GRID_PRESETS.map(([presetRows, presetColumns]) => (
              <button
                key={`${presetRows}x${presetColumns}`} type="button" className="cn-button" disabled={busy}
                aria-pressed={rows === presetRows && columns === presetColumns}
                onClick={() => { setRowsText(String(presetRows)); setColumnsText(String(presetColumns)); }}
              >
                {presetRows} × {presetColumns}
              </button>
            ))}
          </div>
        </div>
        <div className="cio-frame">
          <div className="cio-stage">
            <img className="cio-image" src={apiUrl(imageUrl)} alt={nodeLabel} draggable={false} />
            {valid && (
              <div className="cio-grid" aria-hidden="true" style={{ gridTemplateColumns: `repeat(${columns}, 1fr)`, gridTemplateRows: `repeat(${rows}, 1fr)` }}>
                {Array.from({ length: rows! * columns! }, (_, index) => <span key={index} />)}
              </div>
            )}
          </div>
        </div>
        {valid && <p className="cn-dialog__cost">{t('将拆成 {0} 张图片', [rows! * columns!])}</p>}
        {single && <p className="cn-error" role="alert">{t('1 × 1 就是原图本身，不用拆分。')}</p>}
        {!single && !valid && <p className="cn-error" role="alert">{t('行数和列数都要是 1 到 {0} 之间的整数。', [GRID_MAX])}</p>}
        {problem && <p className="cn-error" role="alert">{problem}</p>}
        <footer className="cn-dialog__foot">
          <button type="button" className="cn-button" onClick={onClose}>{t('取消')}</button>
          <button type="submit" className="cn-button is-primary" disabled={busy || !valid}>
            {busy && <Loader2 className="cn-spin" aria-hidden="true" />} {t('拆分')}
          </button>
        </footer>
      </form>
    </div>
  );
}
