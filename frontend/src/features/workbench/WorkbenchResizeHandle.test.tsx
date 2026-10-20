// @vitest-environment jsdom
import { createRef } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { WorkbenchResizeHandle } from './WorkbenchResizeHandle';
import {
  clampWorkbenchSidebarWidth,
  WORKBENCH_SIDEBAR_DEFAULT_WIDTH,
  WORKBENCH_SIDEBAR_MIN_WIDTH,
  workbenchSidebarMaximum,
} from './workbenchSizing';


describe('WorkbenchResizeHandle', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('keeps the main work area usable when the container narrows', () => {
    expect(workbenchSidebarMaximum(1_000)).toBe(440);
    expect(clampWorkbenchSidebarWidth(700, 1_000)).toBe(440);
    expect(clampWorkbenchSidebarWidth(200, 1_000)).toBe(WORKBENCH_SIDEBAR_MIN_WIDTH);
  });

  it('supports keyboard resizing and a default-width reset', () => {
    const containerRef = createRef<HTMLElement>();
    const sidebarRef = createRef<HTMLElement>();
    const onResize = vi.fn();

    render(
      <div>
        <main ref={containerRef} />
        <aside ref={sidebarRef} />
        <WorkbenchResizeHandle
          containerRef={containerRef}
          sidebarRef={sidebarRef}
          sidebarWidth={400}
          onResize={onResize}
        />
      </div>,
    );
    vi.spyOn(containerRef.current as HTMLElement, 'getBoundingClientRect').mockReturnValue({
      width: 1200,
    } as DOMRect);

    const handle = screen.getByRole('separator', { name: '调整作品区与对话区宽度' });
    fireEvent.keyDown(handle, { key: 'ArrowLeft' });
    fireEvent.keyDown(handle, { key: 'ArrowRight', shiftKey: true });
    fireEvent.keyDown(handle, { key: 'Home' });
    fireEvent.doubleClick(handle);

    expect(onResize).toHaveBeenNthCalledWith(1, 416);
    expect(onResize).toHaveBeenNthCalledWith(2, 350);
    expect(onResize).toHaveBeenNthCalledWith(3, WORKBENCH_SIDEBAR_MIN_WIDTH);
    expect(onResize).toHaveBeenNthCalledWith(4, WORKBENCH_SIDEBAR_DEFAULT_WIDTH);
  });

  it('resizes from the measured sidebar width during a pointer drag', () => {
    const containerRef = createRef<HTMLElement>();
    const sidebarRef = createRef<HTMLElement>();
    const onResize = vi.fn();

    render(
      <div>
        <main ref={containerRef} />
        <aside ref={sidebarRef} />
        <WorkbenchResizeHandle
          containerRef={containerRef}
          sidebarRef={sidebarRef}
          sidebarWidth={null}
          onResize={onResize}
        />
      </div>,
    );
    vi.spyOn(containerRef.current as HTMLElement, 'getBoundingClientRect').mockReturnValue({ width: 1_200 } as DOMRect);
    vi.spyOn(sidebarRef.current as HTMLElement, 'getBoundingClientRect').mockReturnValue({ width: 400 } as DOMRect);

    const handle = screen.getByRole('separator', { name: '调整作品区与对话区宽度' });
    const setPointerCapture = vi.fn();
    const releasePointerCapture = vi.fn();
    Object.assign(handle, {
      setPointerCapture,
      hasPointerCapture: () => true,
      releasePointerCapture,
    });

    fireEvent.pointerDown(handle, { button: 0, clientX: 1_000, pointerId: 7 });
    fireEvent.pointerMove(handle, { clientX: 900, pointerId: 7 });
    fireEvent.pointerUp(handle, { pointerId: 7 });

    expect(onResize).toHaveBeenCalledWith(500);
    expect(setPointerCapture).toHaveBeenCalledWith(7);
    expect(releasePointerCapture).toHaveBeenCalledWith(7);
    expect(document.body.classList.contains('is-resizing-workbench')).toBe(false);
  });

  it('reports the measured width and currently available maximum', () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function measuredRect(this: HTMLElement) {
      if (this.classList.contains('test-container')) return { width: 1_000 } as DOMRect;
      if (this.classList.contains('test-sidebar')) return { width: 440 } as DOMRect;
      return { width: 0 } as DOMRect;
    });
    const containerRef = createRef<HTMLElement>();
    const sidebarRef = createRef<HTMLElement>();

    render(
      <div>
        <main ref={containerRef} className="test-container" />
        <aside ref={sidebarRef} className="test-sidebar" />
        <WorkbenchResizeHandle
          containerRef={containerRef}
          sidebarRef={sidebarRef}
          sidebarWidth={700}
          onResize={vi.fn()}
        />
      </div>,
    );

    const handle = screen.getByRole('separator', { name: '调整作品区与对话区宽度' });
    expect(handle.getAttribute('aria-valuenow')).toBe('440');
    expect(handle.getAttribute('aria-valuemax')).toBe('440');
  });
});
