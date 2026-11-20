// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { clickTarget, doubleClickTarget } from './canvasOpenGestures';
import type { CanvasNode } from './canvasTypes';
import { boundShot, useCanvasOpen, type BoundShot } from './useCanvasOpen';

function node(id: string, kind: CanvasNode['kind'], payload: CanvasNode['payload'] = {}): CanvasNode {
  return { id, kind, track: 'freezone', x: 0, y: 0, width: 260, height: 200, artifact_id: null, payload };
}

afterEach(cleanup);

const NODES = [
  node('pic', 'media', { label: '定妆照' }),
  node('clip', 'video_gen', { label: '第一镜', binding: { sceneId: 'S01', shotId: 2 } }),
  node('loose', 'note', { text: '备忘' }),
  node('desk', 'previz', { sceneId: 'S03' }),
];

function Harness({ onOpenShot, panning = false }: { onOpenShot?: (shot: BoundShot) => void; panning?: boolean }) {
  const opening = useCanvasOpen({ nodes: NODES, onOpenShot });
  return (
    <div data-testid="viewport" {...opening.gestures}>
      <div className={`cn-surface${panning ? ' is-panning' : ''}`}>
        <div data-node-id="pic"><header data-testid="pic-head">定妆照</header><img className="cn-media" src="http://x/a.png" alt="" data-testid="pic-img" /></div>
        <div data-node-id="clip">
          <header data-testid="clip-head">第一镜</header>
          <video className="cn-media" src="http://x/a.mp4" data-testid="clip-video" />
          <textarea data-testid="clip-prompt" />
        </div>
        <div data-node-id="loose"><p data-testid="loose-body">备忘</p></div>
        <div data-node-id="desk"><p data-testid="desk-body">预演</p></div>
      </div>
      {opening.dialog}
    </div>
  );
}

function click(element: Element, at = { x: 10, y: 10 }, down: MouseEventInit = {}) {
  fireEvent.pointerDown(element, { button: 0, clientX: 10, clientY: 10, ...down });
  fireEvent.click(element, { clientX: at.x, clientY: at.y, detail: 1 });
}

function doubleClick(element: Element) {
  fireEvent.pointerDown(element, { button: 0, clientX: 10, clientY: 10 });
  fireEvent.doubleClick(element, { clientX: 10, clientY: 10, detail: 2 });
}

describe('what a press on a card opens', () => {
  it('names the picture for a click and the clip or the card for a double click', () => {
    render(<Harness />);
    expect(clickTarget(screen.getByTestId('pic-img'))).toMatchObject({ kind: 'image', nodeId: 'pic', url: 'http://x/a.png' });
    expect(clickTarget(screen.getByTestId('clip-video'))).toBeNull();
    expect(clickTarget(screen.getByTestId('pic-head'))).toBeNull();
    expect(doubleClickTarget(screen.getByTestId('clip-video'))).toMatchObject({ kind: 'video', nodeId: 'clip', url: 'http://x/a.mp4' });
    expect(doubleClickTarget(screen.getByTestId('clip-head'))).toEqual({ kind: 'node', nodeId: 'clip' });
    expect(doubleClickTarget(screen.getByTestId('clip-prompt'))).toBeNull();
    expect(doubleClickTarget(screen.getByTestId('pic-img'))).toBeNull();
    expect(doubleClickTarget(screen.getByTestId('viewport'))).toBeNull();
  });

  it('reads the shot from a write-back binding or from a previz card', () => {
    expect(boundShot(NODES[1])).toEqual({ sceneId: 'S01', shotId: 2 });
    expect(boundShot(NODES[3])).toEqual({ sceneId: 'S03', shotId: null });
    expect(boundShot(NODES[2])).toBeNull();
  });
});

describe('opening from the canvas', () => {
  it('shows a picture large on a click and puts it away on Escape', () => {
    render(<Harness />);
    click(screen.getByTestId('pic-img'));
    const dialog = screen.getByRole('dialog', { name: '放大查看：定妆照' });
    expect(dialog.querySelector('img')?.getAttribute('src')).toBe('http://x/a.png');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('closes on the backdrop and on the close button, not on the picture', () => {
    render(<Harness />);
    click(screen.getByTestId('pic-img'));
    fireEvent.click(screen.getByRole('dialog').querySelector('img')!);
    expect(screen.getByRole('dialog')).toBeTruthy();
    fireEvent.click(screen.getByRole('dialog'));
    expect(screen.queryByRole('dialog')).toBeNull();
    click(screen.getByTestId('pic-img'));
    fireEvent.click(screen.getByRole('button', { name: '关闭预览' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('opens nothing after a drag, with a modifier held, or while panning', () => {
    const { rerender } = render(<Harness />);
    click(screen.getByTestId('pic-img'), { x: 60, y: 10 });
    expect(screen.queryByRole('dialog')).toBeNull();
    click(screen.getByTestId('pic-img'), { x: 10, y: 10 }, { shiftKey: true });
    expect(screen.queryByRole('dialog')).toBeNull();
    rerender(<Harness panning />);
    click(screen.getByTestId('pic-img'));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('plays a clip in a player on a double click and stops the one on the card', () => {
    render(<Harness />);
    const video = screen.getByTestId('clip-video') as HTMLVideoElement;
    video.pause = vi.fn();
    doubleClick(video);
    const dialog = screen.getByRole('dialog', { name: '播放：第一镜' });
    expect(dialog.querySelector('video')?.getAttribute('src')).toBe('http://x/a.mp4');
    expect(video.pause).toHaveBeenCalled();
  });

  it('opens the shot a card is tied to on a double click, and nothing for a card on its own', () => {
    const onOpenShot = vi.fn();
    render(<Harness onOpenShot={onOpenShot} />);
    doubleClick(screen.getByTestId('loose-body'));
    doubleClick(screen.getByTestId('clip-prompt'));
    expect(onOpenShot).not.toHaveBeenCalled();
    doubleClick(screen.getByTestId('clip-head'));
    expect(onOpenShot).toHaveBeenLastCalledWith({ sceneId: 'S01', shotId: 2 });
    doubleClick(screen.getByTestId('desk-body'));
    expect(onOpenShot).toHaveBeenLastCalledWith({ sceneId: 'S03', shotId: null });
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
