// @vitest-environment jsdom
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { CanvasPresenceLayer, CanvasPresencePeers } from './CanvasPresenceLayer';
import type { SurfaceHandle } from './CanvasSurface';
import type { Viewport } from './canvasTypes';
import type { PresencePeer } from './useCanvasPresence';

afterEach(cleanup);

function fakeSurface(start: Viewport) {
  const listeners = new Set<(view: Viewport, size: { width: number; height: number }) => void>();
  const handle = {
    subscribe: (listener: (view: Viewport, size: { width: number; height: number }) => void) => {
      listeners.add(listener);
      listener(start, { width: 800, height: 600 });
      return () => { listeners.delete(listener); };
    },
  } as unknown as SurfaceHandle;
  return { ref: { current: handle }, move: (view: Viewport) => listeners.forEach(listener => listener(view, { width: 800, height: 600 })), listeners };
}

const PEERS: PresencePeer[] = [
  { client_id: 'w2', label: '另一个窗口 · Firefox', color: '#ff0000' },
  { client_id: 'w3', label: '另一个窗口 · Safari', color: '#0000ff' },
];

describe('CanvasPresenceLayer', () => {
  it('draws cursors, drag outlines and selection rings in each window\'s colour, and keeps their screen size', () => {
    const surface = fakeSurface({ x: 10, y: 20, zoom: 2 });
    const { container, unmount } = render(
      <CanvasPresenceLayer
        surface={surface.ref}
        peers={PEERS}
        cursors={new Map([['w2', { x: 100, y: 50 }], ['gone', { x: 0, y: 0 }]])}
        drags={new Map([['w3', [{ id: 'a', x: 30, y: 40, width: 200, height: 120 }]]])}
        selections={new Map([['w2', ['b', 'missing']]])}
        nodes={[{ id: 'b', x: 300, y: 400, width: 220, height: 160 }]}
      />,
    );
    const layer = container.querySelector<HTMLElement>('.cpl-layer')!;
    expect(layer.getAttribute('aria-hidden')).toBe('true');
    expect(container.querySelector<HTMLElement>('.cpl-world')!.style.transform).toBe('translate(10px, 20px) scale(2)');
    expect(layer.style.getPropertyValue('--cpl-inv')).toBe('0.5');

    // A cursor of a window that has left the list is not drawn.
    const cursors = container.querySelectorAll<HTMLElement>('.cpl-cursor');
    expect(cursors).toHaveLength(1);
    expect(cursors[0].dataset.peer).toBe('w2');
    expect(cursors[0].style.transform).toBe('translate(100px, 50px)');
    expect(cursors[0].style.getPropertyValue('--cpl-color')).toBe('#ff0000');
    expect(cursors[0].textContent).toBe('另一个窗口 · Firefox');

    const outline = container.querySelector<HTMLElement>('.cpl-drag')!;
    expect(outline.style.getPropertyValue('--cpl-color')).toBe('#0000ff');
    expect(outline.style.transform).toBe('translate(30px, 40px)');
    expect(outline.style.width).toBe('200px');

    const rings = container.querySelectorAll<HTMLElement>('.cpl-ring');
    expect(rings).toHaveLength(1);
    expect(rings[0].style.transform).toBe('translate(300px, 400px)');
    expect(rings[0].style.height).toBe('160px');
    expect(rings[0].style.getPropertyValue('--cpl-color')).toBe('#ff0000');

    // Pan and zoom reach it without a render.
    act(() => surface.move({ x: -5, y: 0, zoom: 0.25 }));
    expect(container.querySelector<HTMLElement>('.cpl-world')!.style.transform).toBe('translate(-5px, 0px) scale(0.25)');
    expect(layer.style.getPropertyValue('--cpl-inv')).toBe('4');
    unmount();
    expect(surface.listeners.size).toBe(0);
  });

  it('counts the other windows in the toolbar, one dot each', () => {
    const { container, rerender } = render(<CanvasPresencePeers peers={PEERS} />);
    expect(screen.getByText('同时打开：2 个窗口')).toBeTruthy();
    const dots = container.querySelectorAll<HTMLElement>('.cpl-peers__dot');
    expect([...dots].map(dot => dot.style.getPropertyValue('--cpl-color'))).toEqual(['#ff0000', '#0000ff']);
    rerender(<CanvasPresencePeers peers={[]} />);
    expect(container.querySelector('.cpl-peers')).toBeNull();
  });
});
