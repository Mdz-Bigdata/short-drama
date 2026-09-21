import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type RefObject } from 'react';

import {
  clampWorkbenchSidebarWidth,
  WORKBENCH_SIDEBAR_DEFAULT_WIDTH,
  WORKBENCH_SIDEBAR_MAX_WIDTH,
  WORKBENCH_SIDEBAR_MIN_WIDTH,
  workbenchSidebarMaximum,
} from './workbenchSizing';

interface WorkbenchResizeHandleProps {
  containerRef: RefObject<HTMLElement | null>;
  sidebarRef: RefObject<HTMLElement | null>;
  sidebarWidth: number | null;
  onResize: (width: number) => void;
}

interface DragState {
  pointerId: number;
  startX: number;
  startWidth: number;
}

export function WorkbenchResizeHandle({
  containerRef,
  sidebarRef,
  sidebarWidth,
  onResize,
}: WorkbenchResizeHandleProps) {
  const dragRef = useRef<DragState | null>(null);
  const [measuredWidth, setMeasuredWidth] = useState<number | null>(null);
  const [availableMaximum, setAvailableMaximum] = useState(WORKBENCH_SIDEBAR_MAX_WIDTH);

  useEffect(() => () => {
    document.body.classList.remove('is-resizing-workbench');
  }, []);

  useLayoutEffect(() => {
    const measure = () => {
      const containerWidth = containerRef.current?.getBoundingClientRect().width || window.innerWidth;
      const actualWidth = sidebarRef.current?.getBoundingClientRect().width || sidebarWidth || WORKBENCH_SIDEBAR_DEFAULT_WIDTH;
      setMeasuredWidth(Math.round(actualWidth));
      setAvailableMaximum(Math.round(workbenchSidebarMaximum(containerWidth)));
    };

    measure();
    window.addEventListener('resize', measure);
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    if (containerRef.current) observer?.observe(containerRef.current);
    if (sidebarRef.current) observer?.observe(sidebarRef.current);
    return () => {
      window.removeEventListener('resize', measure);
      observer?.disconnect();
    };
  }, [containerRef, sidebarRef, sidebarWidth]);

  const currentWidth = () => (
    sidebarRef.current?.getBoundingClientRect().width
    || sidebarWidth
    || WORKBENCH_SIDEBAR_DEFAULT_WIDTH
  );

  const clampWidth = (width: number) => {
    const containerWidth = containerRef.current?.getBoundingClientRect().width ?? window.innerWidth;
    return clampWorkbenchSidebarWidth(width, containerWidth);
  };

  const resizeTo = (width: number) => onResize(clampWidth(width));

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: currentWidth(),
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.currentTarget.classList.add('is-dragging');
    document.body.classList.add('is-resizing-workbench');
    event.preventDefault();
  };

  const stopDragging = (event: PointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    dragRef.current = null;
    event.currentTarget.classList.remove('is-dragging');
    document.body.classList.remove('is-resizing-workbench');
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    // The sidebar sits on the right: dragging the divider left makes it wider.
    resizeTo(drag.startWidth + drag.startX - event.clientX);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 50 : 16;
    if (event.key === 'ArrowLeft') {
      resizeTo(currentWidth() + step);
    } else if (event.key === 'ArrowRight') {
      resizeTo(currentWidth() - step);
    } else if (event.key === 'Home') {
      resizeTo(WORKBENCH_SIDEBAR_MIN_WIDTH);
    } else if (event.key === 'End') {
      resizeTo(WORKBENCH_SIDEBAR_MAX_WIDTH);
    } else {
      return;
    }
    event.preventDefault();
  };

  const announcedWidth = measuredWidth ?? Math.round(sidebarWidth ?? WORKBENCH_SIDEBAR_DEFAULT_WIDTH);

  return (
    <div
      className="workbench-resize-handle"
      role="separator"
      tabIndex={0}
      aria-label="调整作品区与对话区宽度"
      aria-controls="workbench-asset-viewer workbench-chat-sidebar"
      aria-orientation="vertical"
      aria-valuemin={WORKBENCH_SIDEBAR_MIN_WIDTH}
      aria-valuemax={availableMaximum}
      aria-valuenow={announcedWidth}
      aria-valuetext={`右侧对话区宽度 ${announcedWidth} 像素`}
      title="左右拖动调整宽度；双击恢复默认"
      onDoubleClick={() => resizeTo(WORKBENCH_SIDEBAR_DEFAULT_WIDTH)}
      onKeyDown={handleKeyDown}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={stopDragging}
      onPointerCancel={stopDragging}
      onLostPointerCapture={event => {
        dragRef.current = null;
        event.currentTarget.classList.remove('is-dragging');
        document.body.classList.remove('is-resizing-workbench');
      }}
    />
  );
}
