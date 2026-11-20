import { parseAspect } from '../spatial/floorPlanGeometry';
import {
  NO_BACKDROP,
  type ActionClip, type CameraCut, type FollowClip, type ActorKey, type ActorOverride, type CameraKey, type GroundPoint, type ShotTimeline, type StageActor, type StageBackdrop,
  type StageCamera, type StageContact, type StageCrowd, type StageLandmark, type StageOperation, type StagePlan, type StagePose, type StageShot,
} from '../spatial/spatialTypes';
import { bakeContacts, contactOperation } from './lib/contacts';
import { effectOperation, effectsOf, removeEffect, setEffect } from './lib/effects';
import { crowdMembersOf, nextCrowdId } from './lib/crowdLayout';
import { timelineOf } from './lib/sampling';
import { crowdOf, normalizeYaw, rotateAbout, round2, verticalFov } from './lib/stageMath';

// The desk shows an edit before the server confirms it, and takes it back with the inverse
// operations. Both are derived here from the same semantic operations the PATCH carries, so the
// preview, the request and the undo entry can never describe three different edits.

const ACTOR_FIELDS = ['position', 'yaw_deg', 'posture', 'height_m'] as const;
const LANDMARK_FIELDS = ['position', 'size', 'yaw_deg', 'shape', 'color', 'kind', 'elevation_m'] as const;
const CROWD_FIELDS = ['center', 'yaw_deg', 'spacing'] as const;
const BACKDROP_FIELDS = ['kind', 'color', 'url', 'yaw_deg', 'opacity'] as const;
const FIGURE_FIELDS = ['figure', 'body_type', 'color'] as const;
const FIGURE_DEFAULTS: Record<string, unknown> = { figure: 'standin', body_type: 'standard', color: '' };

/** Mirrors the backend's set_pose: nothing to hold — no preset, no angles, no clip — takes the pose off. */
function poseOf(op: StageOperation): StagePose | null {
  const joints = (op.joints && typeof op.joints === 'object' ? op.joints : {}) as Record<string, number>;
  const preset = String(op.preset || '');
  const clip = String(op.clip || '');
  if (!preset && !clip && !Object.keys(joints).length) return null;
  return { preset, joints, clip, clip_phase: Number(op.clip_phase) || 0 };
}

export function poseOperation(name: string, shotId: number | undefined, pose: StagePose | null | undefined): StageOperation {
  return {
    op: 'set_pose', name, ...(shotId === undefined ? {} : { shot_id: shotId }),
    preset: pose?.preset || '', joints: pose?.joints || {}, clip: pose?.clip || '', clip_phase: pose?.clip_phase ?? 0,
  };
}

function mapWhere<T>(items: T[], match: (item: T) => boolean, change: (item: T) => T): T[] {
  return items.map(item => (match(item) ? change(item) : item));
}

function pick<T extends object>(keys: readonly string[], from: Record<string, unknown>): Partial<T> {
  const result: Record<string, unknown> = {};
  keys.forEach(key => { if (key in from) result[key] = from[key]; });
  return result as Partial<T>;
}

/** An override without its pose: where someone stands in a shot, not how they hold themselves. */
function stagingOf(override: ActorOverride): Omit<ActorOverride, 'pose'> {
  const staging = { ...override };
  delete staging.pose;
  return staging;
}

function shotOf(plan: StagePlan, shotId: unknown): StageShot | undefined {
  return plan.shots.find(shot => shot.shot_id === Number(shotId));
}

/** A plan stored before the desk had backdrops reads as one without a backdrop. */
export function backdropOf(plan: StagePlan | undefined): StageBackdrop {
  return { ...NO_BACKDROP, ...(plan?.backdrop || {}) };
}

// Mirrors backend crowds.moved: a rigid move plus a re-spacing about the centre, so a member
// someone nudged by hand keeps its nudge.
function transformCrowd(plan: StagePlan, op: StageOperation): StagePlan {
  const before = crowdOf(plan, String(op.crowd_id || ''));
  if (!before) return plan;
  const after: StageCrowd = { ...before, ...pick<StageCrowd>(CROWD_FIELDS, op) };
  const stretch = before.spacing > 0 ? after.spacing / before.spacing : 1;
  const turn = after.yaw_deg - before.yaw_deg;
  return {
    ...plan,
    crowds: plan.crowds?.map(crowd => (crowd.id === before.id ? after : crowd)),
    actors: mapWhere(plan.actors, actor => actor.crowd_id === before.id, actor => {
      const scaled: GroundPoint = [before.center[0] + (actor.position[0] - before.center[0]) * stretch, before.center[1] + (actor.position[1] - before.center[1]) * stretch];
      const turned = rotateAbout(scaled, before.center, turn);
      return {
        ...actor,
        position: [round2(turned[0] + after.center[0] - before.center[0]), round2(turned[1] + after.center[1] - before.center[1])],
        yaw_deg: normalizeYaw(actor.yaw_deg + turn),
      };
    }),
  };
}

function withTimeline(plan: StagePlan, shotId: unknown, timeline: ShotTimeline | null): StagePlan {
  const timelines = { ...(plan.timelines || {}) };
  if (timeline) timelines[String(Number(shotId))] = timeline;
  else delete timelines[String(Number(shotId))];
  return { ...plan, timelines };
}

function candidatePrefix(shotId: number): string {
  return `alt-${String(shotId).padStart(2, '0')}-`;
}

/** Whether add_camera in operations.py will take this id for the shot: its own candidate prefix and a number. */
function isCandidateIdOf(id: string, shotId: number): boolean {
  const prefix = candidatePrefix(shotId);
  return id.startsWith(prefix) && /^\d{2,4}$/.test(id.slice(prefix.length));
}

/** A lens the planner made keeps its cam- id after it stops filming; add_camera in operations.py takes one back while it is free. */
function isFormerFilmingId(id: string): boolean {
  return /^cam-\d{2,76}$/.test(id);
}

/** The id add_camera in operations.py would give the shot's next candidate: one past the highest number in use. */
function nextCandidateId(plan: StagePlan, shotId: number): string {
  const prefix = candidatePrefix(shotId);
  const numbers = plan.cameras.filter(camera => camera.id.startsWith(prefix))
    .map(camera => camera.id.slice(prefix.length).split('-', 1)[0]).filter(tail => /^\d+$/.test(tail)).map(Number);
  return `${prefix}${String(Math.max(0, ...numbers) + 1).padStart(2, '0')}`;
}

// Mirrors the backend's add_camera for a lens that names its own id, which is how an undone removal
// comes back: a copy of the lens that films, standing still, then placed. Drawn at once, it keeps
// the cuts through it on the desk, so an edit made before the answer is built on all of them. A new
// candidate is numbered by the server and waits for its answer.
function addCamera(plan: StagePlan, op: StageOperation): StagePlan {
  const shot = shotOf(plan, op.shot_id);
  const filming = plan.cameras.find(camera => camera.id === shot?.camera_id);
  const id = String(op.camera_id ?? '');
  if (!shot || !filming || plan.cameras.some(camera => camera.id === id)) return plan;
  if (!isCandidateIdOf(id, shot.shot_id) && !isFormerFilmingId(id)) return plan;
  const lens: StageCamera = { ...filming, id, label: String(op.label || filming.label), move: { kind: 'static' } };
  return applyLocal({
    ...plan,
    cameras: [...plan.cameras, lens],
    shots: mapWhere(plan.shots, item => item === shot, item => ({ ...item, alt_camera_ids: [...(item.alt_camera_ids || []), id] })),
  }, { ...op, op: 'move_camera', camera_id: id });
}

// Mirrors the backend's set_timeline: a field that is sent replaces the stored one whole, a field
// that is not sent stays, and an actor track with no keys is not a track.
function setTimeline(plan: StagePlan, op: StageOperation): StagePlan {
  if (!shotOf(plan, op.shot_id)) return plan;
  const next: ShotTimeline = { ...timelineOf(plan, Number(op.shot_id)) };
  if ('duration_s' in op) next.duration_s = Number(op.duration_s);
  if ('fps' in op) next.fps = Number(op.fps) as ShotTimeline['fps'];
  if ('camera' in op) next.camera = (op.camera as CameraKey[]).map(key => ({ ...key, lens_mm: key.lens_mm ?? 50, easing: key.easing ?? 'linear' }));
  if ('actors' in op) {
    next.actors = Object.fromEntries(Object.entries(op.actors as Record<string, ActorKey[]>)
      .filter(([, keys]) => keys.length).map(([name, keys]) => [name, keys.map(key => ({ ...key, easing: key.easing ?? 'linear' }))]));
  }
  if ('clips' in op) next.clips = Object.fromEntries(Object.entries(op.clips as Record<string, ActionClip[]>).filter(([, clips]) => clips.length));
  if ('follow' in op) next.follow = op.follow as FollowClip[];
  // A cut can only be drawn through a lens the desk holds; the server refuses any other.
  if ('cuts' in op) next.cuts = (op.cuts as CameraCut[]).filter(cut => plan.cameras.some(camera => camera.id === cut.camera_id));
  return withTimeline(plan, op.shot_id, next);
}

function nextContactId(contacts: StageContact[]): string {
  const numbers = contacts.map(contact => /^contact-(\d+)$/.exec(contact.id)?.[1]).filter(Boolean).map(Number);
  return `contact-${String(Math.max(0, ...numbers) + 1).padStart(2, '0')}`;
}

/**
 * Mirrors backend contacts.without_shots: the contacts on `target` taken out of `shotIds` (empty: out
 * of every shot). A whole-scene contact that loses some shots keeps the scene's other shots as a
 * list; one left with no shot is gone.
 */
function withoutShots(plan: StagePlan, target: string, shotIds: number[]): StageContact[] {
  const all = plan.shots.map(shot => shot.shot_id);
  return (plan.contacts || []).flatMap(item => {
    if (item.target !== target) return [item];
    if (!shotIds.length) return [];
    const covered = item.shot_ids.length ? item.shot_ids : all;
    const remaining = covered.filter(id => !shotIds.includes(id));
    if (remaining.length === covered.length) return [item];
    return remaining.length ? [{ ...item, shot_ids: remaining }] : [];
  });
}

function shotIdsOf(op: StageOperation): number[] {
  return Array.isArray(op.shot_ids) ? [...new Set((op.shot_ids as unknown[]).map(Number).filter(Number.isFinite))] : [];
}

// Mirrors the backend's set_contact: every other contact on the target loses the new one's shots,
// then the new one is added, as a person's own. Names the server would refuse are its to refuse.
function setContact(plan: StagePlan, op: StageOperation): StagePlan {
  const kind = String(op.kind || '') as StageContact['kind'];
  const target = String(op.target || '');
  if (!['hold', 'sit', 'rest'].includes(kind) || !plan.landmarks.some(item => item.name === target)) return plan;
  const shotIds = shotIdsOf(op);
  const hand = String(op.hand || '');
  const contact: StageContact = {
    id: nextContactId(plan.contacts || []), kind, target,
    actor: kind === 'rest' ? '' : String(op.actor || ''),
    support: kind === 'rest' ? String(op.support || '') : '',
    hand: kind === 'hold' && (hand === 'left' || hand === 'right' || hand === 'both') ? hand : '',
    shot_ids: shotIds, source: 'manual',
  };
  return { ...plan, contacts: [...withoutShots(plan, target, shotIds), contact] };
}

// Mirrors the backend's remove_contact: every contact on the target, or that shot taken out of them.
function removeContact(plan: StagePlan, op: StageOperation): StagePlan {
  const target = String(op.target || '');
  if (!plan.contacts?.some(item => item.target === target)) return plan;
  const shotIds = op.shot_id === undefined || op.shot_id === null ? [] : [Number(op.shot_id)];
  return { ...plan, contacts: withoutShots(plan, target, shotIds) };
}

/** What the plan looks like once `op` lands. Operations only the server can resolve leave it unchanged. */
export function applyLocal(plan: StagePlan, op: StageOperation): StagePlan {
  switch (op.op) {
    case 'move_actor':
      return {
        ...plan,
        actors: mapWhere(plan.actors, actor => actor.name === op.name, actor => ({
          ...actor, ...pick<StageActor>(ACTOR_FIELDS, op),
        })),
      };
    case 'move_landmark':
    case 'transform_landmark':
      return {
        ...plan,
        landmarks: mapWhere(plan.landmarks, item => item.name === op.name, item => ({ ...item, ...pick<StageLandmark>(LANDMARK_FIELDS, op) })),
      };
    case 'add_landmark': {
      if (plan.landmarks.some(item => item.name === op.name)) return plan;
      const landmark: StageLandmark = {
        id: `pending-${String(op.name)}`, name: String(op.name), kind: (op.kind as StageLandmark['kind']) || 'prop',
        position: (op.position as GroundPoint) || [0, -1.5], size: (op.size as StageLandmark['size']) || [0.5, 0.5, 0.5],
        yaw_deg: Number(op.yaw_deg) || 0, shape: (op.shape as StageLandmark['shape']) || 'box', color: String(op.color || ''),
        kit: String(op.kit || ''), parts: (op.fitted_parts as StageLandmark['parts']) || [],
      };
      return { ...plan, landmarks: [...plan.landmarks, landmark] };
    }
    case 'bind_landmark_model':
      return { ...plan, landmarks: mapWhere(plan.landmarks, item => item.name === op.name, item => ({ ...item, element_id: String(op.element_id || '') })) };
    case 'set_backdrop':
      return { ...plan, backdrop: { ...backdropOf(plan), ...pick<StageBackdrop>(BACKDROP_FIELDS, op) } };
    case 'remove_landmark': {
      const removed = { ...plan, landmarks: plan.landmarks.filter(item => item.name !== op.name) };
      // A contact cannot name a piece that is gone.
      if (!plan.contacts?.some(item => item.target === op.name || item.support === op.name)) return removed;
      return { ...removed, contacts: plan.contacts.filter(item => item.target !== op.name && item.support !== op.name) };
    }
    case 'set_contact':
      return setContact(plan, op);
    case 'remove_contact':
      return removeContact(plan, op);
    case 'set_effect':
      return setEffect(plan, op);
    case 'remove_effect':
      return removeEffect(plan, op);
    case 'add_crowd': {
      // Drawn at once from the same generator the server uses; its answer replaces this either way.
      const crowds = plan.crowds || [];
      const rows = Number(op.rows) || 0;
      const columns = Number(op.columns) || 0;
      if (rows < 1 || columns < 1 || rows * columns > 150 || crowds.some(crowd => crowd.label === op.label)) return plan;
      const crowd: StageCrowd = {
        id: nextCrowdId(crowds), label: String(op.label), rows, columns, spacing: Number(op.spacing) || 1,
        center: (op.center as GroundPoint) || [0, -3], yaw_deg: Number(op.yaw_deg) || 0,
        body_type: String(op.body_type || 'standard'), seed: Number(op.seed) || 0,
      };
      return { ...plan, crowds: [...crowds, crowd], actors: [...plan.actors, ...crowdMembersOf(crowd)] };
    }
    case 'transform_crowd':
      return transformCrowd(plan, op);
    case 'remove_crowd':
      return { ...plan, crowds: plan.crowds?.filter(crowd => crowd.id !== op.crowd_id), actors: plan.actors.filter(actor => actor.crowd_id !== op.crowd_id) };
    case 'move_camera':
      return {
        ...plan,
        cameras: mapWhere(plan.cameras, camera => camera.id === op.camera_id, camera => {
          const next: StageCamera = { ...camera, ...pick<StageCamera>(['position', 'target'], op) };
          if ('lens_mm' in op) next.lens_mm = Number(op.lens_mm);
          if ('sensor_mm' in op) next.sensor_mm = Number(op.sensor_mm);
          if ('lens_mm' in op || 'sensor_mm' in op) next.fov_deg = round2(verticalFov(next.lens_mm, parseAspect(camera.aspect), next.sensor_mm));
          return next;
        }),
      };
    case 'add_camera':
      return addCamera(plan, op);
    case 'remove_camera': {
      const removed: StagePlan = {
        ...plan,
        cameras: plan.cameras.filter(camera => camera.id !== op.camera_id),
        shots: plan.shots.map(shot => ({ ...shot, alt_camera_ids: (shot.alt_camera_ids || []).filter(id => id !== op.camera_id) })),
      };
      // The server drops every cut through the lens that is gone; the shot shows its own lens there.
      const cutting = Object.entries(plan.timelines || {}).filter(([, timeline]) => timeline.cuts?.some(cut => cut.camera_id === op.camera_id));
      return cutting.reduce((next, [shotId, timeline]) => (
        withTimeline(next, shotId, { ...timeline, cuts: timeline.cuts?.filter(cut => cut.camera_id !== op.camera_id) })
      ), removed);
    }
    case 'use_camera': {
      const filming = shotOf(plan, op.shot_id);
      const stored = plan.timelines?.[String(Number(op.shot_id))];
      // Camera keys are world poses along the old lens's path; the server drops them too.
      const cleared = filming && filming.camera_id !== String(op.camera_id) && stored?.camera.length
        ? withTimeline(plan, op.shot_id, { ...stored, camera: [] }) : plan;
      return {
        ...cleared,
        shots: mapWhere(plan.shots, shot => shot.shot_id === Number(op.shot_id), shot => {
          const wanted = String(op.camera_id);
          if (wanted === shot.camera_id) return shot;
          // The lens that was filming takes the promoted one's place among the candidates.
          return { ...shot, camera_id: wanted, alt_camera_ids: (shot.alt_camera_ids || []).map(id => (id === wanted ? shot.camera_id : id)) };
        }),
      };
    }
    case 'set_timeline':
      return setTimeline(plan, op);
    case 'clear_timeline':
      return plan.timelines?.[String(Number(op.shot_id))] ? withTimeline(plan, op.shot_id, null) : plan;
    case 'set_figure':
      return {
        ...plan,
        actors: mapWhere(plan.actors, actor => (op.crowd_id ? actor.crowd_id === op.crowd_id : actor.name === op.name), actor => ({
          ...actor, ...pick<StageActor>(FIGURE_FIELDS, op),
        })),
        // The server records a whole array's body type on the array itself, so a member added later matches.
        crowds: op.crowd_id && 'body_type' in op
          ? plan.crowds?.map(crowd => (crowd.id === op.crowd_id ? { ...crowd, body_type: String(op.body_type) } : crowd))
          : plan.crowds,
      };
    case 'set_pose': {
      const pose = poseOf(op);
      if (op.shot_id === undefined || op.shot_id === null) {
        return { ...plan, actors: mapWhere(plan.actors, actor => actor.name === op.name, actor => ({ ...actor, pose })) };
      }
      return {
        ...plan,
        shots: mapWhere(plan.shots, shot => shot.shot_id === Number(op.shot_id), shot => {
          const current = shot.overrides.find(item => item.name === op.name);
          const kept = shot.overrides.filter(item => item.name !== op.name);
          const staging = current ? stagingOf(current) : { name: String(op.name) };
          // An override that says nothing any more is not one.
          const says = pose !== null || Object.entries(staging).some(([key, value]) => key !== 'name' && value !== undefined && value !== null && value !== false && value !== '');
          return { ...shot, overrides: says ? [...kept, { ...staging, ...(pose ? { pose } : {}) }] : kept };
        }),
      };
    }
    case 'set_shot_override':
      return {
        ...plan,
        shots: mapWhere(plan.shots, shot => shot.shot_id === Number(op.shot_id), shot => {
          // The per-shot pose is set_pose's to write; restaging someone does not un-pose them.
          const pose = shot.overrides.find(item => item.name === op.name)?.pose;
          return {
            ...shot,
            overrides: [
              ...shot.overrides.filter(item => item.name !== op.name),
              { ...pick<ActorOverride>(['position', 'yaw_deg', 'posture', 'offstage', 'hold', 'reason'], op), name: String(op.name), ...(pose ? { pose } : {}) },
            ],
          };
        }),
      };
    case 'clear_shot_override':
      return { ...plan, shots: mapWhere(plan.shots, shot => shot.shot_id === Number(op.shot_id), shot => ({ ...shot, overrides: shot.overrides.filter(item => item.name !== op.name) })) };
    default:
      return plan;
  }
}

/**
 * What a batch leaves behind. Like the server, the whole-scene contacts are then baked into the
 * stored marks (a prop held all scene long is stored in the hand) and contacts that name something
 * gone are dropped; a plan with no contacts is untouched.
 */
export function applyAll(plan: StagePlan, operations: StageOperation[]): StagePlan {
  return bakeContacts(operations.reduce(applyLocal, plan));
}

function restoreCamera(camera: StageCamera): StageOperation {
  return { op: 'move_camera', camera_id: camera.id, position: camera.position, target: camera.target, lens_mm: camera.lens_mm };
}

function inverseOfOne(plan: StagePlan, op: StageOperation): StageOperation[] | null {
  switch (op.op) {
    case 'move_actor': {
      const actor = plan.actors.find(item => item.name === op.name);
      if (!actor) return [];
      const restore: StageOperation = { op: 'move_actor', name: actor.name };
      ACTOR_FIELDS.forEach(key => { if (key in op) restore[key] = actor[key]; });
      return [restore];
    }
    case 'move_landmark':
    case 'transform_landmark': {
      const landmark = plan.landmarks.find(item => item.name === op.name);
      if (!landmark) return [];
      const defaults: Record<string, unknown> = { yaw_deg: 0, shape: 'box', color: '' };
      const restore: StageOperation = { op: 'transform_landmark', name: landmark.name };
      LANDMARK_FIELDS.forEach(key => { if (key in op) restore[key] = landmark[key] ?? defaults[key]; });
      return [restore];
    }
    case 'add_landmark':
      return [{ op: 'remove_landmark', name: op.name }];
    case 'bind_landmark_model': {
      const landmark = plan.landmarks.find(item => item.name === op.name);
      return landmark ? [{ op: 'bind_landmark_model', name: landmark.name, element_id: landmark.element_id || '' }] : [];
    }
    case 'remove_landmark': {
      const landmark = plan.landmarks.find(item => item.name === op.name);
      if (!landmark) return [];
      // The piece comes back first, then whatever contact named it.
      const contacts = (plan.contacts || []).filter(item => item.target === landmark.name || item.support === landmark.name);
      return [
        addLandmarkOperation(landmark), ...(landmark.element_id ? [{ op: 'bind_landmark_model', name: landmark.name, element_id: landmark.element_id }] : []),
        ...contacts.map(contactOperation),
      ];
    }
    case 'set_effect':
    case 'remove_effect': {
      // A marker that was there comes back as it was; one this edit made is taken away again.
      const before = effectsOf(plan).find(item => item.id === op.id);
      if (before) return [effectOperation(before)];
      if (op.op === 'remove_effect') return [];
      const made = effectsOf(applyLocal(plan, op)).find(item => !effectsOf(plan).some(old => old.id === item.id));
      return made ? [{ op: 'remove_effect', id: made.id }] : [];
    }
    case 'set_contact':
    case 'remove_contact': {
      // Whatever is on the target afterwards goes, the stored marks a whole-scene contact baked go back,
      // then each contact that was there comes back as it was (the server refuses removing nothing).
      const target = String(op.target || '');
      const before = (plan.contacts || []).filter(item => item.target === target);
      if (op.op === 'remove_contact' && !before.length) return [];
      const after = applyLocal(plan, op);
      return [
        ...(after.contacts?.some(item => item.target === target) ? [{ op: 'remove_contact', target }] : []),
        ...restoreMarks(plan, op, before),
        ...before.map(contactOperation),
      ];
    }
    case 'transform_crowd': {
      const crowd = crowdOf(plan, String(op.crowd_id || ''));
      if (!crowd) return [];
      const restore: StageOperation = { op: 'transform_crowd', crowd_id: crowd.id };
      CROWD_FIELDS.forEach(key => { if (key in op) restore[key] = crowd[key]; });
      return [restore];
    }
    case 'remove_crowd': {
      // Only a recorded array can be rebuilt: the seed is what makes it the same crowd again.
      const crowd = plan.crowds?.find(item => item.id === op.crowd_id);
      if (!crowd) return [];
      return [{
        op: 'add_crowd', label: crowd.label, rows: crowd.rows, columns: crowd.columns, spacing: crowd.spacing,
        center: crowd.center, yaw_deg: crowd.yaw_deg, body_type: crowd.body_type, seed: crowd.seed,
      }];
    }
    case 'move_camera': {
      const camera = plan.cameras.find(item => item.id === op.camera_id);
      if (!camera) return [];
      const restore: StageOperation = { op: 'move_camera', camera_id: camera.id };
      (['position', 'target', 'lens_mm'] as const).forEach(key => { if (key in op) restore[key] = camera[key]; });
      if ('sensor_mm' in op) restore.sensor_mm = camera.sensor_mm ?? 36;
      return [restore];
    }
    case 'frame_shot': {
      const camera = plan.cameras.find(item => item.id === shotOf(plan, op.shot_id)?.camera_id);
      return camera ? [restoreCamera(camera)] : [];
    }
    case 'remove_camera': {
      const camera = plan.cameras.find(item => item.id === op.camera_id);
      const shot = plan.shots.find(item => (item.alt_camera_ids || []).includes(String(op.camera_id)));
      if (!camera || !shot) return [];
      // Every field add_camera takes: a candidate starts as a copy of the filming lens, sensor included.
      const rebuilt: StageOperation = {
        op: 'add_camera', shot_id: shot.shot_id, label: camera.label, position: camera.position, target: camera.target,
        lens_mm: camera.lens_mm, sensor_mm: camera.sensor_mm ?? 36,
      };
      // The cuts through it go with it, and they name the lens by id: it comes back under an id, then they do.
      // Older history entries name it too, so it asks for its own id whenever the server would take it.
      const cuts = plan.timelines?.[String(shot.shot_id)]?.cuts ?? [];
      const cutting = cuts.some(cut => cut.camera_id === camera.id);
      if (isCandidateIdOf(camera.id, shot.shot_id) || isFormerFilmingId(camera.id)) {
        return [{ ...rebuilt, camera_id: camera.id }, ...(cutting ? [{ op: 'set_timeline', shot_id: shot.shot_id, cuts }] : [])];
      }
      // Any other id the server will not hand back. Without cuts the lens takes whatever number the
      // server gives it; with cuts it asks for the next free one here, so they can follow it there.
      if (!cutting) return [rebuilt];
      const id = nextCandidateId(plan, shot.shot_id);
      return [
        { ...rebuilt, camera_id: id },
        { op: 'set_timeline', shot_id: shot.shot_id, cuts: cuts.map(cut => (cut.camera_id === camera.id ? { ...cut, camera_id: id } : cut)) },
      ];
    }
    case 'use_camera': {
      const shot = shotOf(plan, op.shot_id);
      if (!shot) return [];
      const keys = plan.timelines?.[String(shot.shot_id)]?.camera || [];
      return [
        { op: 'use_camera', shot_id: shot.shot_id, camera_id: shot.camera_id },
        ...(keys.length && shot.camera_id !== String(op.camera_id) ? [{ op: 'set_timeline', shot_id: shot.shot_id, camera: keys }] : []),
      ];
    }
    case 'set_timeline': {
      const stored = plan.timelines?.[String(Number(op.shot_id))];
      if (!stored) return shotOf(plan, op.shot_id) ? [{ op: 'clear_timeline', shot_id: op.shot_id }] : [];
      const restore: StageOperation = { op: 'set_timeline', shot_id: op.shot_id };
      (['duration_s', 'fps', 'camera', 'actors'] as const).forEach(key => { if (key in op) restore[key] = stored[key]; });
      if ('clips' in op) restore.clips = stored.clips ?? {};
      if ('follow' in op) restore.follow = stored.follow ?? [];
      if ('cuts' in op) restore.cuts = stored.cuts ?? [];
      return [restore];
    }
    case 'clear_timeline': {
      const stored = plan.timelines?.[String(Number(op.shot_id))];
      return stored ? [{ op: 'set_timeline', shot_id: op.shot_id, ...stored }] : [];
    }
    case 'set_path': {
      // The route rewrites a whole track (and may lengthen the shot, and lay a motion on it): all of that goes back.
      const stored = plan.timelines?.[String(Number(op.shot_id))];
      return stored ? [{ op: 'set_timeline', shot_id: op.shot_id, ...stored }] : [{ op: 'clear_timeline', shot_id: op.shot_id }];
    }
    case 'apply_camera_move': {
      // The keys it writes are the server's to lay out; what was there before is all undo needs.
      const stored = plan.timelines?.[String(Number(op.shot_id))];
      return stored ? [{ op: 'set_timeline', shot_id: op.shot_id, camera: stored.camera }] : [{ op: 'clear_timeline', shot_id: op.shot_id }];
    }
    case 'set_figure': {
      // A crowd is switched as one piece, but its members may have been switched one at a time
      // before that: the inverse is one operation per member, each with that member's own values.
      const crowd = op.crowd_id ? crowdOf(plan, String(op.crowd_id)) : undefined;
      const members = op.crowd_id
        ? plan.actors.filter(item => item.crowd_id === op.crowd_id)
        : plan.actors.filter(item => item.name === op.name);
      const restores = members.map(actor => {
        const restore: StageOperation = { op: 'set_figure', name: actor.name };
        FIGURE_FIELDS.forEach(key => { if (key in op) restore[key] = actor[key] ?? FIGURE_DEFAULTS[key]; });
        return restore;
      });
      // The array's own recorded body type goes back first; the per-member restores then win for the people.
      return crowd && 'body_type' in op
        ? [{ op: 'set_figure', crowd_id: crowd.id, body_type: crowd.body_type }, ...restores]
        : restores;
    }
    case 'set_backdrop': {
      const backdrop = backdropOf(plan);
      const restore: StageOperation = { op: 'set_backdrop' };
      BACKDROP_FIELDS.forEach(key => { if (key in op) restore[key] = backdrop[key]; });
      return [restore];
    }
    case 'set_pose': {
      const shotId = op.shot_id === undefined || op.shot_id === null ? undefined : Number(op.shot_id);
      const previous = shotId === undefined
        ? plan.actors.find(item => item.name === op.name)?.pose
        : shotOf(plan, shotId)?.overrides.find(item => item.name === op.name)?.pose;
      return [poseOperation(String(op.name), shotId, previous)];
    }
    case 'set_shot_override':
    case 'clear_shot_override': {
      const previous = shotOf(plan, op.shot_id)?.overrides.find(item => item.name === op.name);
      if (!previous) return op.op === 'clear_shot_override' ? [] : [{ op: 'clear_shot_override', shot_id: op.shot_id, name: op.name }];
      // The per-shot pose is set_pose's to write: set_shot_override keeps whatever pose is there,
      // so only a cleared override (which took the pose with it) needs the pose put back.
      const restore: StageOperation[] = [{ op: 'set_shot_override', shot_id: op.shot_id, ...stagingOf(previous) }];
      if (previous.pose && op.op === 'clear_shot_override') restore.push({ op: 'set_pose', name: previous.name, shot_id: op.shot_id, ...previous.pose });
      return restore;
    }
    default:
      return null;
  }
}

/**
 * The stored marks a whole-scene contact may have baked, as they are now: the target's place and,
 * for a sit, the sitter's mark and posture. Nothing when no whole-scene contact is involved.
 */
function restoreMarks(plan: StagePlan, op: StageOperation, before: StageContact[]): StageOperation[] {
  const sceneWide = (op.op === 'set_contact' && !shotIdsOf(op).length) || before.some(item => !item.shot_ids.length);
  if (!sceneWide) return [];
  const restores: StageOperation[] = [];
  const landmark = plan.landmarks.find(item => item.name === op.target);
  if (landmark) {
    restores.push({ op: 'transform_landmark', name: landmark.name, position: landmark.position, elevation_m: landmark.elevation_m ?? 0, yaw_deg: landmark.yaw_deg ?? 0 });
  }
  const sitters = new Set([...(op.op === 'set_contact' && op.kind === 'sit' ? [String(op.actor || '')] : []), ...before.filter(item => item.kind === 'sit').map(item => item.actor)]);
  plan.actors.filter(actor => sitters.has(actor.name)).forEach(actor => restores.push({ op: 'move_actor', name: actor.name, position: actor.position, posture: actor.posture }));
  return restores;
}

export function addLandmarkOperation(landmark: StageLandmark, name = landmark.name): StageOperation {
  return {
    op: 'add_landmark', name, kind: landmark.kind, position: landmark.position, size: landmark.size,
    yaw_deg: landmark.yaw_deg ?? 0, shape: landmark.shape ?? 'box', color: landmark.color ?? '',
    // A piece built from parts comes back exactly as it was, not rebuilt from its name.
    ...(landmark.parts?.length ? { kit: landmark.kit ?? '', fitted_parts: landmark.parts } : {}),
  };
}

/**
 * The inverse of a batch, in undo order. Each inverse is read off the plan as it stands just
 * before its own operation, so two edits of one object inside a batch restore the first state.
 */
export function inverseOf(plan: StagePlan, operations: StageOperation[]): StageOperation[] | null {
  const inverses: StageOperation[][] = [];
  let current = plan;
  for (const op of operations) {
    const inverse = inverseOfOne(current, op);
    if (inverse === null) return null;
    inverses.unshift(inverse);
    current = applyLocal(current, op);
  }
  return inverses.flat();
}

/** A set piece in the shape `apply_blockout` takes. */
export function blockoutPiece(item: StageLandmark): Record<string, unknown> {
  return {
    name: item.name, kind: item.kind, shape: item.shape ?? 'box', center: item.position, size: item.size,
    yaw_deg: item.yaw_deg ?? 0, elevation_m: item.elevation_m ?? 0, color: item.color ?? '',
  };
}

/** For operations whose result carries server-made ids: undo whatever appeared between the two plans. */
export function inverseFromDiff(before: StagePlan, after: StagePlan): StageOperation[] {
  const operations: StageOperation[] = [];
  const knownCrowds = new Set(before.actors.map(actor => actor.crowd_id || ''));
  [...new Set(after.actors.map(actor => actor.crowd_id || ''))]
    .filter(id => id && !knownCrowds.has(id))
    .forEach(id => operations.push({ op: 'remove_crowd', crowd_id: id }));
  const knownCameras = new Set(before.cameras.map(camera => camera.id));
  after.cameras.filter(camera => !knownCameras.has(camera.id)).forEach(camera => operations.push({ op: 'remove_camera', camera_id: camera.id }));
  // A blockout is hundreds of pieces and one thing to a person: it goes back as one operation.
  const blockoutOf = (plan: StagePlan) => plan.landmarks.filter(item => item.origin === 'blockout');
  const heldBefore = blockoutOf(before);
  const heldAfter = blockoutOf(after);
  if (heldBefore.length !== heldAfter.length || heldAfter.some(item => !heldBefore.some(old => old.name === item.name))) {
    operations.push(heldBefore.length
      ? { op: 'apply_blockout', replace: true, pieces: heldBefore.map(blockoutPiece) }
      : { op: 'clear_blockout' });
  }
  const knownLandmarks = new Set(before.landmarks.map(item => item.name));
  after.landmarks.filter(item => !knownLandmarks.has(item.name) && item.origin !== 'blockout').forEach(item => operations.push({ op: 'remove_landmark', name: item.name }));
  // A re-framed or re-solved lens goes back to where it was.
  before.cameras.forEach(camera => {
    const now = after.cameras.find(item => item.id === camera.id);
    if (now && (String(now.position) !== String(camera.position) || String(now.target) !== String(camera.target) || now.lens_mm !== camera.lens_mm)) {
      operations.push(restoreCamera(camera));
    }
  });
  return operations;
}

export function overrideFor(shot: StageShot | undefined, name: string): ActorOverride | undefined {
  return shot?.overrides.find(item => item.name === name);
}

/**
 * Moving someone in a shot that re-marks them edits that shot's override: the base mark is not
 * what the viewport is showing, so writing to it would move nothing on screen.
 */
export function actorMoveOperation(shot: StageShot | undefined, name: string, change: { position?: GroundPoint; yaw_deg?: number }): StageOperation {
  const override = overrideFor(shot, name);
  const pinned = override && ((change.position && override.position) || (change.yaw_deg !== undefined && override.yaw_deg != null));
  if (shot && override && pinned) return { op: 'set_shot_override', shot_id: shot.shot_id, ...stagingOf(override), ...change };
  return { op: 'move_actor', name, ...change };
}
