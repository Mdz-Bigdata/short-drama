// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CanvasMinimapCanvas } from './CanvasMinimapCanvas';
import type { CanvasNode } from './canvasTypes';

const node = (id: string, x: number, y: number, width = 100, height = 100, kind: CanvasNode['kind'] = 'note'): CanvasNode => ({
  id, kind, track: 'freezone', x, y, width, height, artifact_id: null, payload: {},
});

function mockContext() {
  const context = {
    calls: [] as Array<[string, unknown[]]>,
    globalAlpha: 1, lineWidth: 1, fillStyle: '', strokeStyle: '',
    clearRect: vi.fn(), drawImage: vi.fn(), setTransform: vi.fn(),
    fillRect: vi.fn((...args: unknown[]) => { context.calls.push([`fill ${context.fillStyle}`, args]); }),
    strokeRect: vi.fn((...args: unknown[]) => { context.calls.push([`stroke ${context.strokeStyle}`, args]); }),
  };
  return context;
}

describe('canvas minimap', () => {
  let contexts: Map<HTMLCanvasElement, ReturnType<typeof mockContext>>;
  let frames: FrameRequestCallback[];

  beforeEach(() => {
    contexts = new Map();
    frames = [];
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(function getContext(this: HTMLCanvasElement) {
      if (!contexts.has(this)) contexts.set(this, mockContext());
      return contexts.get(this) as unknown as CanvasRenderingContext2D;
    } as unknown as typeof HTMLCanvasElement.prototype.getContext);
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => frames.push(callback));
    vi.stubGlobal('cancelAnimationFrame', (handle: number) => { frames[handle - 1] = () => {}; });
    vi.stubGlobal('devicePixelRatio', 3);
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
  const flush = () => act(() => { frames.splice(0).forEach(callback => callback(0)); });
  const visibleCanvas = () => screen.getByRole('img', { name: '小地图' }) as HTMLCanvasElement;
  const layerContext = () => [...contexts.entries()].find(([canvas]) => canvas !== visibleCanvas())![1];

  it('draws node rects into a cached layer, groups as outlines, selected ones in the accent, then the view window', () => {
    // Bounds: nodes span (0,0)-(2000,1000), plus 500 each side = 3000x2000, so 0.08 map px per world unit.
    const nodes = [node('g', 0, 0, 1000, 1000, 'group'), node('a', 0, 0, 1000, 1000), node('b', 1000, 0, 1000, 1000)];
    const onJump = vi.fn();
    const { rerender } = render(
      <CanvasMinimapCanvas nodes={nodes} view={{ x: 0, y: 0, zoom: 1 }} width={800} height={600} selected={new Set(['b'])} onJump={onJump} />,
    );
    expect(contexts.size).toBe(0);
    flush();
    const canvas = visibleCanvas();
    // Device pixel ratio 3 is capped at 2.
    expect(canvas.width).toBe(480);
    expect(canvas.height).toBe(320);
    const layer = layerContext();
    expect(layer.setTransform).toHaveBeenCalledWith(2, 0, 0, 2, 0, 0);
    expect(layer.calls.map(([what]) => what.split(' ')[0])).toEqual(['stroke', 'fill', 'fill']);
    expect(layer.calls[0][1]).toEqual([40.5, 40.5, 80, 80]);
    expect(layer.calls[1][1]).toEqual([40, 40, 80, 80]);
    expect(layer.calls[2][1]).toEqual([120, 40, 80, 80]);
    expect(layer.calls[2][0]).not.toBe(layer.calls[1][0]);

    const shown = contexts.get(canvas)!;
    expect(shown.drawImage).toHaveBeenCalledTimes(1);
    // The 800x600 view at zoom 1 from the world origin.
    expect(shown.strokeRect).toHaveBeenLastCalledWith(40, 40, 64, 48);

    // Moving the view stamps the same layer again instead of redrawing every node.
    const selected = new Set(['b']);
    rerender(<CanvasMinimapCanvas nodes={nodes} view={{ x: 0, y: 0, zoom: 1 }} width={800} height={600} selected={selected} onJump={onJump} />);
    flush();
    const drawnNodes = layer.calls.length;
    rerender(<CanvasMinimapCanvas nodes={nodes} view={{ x: -800, y: -100, zoom: 0.5 }} width={800} height={600} selected={selected} onJump={onJump} />);
    flush();
    expect(layer.calls.length).toBe(drawnNodes);
    expect(shown.drawImage).toHaveBeenCalledTimes(3);
    // World (1600,200) at 0.08 from (-500,-500): the window starts at (168, 56) and is 1600x1200 world wide.
    expect(shown.strokeRect).toHaveBeenLastCalledWith(168, 56, 128, 96);

    // A new selection redraws the layer.
    rerender(<CanvasMinimapCanvas nodes={nodes} view={{ x: -800, y: -100, zoom: 0.5 }} width={800} height={600} selected={new Set(['a'])} onJump={onJump} />);
    flush();
    expect(layer.calls.length).toBe(drawnNodes + 3);
  });

  it('jumps on press and follows a drag, keeping the zoom and centring the point under the pointer', () => {
    const nodes = [node('a', 0, 0, 2000, 1000)];
    const onJump = vi.fn();
    render(<CanvasMinimapCanvas nodes={nodes} view={{ x: 0, y: 0, zoom: 0.5 }} width={800} height={600} onJump={onJump} />);
    const box = visibleCanvas().parentElement!;
    // Shown at twice its drawing size: pointer offsets are scaled back to map pixels.
    box.getBoundingClientRect = () => ({ left: 10, top: 20, width: 480, height: 320, right: 490, bottom: 340, x: 10, y: 20, toJSON: () => ({}) });
    // Map centre (120,80) is world (1000,500): the view puts it at the surface centre (400,300).
    fireEvent.pointerDown(box, { clientX: 10 + 240, clientY: 20 + 160, button: 0, pointerId: 1 });
    expect(onJump).toHaveBeenLastCalledWith({ zoom: 0.5, x: 400 - 1000 * 0.5, y: 300 - 500 * 0.5 });
    // Map (240,80) is world (2500,500).
    fireEvent.pointerMove(box, { clientX: 10 + 480, clientY: 20 + 160, pointerId: 1 });
    expect(onJump).toHaveBeenLastCalledWith({ zoom: 0.5, x: 400 - 2500 * 0.5, y: 300 - 500 * 0.5 });
    fireEvent.pointerUp(box, { pointerId: 1 });
    fireEvent.pointerMove(box, { clientX: 20, clientY: 100, pointerId: 1 });
    expect(onJump).toHaveBeenCalledTimes(2);
    fireEvent.pointerDown(box, { clientX: 20, clientY: 100, button: 2, pointerId: 1 });
    expect(onJump).toHaveBeenCalledTimes(2);
  });

  it('frames an empty canvas around the origin', () => {
    const onJump = vi.fn();
    render(<CanvasMinimapCanvas nodes={[]} view={{ x: 0, y: 0, zoom: 2 }} width={800} height={600} onJump={onJump} />);
    const box = visibleCanvas().parentElement!;
    box.getBoundingClientRect = () => ({ left: 0, top: 0, width: 240, height: 160, right: 240, bottom: 160, x: 0, y: 0, toJSON: () => ({}) });
    // 1000x1000 world in a 240x160 map: 0.16 per unit, centred with 40 px either side; (40,0) is world (-500,-500).
    fireEvent.pointerDown(box, { clientX: 40, clientY: 0, button: 0, pointerId: 1 });
    expect(onJump).toHaveBeenLastCalledWith({ zoom: 2, x: 400 + 1000, y: 300 + 1000 });
  });
});
