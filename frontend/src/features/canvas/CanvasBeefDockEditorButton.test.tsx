// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CanvasBeefDockEditorButton } from './CanvasBeefDockEditorButton';
import { CanvasBeefDocContext, referencesFor } from './canvasBeefDocContext';
import { CanvasContext, type CanvasActions } from './canvasContext';
import type { CanvasDoc, CanvasNode } from './canvasTypes';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const node = (id: string, kind: CanvasNode['kind'], payload: CanvasNode['payload'] = {}): CanvasNode => ({
  id, kind, track: 'freezone', x: 0, y: 0, width: 100, height: 80, artifact_id: null, payload,
});
const clip = node('v', 'video_gen', { prompt: '追车', params: {} });
const doc: CanvasDoc = {
  nodes: [clip, node('n1', 'note', { text: '林夏：短发，青色斗篷' }), node('i1', 'image_gen'), node('m1', 'media', { medium: 'image' })],
  edges: [
    { id: 'e1', source: 'n1', target: 'v', kind: 'dependency', payload: {} },
    { id: 'e2', source: 'i1', target: 'v', kind: 'reference', payload: {} },
    { id: 'e3', source: 'm1', target: 'v', kind: 'reference', payload: {} },
  ],
};

describe('referencesFor', () => {
  it('takes the text of connected notes and counts connected pictures', () => {
    expect(referencesFor(clip, doc)).toEqual({ texts: ['林夏：短发，青色斗篷'], images: 2 });
    expect(referencesFor(clip, null)).toEqual({ texts: [], images: 0 });
  });
});

describe('CanvasBeefDockEditorButton', () => {
  it('opens the editor and writes back through the dock’s own patch', () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, status: 200, json: async () => ({ modes: [], text_models: [], default_text_model: '' }) } as Response);
    const patch = vi.fn();
    const actions = { taskId: 't1', options: { models: { image: 'seedream', video: 'seedance', audio: '' } }, patch } as unknown as CanvasActions;
    render(
      <div className="canvas-workspace">
        <CanvasContext.Provider value={actions}>
          <CanvasBeefDocContext.Provider value={doc}>
            <CanvasBeefDockEditorButton node={clip} />
          </CanvasBeefDocContext.Provider>
        </CanvasContext.Provider>
      </div>,
    );
    fireEvent.click(screen.getByRole('button', { name: '放大编辑提示词' }));
    const box = screen.getByRole('textbox', { name: '提示词' });
    expect(box.closest('.canvas-workspace')).toBeTruthy();
    fireEvent.change(box, { target: { value: '雨夜追车，车灯划破雨幕' } });
    fireEvent.click(screen.getByRole('button', { name: '完成' }));
    expect(patch).toHaveBeenCalledWith('v', { prompt: '雨夜追车，车灯划破雨幕' }, 'prompt:v');
    expect(screen.queryByRole('dialog', { name: '放大编辑提示词' })).toBeNull();
  });

  it('is not offered for nodes without a picture or clip prompt', () => {
    const actions = { taskId: 't1', options: null, patch: vi.fn() } as unknown as CanvasActions;
    const { container } = render(<CanvasContext.Provider value={actions}><CanvasBeefDockEditorButton node={node('a', 'audio_gen')} /></CanvasContext.Provider>);
    expect(container.innerHTML).toBe('');
  });
});
