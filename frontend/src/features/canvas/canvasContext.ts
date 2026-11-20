import { createContext, useContext } from 'react';

import type { LatestRun, NodePayload, ProjectShot, RunOptions, TableCast, TableShot } from './canvasTypes';

export interface CanvasActions {
  taskId: string;
  options: RunOptions | null;
  shots: ProjectShot[];
  /** Bumped when the director desk closes: what it stored should be read again. */
  deskToken: number;
  patch: (nodeId: string, payload: Partial<NodePayload>, coalesce?: string) => void;
  run: (nodeIds: string[]) => void;
  cancel: (latest: LatestRun) => void;
  upload: (nodeId: string, file: File) => void;
  openDesk: (nodeId: string) => void;
  /** Turn a beat plan into a row of image nodes, each with its beat as the prompt. */
  layOutBeats: (sourceId: string, beats: Array<{ title: string; prompt: string }>) => void;
  /** Turn a shot table into a row of shots: a first frame feeding a video node each, with its length and lines. */
  layOutShots?: (sourceId: string, shots: TableShot[], framePrompts?: string[], cast?: TableCast[]) => void;
}

export const CanvasContext = createContext<CanvasActions | null>(null);

export function useCanvasActions() {
  const actions = useContext(CanvasContext);
  if (!actions) throw new Error('CanvasContext is missing');
  return actions;
}
