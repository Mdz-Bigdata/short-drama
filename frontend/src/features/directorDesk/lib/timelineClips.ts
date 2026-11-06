// The block tracks of the timeline: what a figure does (action clips) and whom the lens stays on
// (follow clips). Like the key edits, every change ends in a `set_timeline` carrying the whole list.

import type {
  ActionClip, CameraCut, CameraKey, FollowClip, SpacePoint, StageActor, StageOperation, StagePlan, StageShot, ShotTimeline,
} from '../../spatial/spatialTypes';
import { humanoidClip } from './humanoidClips';
import { sampleShot, timelineOf, timeOfFrame } from './sampling';
import { round2 } from './stageMath';

export interface Block { id: string; start: number; end: number }

/** A block shorter than this cannot be grabbed by either end. */
export const MIN_BLOCK_S = 0.1;
/** A looping motion dropped on the track runs this long until somebody trims it. */
const DEFAULT_LOOP_LENGTH_S = 3;
const DEFAULT_FOLLOW_LENGTH_S = 5;
const DEFAULT_CUT_LENGTH_S = 2;
/** Enough keys that a baked follow reads as the follow it was, within what a track holds. */
const BAKED_KEYS_PER_SECOND = 8;
const MAX_BAKED_KEYS = 120;

export interface FollowPreset {
  id: string;
  label: string;
  offset: SpacePoint;
  aim: number;
  lensMm: number;
  relative?: FollowClip['relative'];
}

export const FOLLOW_PRESETS: FollowPreset[] = [
  { id: 'close-up', label: '面部特写', offset: [0, 0, -0.9], aim: 0.93, lensMm: 85 },
  { id: 'behind', label: '背后近跟', offset: [0.2, 0.1, 1.1], aim: 0.9, lensMm: 50 },
  { id: 'shoulder', label: '过肩跟随', offset: [0.45, 0.05, 1.2], aim: 0.92, lensMm: 50 },
  { id: 'side', label: '侧面跟拍', offset: [2.2, 0, 0], aim: 0.7, lensMm: 35 },
  { id: 'lead', label: '前方引导', offset: [0, 0.1, -2.6], aim: 0.8, lensMm: 35 },
  { id: 'top', label: '俯拍跟随', offset: [0, 5, 0.6], aim: 0.6, lensMm: 28, relative: 'world' },
];

function snap(time: number, fps: number): number {
  return timeOfFrame(Math.round(time * fps), fps);
}

function sorted<T extends Block>(blocks: T[]): T[] {
  return [...blocks].sort((a, b) => a.start - b.start);
}

/** The room a block can slide or stretch in: from the end of the one before it to the start of the one after. */
function roomOf<T extends Block>(blocks: T[], id: string, durationS: number): [number, number] {
  const others = sorted(blocks.filter(block => block.id !== id));
  const held = blocks.find(block => block.id === id);
  if (!held) return [0, durationS];
  const middle = (held.start + held.end) / 2;
  const before = others.filter(block => (block.start + block.end) / 2 <= middle).pop();
  const after = others.find(block => (block.start + block.end) / 2 > middle);
  return [before?.end ?? 0, after?.start ?? durationS];
}

/** The block slid to start at `start`, stopped by its neighbours and the ends of the shot. */
export function moveBlock<T extends Block>(blocks: T[], id: string, start: number, fps: number, durationS: number): T[] {
  const [low, high] = roomOf(blocks, id, durationS);
  return sorted(blocks.map(block => {
    if (block.id !== id) return block;
    const length = block.end - block.start;
    const from = snap(Math.min(high - length, Math.max(low, start)), fps);
    return { ...block, start: from, end: round2Time(from + length) };
  }));
}

function round2Time(time: number): number {
  return Math.round(time * 1000) / 1000;
}

/** One end of the block dragged to `time`; the other end stays put. */
export function trimBlock<T extends Block>(blocks: T[], id: string, edge: 'start' | 'end', time: number, fps: number, durationS: number): T[] {
  const [low, high] = roomOf(blocks, id, durationS);
  return blocks.map(block => {
    if (block.id !== id) return block;
    return edge === 'start'
      ? { ...block, start: snap(Math.min(block.end - MIN_BLOCK_S, Math.max(low, time)), fps) }
      : { ...block, end: snap(Math.max(block.start + MIN_BLOCK_S, Math.min(high, time)), fps) };
  });
}

/** Where a new block of about `length` seconds fits at `at`, shortened to the gap it lands in; `null` when there is none. */
export function placeBlock(blocks: Block[], at: number, length: number, fps: number, durationS: number): { start: number; end: number } | null {
  const inside = blocks.find(block => at >= block.start && at < block.end);
  const from = inside ? inside.end : at;
  const next = sorted(blocks).find(block => block.start >= from);
  const limit = next?.start ?? durationS;
  const end = Math.min(limit, from + length);
  if (end - from < MIN_BLOCK_S) return null;
  return { start: snap(from, fps), end: snap(end, fps) };
}

export function nextBlockId(blocks: Block[], prefix: string): string {
  const taken = new Set(blocks.map(block => block.id));
  for (let number = 1; ; number += 1) {
    const id = `${prefix}-${String(number).padStart(2, '0')}`;
    if (!taken.has(id)) return id;
  }
}

export function actionClipsOf(timeline: ShotTimeline, name: string): ActionClip[] {
  return timeline.clips?.[name] ?? [];
}

export function clipsOperation(shotId: number, timeline: ShotTimeline, name: string, clips: ActionClip[]): StageOperation {
  return { op: 'set_timeline', shot_id: shotId, clips: { ...(timeline.clips ?? {}), [name]: clips } };
}

export function followOperation(shotId: number, follow: FollowClip[]): StageOperation {
  return { op: 'set_timeline', shot_id: shotId, follow };
}

export function cutsOperation(shotId: number, cuts: CameraCut[]): StageOperation {
  return { op: 'set_timeline', shot_id: shotId, cuts };
}

/** A cut to `cameraId` from the playhead, as long as the room there allows up to a few seconds. */
export function addCut(timeline: ShotTimeline, cameraId: string, at: number): CameraCut | null {
  const held = timeline.cuts ?? [];
  const room = placeBlock(held, at, DEFAULT_CUT_LENGTH_S, timeline.fps, timeline.duration_s);
  return room && { id: nextBlockId(held, 'cut'), camera_id: cameraId, ...room };
}

/** A motion dropped at the playhead: a one-off runs once, a loop runs a few seconds. */
export function addAction(timeline: ShotTimeline, name: string, clipId: string, at: number): ActionClip | null {
  const motion = humanoidClip(clipId);
  const held = actionClipsOf(timeline, name);
  const room = placeBlock(held, at, motion.loop ? DEFAULT_LOOP_LENGTH_S : motion.duration, timeline.fps, timeline.duration_s);
  return room && { id: nextBlockId(held, 'clip'), clip: motion.id, ...room };
}

export function addFollow(timeline: ShotTimeline, actor: string, preset: FollowPreset, at: number): FollowClip | null {
  const held = timeline.follow ?? [];
  const room = placeBlock(held, at, DEFAULT_FOLLOW_LENGTH_S, timeline.fps, timeline.duration_s);
  return room && {
    id: nextBlockId(held, 'follow'), actor, ...room, offset: preset.offset, relative: preset.relative ?? 'actor',
    aim: preset.aim, damping_s: 0.3, blend_s: 0, lens_mm: preset.lensMm,
  };
}

/** A motion needs limbs to show: asking for one on a limbless stand-in brings the skinned figure in with it. */
export function figureForAction(actor: StageActor | undefined): StageOperation[] {
  return actor && (actor.figure ?? 'standin') === 'standin' ? [{ op: 'set_figure', name: actor.name, figure: 'humanoid' }] : [];
}

/**
 * The lens's whole travel over the shot written out as ordinary camera keys, follow clips gone:
 * for hand-editing every frame of it, and for Blender and the desk interchange, which read keys only.
 */
export function bakeFollow(plan: StagePlan, shot: StageShot): StageOperation {
  const timeline = timelineOf(plan, shot.shot_id);
  const count = Math.min(MAX_BAKED_KEYS, Math.max(2, Math.ceil(timeline.duration_s * BAKED_KEYS_PER_SECOND) + 1));
  const keys: CameraKey[] = [];
  for (let index = 0; index < count; index += 1) {
    const time = round2Time((timeline.duration_s * index) / (count - 1));
    const lens = sampleShot(plan, shot, Math.min(time, timeline.duration_s - 1e-3)).camera;
    if (lens) keys.push({ time, position: lens.position.map(round2) as SpacePoint, target: lens.target.map(round2) as SpacePoint, lens_mm: Math.round(lens.lens_mm * 10) / 10, easing: 'linear' });
  }
  return { op: 'set_timeline', shot_id: shot.shot_id, camera: keys, follow: [] };
}
