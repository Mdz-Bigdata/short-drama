import { Hand, MousePointer2 } from 'lucide-react';

import { t } from '../../i18n';
import type { CanvasTool } from './canvasBeefTool';
import './CanvasBeef.css';

/** Select (V) or hand (H): with the hand, a left drag moves the view instead of selecting. */
export function CanvasBeefToolToggle({ tool, onChange }: { tool: CanvasTool; onChange: (tool: CanvasTool) => void }) {
  return (
    <div className="canvas-beef-tools" role="radiogroup" aria-label={t('画布工具')}>
      <button type="button" role="radio" aria-checked={tool === 'select'} title={t('选择（V）')} onClick={() => onChange('select')}>
        <MousePointer2 size={15} aria-hidden="true" /><span className="sr-only">{t('选择')}</span>
      </button>
      <button type="button" role="radio" aria-checked={tool === 'hand'} title={t('抓手（H）：拖动画面')} onClick={() => onChange('hand')}>
        <Hand size={15} aria-hidden="true" /><span className="sr-only">{t('抓手')}</span>
      </button>
    </div>
  );
}
