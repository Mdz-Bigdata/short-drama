import { useCallback, useEffect, useState } from 'react';

export type CanvasTool = 'select' | 'hand';
const KEY = 'canvas.tool';

function stored(): CanvasTool {
  try {
    return localStorage.getItem(KEY) === 'hand' ? 'hand' : 'select';
  } catch {
    return 'select';
  }
}

/** Whether a key press is meant for a text field rather than the canvas. */
export function typingInto(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  if (!element || typeof element.closest !== 'function') return false;
  return Boolean(element.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"]'));
}

/** The tool a key chooses: V for selecting, H for the hand; anything else none. */
export function toolForKey(event: Pick<KeyboardEvent, 'key' | 'metaKey' | 'ctrlKey' | 'altKey' | 'target'>): CanvasTool | null {
  if (event.metaKey || event.ctrlKey || event.altKey || typingInto(event.target)) return null;
  const key = event.key.toLowerCase();
  return key === 'v' ? 'select' : key === 'h' ? 'hand' : null;
}

/**
 * The canvas's pointer tool. With the hand, a left drag pans and nothing is selected or moved; with select,
 * a left drag selects as before. Space-drag, middle-drag and the trackpad pan with either. Remembered per browser.
 */
export function useCanvasTool(): [CanvasTool, (tool: CanvasTool) => void] {
  const [tool, setToolState] = useState<CanvasTool>(stored);
  const setTool = useCallback((next: CanvasTool) => {
    setToolState(next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // A browser that keeps nothing still switches for this visit.
    }
  }, []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const chosen = toolForKey(event);
      if (chosen) setTool(chosen);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setTool]);
  return [tool, setTool];
}

/** Whether a pointer press should pan rather than select, given the tool and the press. */
export function pressPans(tool: CanvasTool, event: Pick<PointerEvent, 'button'>, spaceHeld = false): boolean {
  return event.button === 1 || (event.button === 0 && (tool === 'hand' || spaceHeld));
}
