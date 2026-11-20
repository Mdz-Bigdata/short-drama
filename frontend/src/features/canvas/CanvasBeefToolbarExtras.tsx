import { useEffect, useRef, useState } from 'react';
import { Palette, Table2 } from 'lucide-react';

import { t } from '../../i18n';
import { CanvasBeefAppearancePanel } from './CanvasBeefAppearancePanel';
import { CanvasBeefToolToggle } from './CanvasBeefToolToggle';
import type { CanvasAppearance } from './canvasBeefAppearance';
import type { CanvasTool } from './canvasBeefTool';
import './CanvasBeef.css';

export interface CanvasBeefToolbarExtrasProps {
  tool: CanvasTool;
  onTool: (tool: CanvasTool) => void;
  onBatch: () => void;
  canvasId: string;
  accountId: string;
  appearance: CanvasAppearance;
  onAppearance: (value: CanvasAppearance) => void;
}

/** Toolbar additions: the select / hand toggle, the batch creation table, and the board's appearance. */
export function CanvasBeefToolbarExtras({ tool, onTool, onBatch, canvasId, accountId, appearance, onAppearance }: CanvasBeefToolbarExtrasProps) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return undefined;
    const away = (event: PointerEvent) => { if (!box.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false); };
    window.addEventListener('pointerdown', away);
    window.addEventListener('keydown', escape);
    return () => { window.removeEventListener('pointerdown', away); window.removeEventListener('keydown', escape); };
  }, [open]);
  return (
    <>
      <CanvasBeefToolToggle tool={tool} onChange={onTool} />
      <button type="button" className="cn-icon" onClick={onBatch} aria-label={t('批量创作表')} title={t('批量创作表')}><Table2 aria-hidden="true" /></button>
      <span className="canvas-beef-popover-anchor" ref={box}>
        <button type="button" className="cn-icon" aria-expanded={open} onClick={() => setOpen(value => !value)} aria-label={t('画布外观')} title={t('画布外观')}>
          <Palette aria-hidden="true" />
        </button>
        {open && (
          <div className="canvas-beef-popover">
            <CanvasBeefAppearancePanel canvasId={canvasId} accountId={accountId} value={appearance} onChange={onAppearance} showGrid={false} />
          </div>
        )}
      </span>
    </>
  );
}
