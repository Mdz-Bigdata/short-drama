import { useState } from 'react';
import { createPortal } from 'react-dom';
import { Maximize2 } from 'lucide-react';

import { t } from '../../i18n';
import { CanvasBeefPromptEditor } from './CanvasBeefPromptEditor';
import { useCanvasActions } from './canvasContext';
import { referencesFor, useCanvasBeefDoc } from './canvasBeefDocContext';
import type { CanvasNode } from './canvasTypes';

/** The composer dock's way into the large prompt editor and optimizer, for picture and clip nodes. */
export function CanvasBeefDockEditorButton({ node }: { node: CanvasNode }) {
  const { taskId, options, patch } = useCanvasActions();
  const doc = useCanvasBeefDoc();
  const [open, setOpen] = useState(false);
  if (node.kind !== 'image_gen' && node.kind !== 'video_gen') return null;
  const medium = node.kind === 'video_gen' ? 'video' : 'image';
  const references = referencesFor(node, doc);
  const target = String(node.payload.params?.model || (medium === 'video' ? options?.models.video : options?.models.image) || '');
  // Opened over the whole workspace (and inside it, so its light or dark theme applies), not inside the dock.
  const host = typeof document === 'undefined' ? null : document.querySelector('.canvas-workspace') ?? document.body;
  return (
    <>
      <button type="button" className="cn-button is-quiet" onClick={() => setOpen(true)} aria-label={t('放大编辑提示词')} title={t('放大编辑提示词')}>
        <Maximize2 aria-hidden="true" />
      </button>
      {open && host && createPortal(
        <CanvasBeefPromptEditor
          nodeId={node.id} taskId={taskId} medium={medium} text={String(node.payload.prompt ?? '')} targetModel={target}
          references={references.texts} imageReferences={references.images}
          durationSeconds={medium === 'video' ? Number(node.payload.params?.durationSeconds ?? 5) || undefined : undefined}
          textModels={options?.enabled?.text} defaultTextModel={options?.models?.text}
          // The dock's own way of writing the prompt: one undo step, and the quote is worked out again after the save.
          onApply={text => patch(node.id, { prompt: text }, `prompt:${node.id}`)}
          onClose={() => setOpen(false)}
        />,
        host,
      )}
    </>
  );
}
