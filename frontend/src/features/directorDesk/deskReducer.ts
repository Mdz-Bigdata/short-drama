import type { SpatialPlanResponse, StageOperation, StagePlan } from '../spatial/spatialTypes';
import { applyAll, inverseFromDiff, inverseOf } from './deskOperations';
import { refKey, type DeskLayout, type DeskTool, type GuideSettings, type MeasurePoint, type SelectionRef, type SnapSettings } from './deskTypes';

export type EditKind = 'edit' | 'undo' | 'redo';

export interface PendingEdit {
  id: number;
  kind: EditKind;
  label: string;
  operations: StageOperation[];
  /** `null`: read it off the server's answer. `false`: this edit cannot be undone. */
  inverse: StageOperation[] | null | false;
}

export interface HistoryEntry {
  label: string;
  forward: StageOperation[];
  inverse: StageOperation[];
}

export type SaveState = 'idle' | 'saving' | 'saved' | 'error';

export interface DeskState {
  /** The last plan the server confirmed. */
  response: SpatialPlanResponse | null;
  /** What the desk draws: the confirmed plan with every unconfirmed edit on top. */
  plan: StagePlan | null;
  loadError: string;
  pending: PendingEdit[];
  undo: HistoryEntry[];
  redo: HistoryEntry[];
  selection: SelectionRef[];
  tool: DeskTool;
  layout: DeskLayout;
  snap: SnapSettings;
  guides: GuideSettings;
  shotId: number | null;
  /** The lens the camera view looks through; '' follows the shot's filming camera. */
  lensCameraId: string;
  hidden: string[];
  locked: string[];
  measure: MeasurePoint[];
  saveState: SaveState;
  notice: string;
  /** A 422: the server's own sentence, shown where the value was typed. */
  inspectorError: string;
  /** Non-empty while generation holds the stage: the reason, as the server put it. */
  readOnly: string;
  /** Bumped when someone else's revision won: the session reads the plan again. */
  reloadToken: number;
}

export type DeskAction =
  | { type: 'loaded'; response: SpatialPlanResponse }
  | { type: 'loadFailed'; message: string }
  | { type: 'select'; ref: SelectionRef; additive?: boolean }
  | { type: 'clearSelection' }
  | { type: 'setTool'; tool: DeskTool }
  | { type: 'setLayout'; layout: DeskLayout }
  | { type: 'setSnap'; snap: Partial<SnapSettings> }
  | { type: 'setGuides'; guides: Partial<GuideSettings> }
  | { type: 'setShot'; shotId: number }
  | { type: 'setLensCamera'; cameraId: string }
  | { type: 'toggleHidden'; key: string }
  | { type: 'toggleLocked'; key: string }
  | { type: 'measure'; point: MeasurePoint }
  | { type: 'clearMeasure' }
  | { type: 'notice'; message: string }
  | { type: 'edit'; id: number; kind: EditKind; label: string; operations: StageOperation[]; irreversible?: boolean }
  | { type: 'applied'; response: SpatialPlanResponse; editIds: number[] }
  | { type: 'rejected'; editIds: number[]; status: number; message: string };

const HISTORY_LIMIT = 100;

export const initialDeskState: DeskState = {
  response: null, plan: null, loadError: '', pending: [], undo: [], redo: [], selection: [],
  tool: 'select', layout: 'split',
  snap: { grid: true, gridSize: 0.25, faces: true, angle: true },
  guides: { aspect: '', frame: true, thirds: true, safe: false, cross: false },
  shotId: null, lensCameraId: '', hidden: [], locked: [], measure: [],
  saveState: 'idle', notice: '', inspectorError: '', readOnly: '', reloadToken: 0,
};

/** A 409 is either someone else's newer revision or a running generation holding the stage. */
export function isRevisionConflict(message: string): boolean {
  return /刷新|其他页面|revision/i.test(message);
}

function keepShot(plan: StagePlan, shotId: number | null): number | null {
  return shotId !== null && plan.shots.some(shot => shot.shot_id === shotId) ? shotId : plan.shots[0]?.shot_id ?? null;
}

function exists(plan: StagePlan, ref: SelectionRef): boolean {
  switch (ref.kind) {
    case 'actor': return plan.actors.some(actor => actor.name === ref.name);
    case 'landmark': return plan.landmarks.some(item => item.name === ref.name);
    case 'crowd': return plan.actors.some(actor => actor.crowd_id === ref.id);
    default: return plan.cameras.some(camera => camera.id === ref.id);
  }
}

function withPlan(state: DeskState, plan: StagePlan): DeskState {
  const lensCameraId = plan.cameras.some(camera => camera.id === state.lensCameraId) ? state.lensCameraId : '';
  return { ...state, plan, lensCameraId, shotId: keepShot(plan, state.shotId), selection: state.selection.filter(ref => exists(plan, ref)) };
}

function toggle(list: string[], key: string): string[] {
  return list.includes(key) ? list.filter(item => item !== key) : [...list, key];
}

function push(stack: HistoryEntry[], entry: HistoryEntry): HistoryEntry[] {
  return [...stack, entry].slice(-HISTORY_LIMIT);
}

export function deskReducer(state: DeskState, action: DeskAction): DeskState {
  switch (action.type) {
    case 'loaded':
      // A fresh read replaces everything unconfirmed; the history spoke about a plan that is gone.
      return withPlan({
        ...state, response: action.response, loadError: '', pending: [], undo: [], redo: [],
        saveState: 'idle', inspectorError: '', readOnly: '',
      }, action.response.plan);
    case 'loadFailed':
      return { ...state, loadError: action.message };
    case 'select': {
      if (!action.additive) return { ...state, selection: [action.ref], inspectorError: '' };
      const key = refKey(action.ref);
      const already = state.selection.some(ref => refKey(ref) === key);
      return {
        ...state, inspectorError: '',
        selection: already ? state.selection.filter(ref => refKey(ref) !== key) : [...state.selection, action.ref],
      };
    }
    case 'clearSelection':
      return state.selection.length ? { ...state, selection: [], inspectorError: '' } : state;
    case 'setTool':
      return { ...state, tool: action.tool, measure: action.tool === 'measure' ? state.measure : [] };
    case 'setLayout':
      return { ...state, layout: action.layout };
    case 'setSnap':
      return { ...state, snap: { ...state.snap, ...action.snap } };
    case 'setGuides':
      return { ...state, guides: { ...state.guides, ...action.guides } };
    case 'setShot':
      return { ...state, shotId: action.shotId, lensCameraId: '' };
    case 'setLensCamera':
      return { ...state, lensCameraId: action.cameraId };
    case 'toggleHidden':
      return { ...state, hidden: toggle(state.hidden, action.key) };
    case 'toggleLocked':
      return { ...state, locked: toggle(state.locked, action.key) };
    case 'measure':
      // A third click starts a new measurement.
      return { ...state, measure: state.measure.length >= 2 ? [action.point] : [...state.measure, action.point] };
    case 'clearMeasure':
      return { ...state, measure: [] };
    case 'notice':
      return { ...state, notice: action.message };
    case 'edit': {
      if (!state.plan || state.readOnly) return state;
      const edit: PendingEdit = {
        id: action.id, kind: action.kind, label: action.label, operations: action.operations,
        inverse: action.irreversible ? false : inverseOf(state.plan, action.operations),
      };
      return {
        ...withPlan(state, applyAll(state.plan, action.operations)),
        pending: [...state.pending, edit],
        // The entry being replayed leaves its stack now, so a second Ctrl+Z reaches the one below.
        undo: action.kind === 'undo' ? state.undo.slice(0, -1) : state.undo,
        redo: action.kind === 'redo' ? state.redo.slice(0, -1) : state.redo,
        saveState: 'saving', notice: '', inspectorError: '',
      };
    }
    case 'applied': {
      const before = state.response?.plan;
      const landed = state.pending.filter(edit => action.editIds.includes(edit.id));
      const waiting = state.pending.filter(edit => !action.editIds.includes(edit.id));
      let { undo, redo } = state;
      landed.forEach(edit => {
        if (edit.inverse === false) { undo = []; redo = []; return; }
        const inverse = edit.inverse ?? (before ? inverseFromDiff(before, action.response.plan) : []);
        if (!inverse.length) return;
        const entry: HistoryEntry = { label: edit.label, forward: edit.operations, inverse };
        if (edit.kind === 'undo') redo = push(redo, { label: edit.label, forward: inverse, inverse: edit.operations });
        else {
          undo = push(undo, entry);
          if (edit.kind === 'edit') redo = [];
        }
      });
      return {
        ...withPlan(state, applyAll(action.response.plan, waiting.flatMap(edit => edit.operations))),
        response: action.response, pending: waiting, undo, redo,
        saveState: waiting.length ? 'saving' : 'saved',
      };
    }
    case 'rejected': {
      const base = state.response ? withPlan(state, state.response.plan) : state;
      const dropped = { ...base, pending: state.pending.filter(edit => !action.editIds.includes(edit.id)), saveState: 'error' as const };
      if (action.status === 422) return { ...dropped, inspectorError: action.message };
      if (action.status === 409 && !isRevisionConflict(action.message)) return { ...dropped, readOnly: action.message, notice: '' };
      if (action.status === 409) return { ...dropped, notice: `${action.message}（已重新读取最新方案，刚才的修改没有保存）`, reloadToken: state.reloadToken + 1 };
      return { ...dropped, notice: action.message };
    }
    default:
      return state;
  }
}
