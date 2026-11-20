import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { Maximize2, Sparkles, X } from 'lucide-react';

import { t } from '../../i18n';
import { CanvasBeefPromptOptimizer } from './CanvasBeefPromptOptimizer';
import { clampEditorSize as clampSize, defaultEditorSize, EDITOR_NUDGE as NUDGE } from './canvasBeefEditorSize';
import './CanvasBeef.css';

export interface CanvasBeefPromptEditorProps {
  /** The node being edited: a new node opens the editor at its default size again. */
  nodeId: string;
  taskId: string;
  medium: 'image' | 'video';
  text: string;
  targetModel?: string;
  references?: string[];
  imageReferences?: number;
  /** A clip node's length in seconds; the optimizer's timed script fills it exactly. */
  durationSeconds?: number;
  /** The canvas's enabled text models (run-options enabled.text) and its default (models.text). */
  textModels?: string[];
  defaultTextModel?: string;
  onApply: (text: string) => void;
  onClose: () => void;
}

/** A large editor for a picture or clip node's prompt, resizable from its corner, with the optimizer beside it. */
export function CanvasBeefPromptEditor(props: CanvasBeefPromptEditorProps) {
  // Keyed by node so switching nodes starts again at the default size.
  return <PromptEditor key={props.nodeId} {...props} />;
}

function PromptEditor({ taskId, medium, text, targetModel, references = [], imageReferences = 0, durationSeconds, textModels, defaultTextModel, onApply, onClose }: CanvasBeefPromptEditorProps) {
  const [draft, setDraft] = useState(text);
  const [size, setSize] = useState(defaultEditorSize);
  const [optimizing, setOptimizing] = useState(false);
  const drag = useRef<{ x: number; y: number; width: number; height: number } | null>(null);
  const area = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { area.current?.focus(); }, []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && !optimizing) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, optimizing]);

  const startResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, ...size };
  };
  const moveResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    const start = drag.current;
    if (!start) return;
    setSize(clampSize({ width: start.width + (event.clientX - start.x) * 2, height: start.height + (event.clientY - start.y) }));
  };
  const nudge = useCallback((event: ReactKeyboardEvent<HTMLDivElement>) => {
    const step = { ArrowRight: [NUDGE, 0], ArrowLeft: [-NUDGE, 0], ArrowDown: [0, NUDGE], ArrowUp: [0, -NUDGE] }[event.key];
    if (!step) return;
    event.preventDefault();
    setSize(current => clampSize({ width: current.width + step[0], height: current.height + step[1] }));
  }, []);

  return (
    <div className="canvas-beef-backdrop" role="presentation" onPointerDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="canvas-beef-editor" role="dialog" aria-modal="true" aria-label={t('放大编辑提示词')} style={{ width: size.width }}>
        <header>
          <strong><Maximize2 size={14} aria-hidden="true" /> {t('放大编辑提示词')}</strong>
          <span>{t('{0} 字', [draft.length])}</span>
          <button type="button" onClick={onClose} aria-label={t('关闭')}><X size={15} /></button>
        </header>
        <textarea
          ref={area} value={draft} onChange={event => setDraft(event.target.value)} style={{ height: size.height }}
          aria-label={t('提示词')} spellCheck={false}
        />
        <footer>
          <button type="button" onClick={() => setOptimizing(true)} disabled={!draft.trim()}>
            <Sparkles size={14} /> {t('优化')}
          </button>
          <span className="canvas-beef-spacer" />
          <button type="button" onClick={onClose}>{t('取消')}</button>
          <button type="button" className="is-primary" onClick={() => { onApply(draft); onClose(); }} disabled={draft === text}>{t('完成')}</button>
        </footer>
        <div
          className="canvas-beef-editor__resize" role="slider" tabIndex={0} aria-label={t('调整编辑框大小')}
          aria-valuetext={`${size.width} × ${size.height}`}
          onPointerDown={startResize} onPointerMove={moveResize} onPointerUp={() => { drag.current = null; }} onKeyDown={nudge}
        />
      </div>
      {optimizing && (
        <CanvasBeefPromptOptimizer
          taskId={taskId} prompt={draft} medium={medium} targetModel={targetModel} references={references} imageReferences={imageReferences}
          durationSeconds={durationSeconds} textModels={textModels} defaultTextModel={defaultTextModel}
          onAdopt={adopted => { setDraft(adopted); setOptimizing(false); area.current?.focus(); }}
          onClose={() => setOptimizing(false)}
        />
      )}
    </div>
  );
}
