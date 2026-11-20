// Contact between a body and a thing, as the stage keeps it: a prop in a hand, someone on a seat,
// a piece resting on another. Mirrors the contract the backend resolver follows
// (backend/app/core/spatial_stage, "contacts"): one resolver, applied after the shot's overrides,
// the playback sample and the drag in progress, before anything is drawn.
//
// Nothing here touches three.js: a jointed figure's real hand comes in through `HandLocator`
// (see handBones.ts), so the spatial dialog and the desk's own chunk stay free of it.

import {
  actorsInShot, type ContactHand, type GroundPoint, type SpacePoint, type StageActor, type StageContact,
  type StageLandmark, type StageOperation, type StagePlan, type StagePosture, type StageShot,
} from '../../spatial/spatialTypes';
import { posePosture } from './poses';

/** Hand height as a share of standing height, by posture. */
export const HAND_HEIGHT: Record<StagePosture, number> = {
  stand: 0.47, walk: 0.47, run: 0.47, fight: 0.47, lean: 0.47, bow: 0.47,
  sit: 0.55, crouch: 0.5, kneel: 0.5, lie: 0.12,
};
/** One hand: this far to the actor's side and this far forward. Both hands: on the centre line, further forward. */
export const HAND_SIDE_M = 0.22;
export const HAND_FORWARD_M = 0.18;
export const BOTH_HANDS_FORWARD_M = 0.25;
/** A resting piece keeps this far inside the edge of what it rests on. */
export const REST_MARGIN_M = 0.02;
/** A seat is something whose top is this high. */
export const SEAT_TOP_M: [number, number] = [0.3, 0.7];

export type Hand = Exclude<ContactHand, ''>;

/**
 * Where a hand holds something, and — when the figure's own hand can be read — which way the fist
 * points what it holds (`along`: in at the little finger, out past the thumb) and which way its
 * knuckles face (`forward`). Both are unit vectors on the stage.
 */
export interface HandGrip {
  point: SpacePoint;
  along?: SpacePoint;
  forward?: SpacePoint;
}

/** A point on the stage (x, height, z) for one hand of `actor`, or a whole grip, or `null` to fall back on the formula. */
export type HandLocator = (actor: StageActor, hand: Hand) => SpacePoint | HandGrip | null;

/** A held thing this tall and this slender is a sword, a staff, a torch: it lies along the fist rather than standing in the palm. */
export const LONG_PROP_MIN_M = 0.4;
export const LONG_PROP_SLENDER = 3;
/** The fist closes this far up from the end of a long thing, or this share of its length if that is less. */
export const HILT_M = 0.12;
export const HILT_SHARE = 0.15;

/** Whether a held `prop` is carried along the fist (tilted with the hand) rather than upright in it. */
export function carriedAlongFist(prop: Pick<StageLandmark, 'size'>): boolean {
  return prop.size[2] >= LONG_PROP_MIN_M && prop.size[2] >= LONG_PROP_SLENDER * Math.max(prop.size[0], prop.size[1]);
}

export interface ResolveOptions {
  hand?: HandLocator;
  /** Writing stored marks, as the server does: a sit sets the posture and leaves the pose alone. */
  bake?: boolean;
}

export const HAND_LABELS: Record<Hand, string> = { right: '右手', left: '左手', both: '双手' };

export function handOf(contact: Pick<StageContact, 'hand'>): Hand {
  return contact.hand === 'left' || contact.hand === 'both' ? contact.hand : 'right';
}

/** Whether `contact` holds in shot `shotId`: a whole-scene contact holds everywhere. */
export function contactApplies(contact: Pick<StageContact, 'shot_ids'>, shotId: number | null | undefined): boolean {
  if (!contact.shot_ids?.length) return true;
  return shotId !== null && shotId !== undefined && contact.shot_ids.includes(shotId);
}

const NO_CONTACTS: StageContact[] = [];

/** Every contact in force in shot `shotId`, in the order the plan lists them. */
export function contactsAt(plan: Pick<StagePlan, 'contacts'>, shotId: number | null | undefined): StageContact[] {
  const all = plan.contacts;
  if (!all?.length) return NO_CONTACTS;
  return all.filter(contact => contactApplies(contact, shotId));
}

/** The contact on `target` in force in this shot (there is at most one). */
export function contactOn(plan: Pick<StagePlan, 'contacts'>, shotId: number | null | undefined, target: string): StageContact | undefined {
  return plan.contacts?.find(contact => contact.target === target && contactApplies(contact, shotId));
}

/** The seat `actor` sits on in this shot. */
export function seatOf(plan: Pick<StagePlan, 'contacts'>, shotId: number | null | undefined, actor: string): StageContact | undefined {
  return plan.contacts?.find(contact => contact.kind === 'sit' && contact.actor === actor && contactApplies(contact, shotId));
}

/** What the outliner and the notices say about a contact: 「在林夏右手里」「放在书案上」「坐在扶手椅上」. */
export function contactPhrase(contact: StageContact): string {
  if (contact.kind === 'hold') return `在${contact.actor}${HAND_LABELS[handOf(contact)]}里`;
  if (contact.kind === 'rest') return `放在${contact.support}上`;
  return `坐在${contact.target}上`;
}

/**
 * Why the operator may not drag `ref` on its own in this shot, or ''. A held prop goes where the
 * hand goes and a seated actor stays on the seat; a lock does not change that, the contact does.
 */
export function dragRefusal(plan: Pick<StagePlan, 'contacts'>, shotId: number | null | undefined, ref: { kind: string; name?: string } | undefined, mode: string | null): string {
  if (!ref?.name || (mode !== 'translate' && mode !== 'rotate')) return '';
  if (ref.kind === 'landmark') {
    const contact = contactOn(plan, shotId, ref.name);
    return contact?.kind === 'hold' ? `「${ref.name}」${contactPhrase(contact)}：先解除接触再单独移动` : '';
  }
  if (ref.kind === 'actor' && mode === 'translate') {
    const seat = seatOf(plan, shotId, ref.name);
    return seat ? `「${ref.name}」${contactPhrase(seat)}：先解除接触再单独移动` : '';
  }
  return '';
}

/** Names of the pieces a hand holds in this shot: a drag of the person carries them, they are not moved on their own. */
export function heldTargets(plan: Pick<StagePlan, 'contacts'>, shotId: number | null | undefined): Set<string> {
  return new Set(contactsAt(plan, shotId).filter(contact => contact.kind === 'hold').map(contact => contact.target));
}

function round3(value: number): number {
  return Math.round(value * 1000) / 1000 + 0;
}

/** The posture a hand height is read for: the pose preset's first, as the backend's projection reads it. */
export function contactPosture(actor: Pick<StageActor, 'posture' | 'pose'>): StagePosture {
  return (posePosture(actor.pose?.preset) || actor.posture) as StagePosture;
}

/** The contract's hand: off the actor's mark by a facing-relative offset, at a share of standing height. */
export function formulaHandPoint(actor: Pick<StageActor, 'position' | 'yaw_deg' | 'height_m' | 'posture' | 'pose'>, hand: Hand): SpacePoint {
  const yaw = (actor.yaw_deg * Math.PI) / 180;
  // forward = (sin yaw, cos yaw), right = (-forward.z, forward.x): geometry.py's conventions.
  const fx = Math.sin(yaw);
  const fz = Math.cos(yaw);
  const side = hand === 'both' ? 0 : hand === 'left' ? -HAND_SIDE_M : HAND_SIDE_M;
  const forward = hand === 'both' ? BOTH_HANDS_FORWARD_M : HAND_FORWARD_M;
  return [
    actor.position[0] - fz * side + fx * forward,
    actor.height_m * (HAND_HEIGHT[contactPosture(actor)] ?? HAND_HEIGHT.stand),
    actor.position[1] + fx * side + fz * forward,
  ];
}

/** `point` brought inside the footprint of `piece` (yaw aware), `margin` in from every edge. */
export function clampToFootprint(point: GroundPoint, piece: Pick<StageLandmark, 'position' | 'size' | 'yaw_deg'>, margin = REST_MARGIN_M): GroundPoint {
  const yaw = ((piece.yaw_deg ?? 0) * Math.PI) / 180;
  const cos = Math.cos(yaw);
  const sin = Math.sin(yaw);
  const dx = point[0] - piece.position[0];
  const dz = point[1] - piece.position[1];
  // The piece's own axes, as geometry.local_point reads them.
  const x = dx * cos - dz * sin;
  const z = dx * sin + dz * cos;
  const halfX = Math.max(0, piece.size[0] / 2 - margin);
  const halfZ = Math.max(0, piece.size[1] / 2 - margin);
  const cx = Math.min(halfX, Math.max(-halfX, x));
  const cz = Math.min(halfZ, Math.max(-halfZ, z));
  if (cx === x && cz === z) return point;
  return [piece.position[0] + cx * cos + cz * sin, piece.position[1] - cx * sin + cz * cos];
}

/** The top of a piece above the floor. */
export function topOf(piece: Pick<StageLandmark, 'elevation_m' | 'size'>): number {
  return (piece.elevation_m ?? 0) + piece.size[2];
}

export function isSeat(piece: Pick<StageLandmark, 'elevation_m' | 'size'>): boolean {
  const top = topOf(piece);
  return top >= SEAT_TOP_M[0] - 1e-6 && top <= SEAT_TOP_M[1] + 1e-6;
}

/** A sit keeps a pose that is already a sit, or one somebody shaped by hand; a named other posture gives way to sitting. */
function seatedPose(actor: StageActor): StageActor['pose'] {
  const pose = actor.pose;
  const named = posePosture(pose?.preset);
  return pose && named && named !== 'sit' ? { preset: 'sit', joints: {} } : pose;
}

/**
 * The plan as its contacts in shot `shotId` make it: seated actors on their seats, held props in
 * the hand, resting pieces on what they rest on. Sits go first (a seated actor's hand is lower; a
 * seat that rests on something is found where it rests), then holds, then rests, settled until
 * nothing moves (a thing on a tray on a table) — the order backend contacts.py keeps. With no
 * contact in force the plan comes back as the very same object, and so does everything a contact
 * leaves where it was.
 */
export function resolveContacts(plan: StagePlan, shotId: number | null | undefined, options: ResolveOptions = {}): StagePlan {
  const contacts = contactsAt(plan, shotId);
  if (!contacts.length) return plan;
  const shot = plan.shots.find(item => item.shot_id === shotId);
  let actors = plan.actors;
  let shots = plan.shots;
  let landmarks = plan.landmarks;
  const landmark = (name: string) => landmarks.find(item => item.name === name);
  const setLandmark = (name: string, change: Partial<StageLandmark>) => {
    landmarks = landmarks.map(item => (item.name === name ? { ...item, ...change } : item));
  };
  const cast = () => actorsInShot({ ...plan, actors, shots }, shots.find(item => item.shot_id === shotId));
  const rests = contacts.filter(contact => contact.kind === 'rest');
  const settle = () => {
    for (let pass = 0; pass < Math.max(1, rests.length); pass += 1) {
      const before = landmarks;
      rests.forEach(contact => {
        const piece = landmark(contact.target);
        const support = landmark(contact.support);
        if (!piece || !support || piece === support) return;
        const elevation = round3(topOf(support));
        const clamped = clampToFootprint(piece.position, support);
        const position: GroundPoint = clamped === piece.position ? piece.position : [round3(clamped[0]), round3(clamped[1])];
        if (position === piece.position && (piece.elevation_m ?? 0) === elevation) return;
        setLandmark(piece.name, { position, elevation_m: elevation });
      });
      if (landmarks === before) return;
    }
  };

  const seatedPoseOf = (actor: StageActor) => (options.bake ? actor.pose : seatedPose(actor));
  if (rests.length && contacts.some(contact => contact.kind === 'sit')) settle();
  contacts.forEach(contact => {
    if (contact.kind !== 'sit') return;
    const seat = landmark(contact.target);
    const actor = cast().find(item => item.name === contact.actor);
    if (!seat || !actor) return;
    const pose = seatedPoseOf(actor);
    if (actor.position[0] === seat.position[0] && actor.position[1] === seat.position[1] && actor.posture === 'sit' && pose === actor.pose) return;
    const position: GroundPoint = [seat.position[0], seat.position[1]];
    actors = actors.map(item => (item.name === actor.name ? { ...item, position, posture: 'sit', pose: item.pose ? seatedPoseOf(item) : item.pose } : item));
    if (shot) {
      shots = shots.map(item => (item.shot_id !== shot.shot_id ? item : {
        ...item,
        overrides: item.overrides.map(override => (override.name !== actor.name ? override : {
          ...override,
          ...(override.position ? { position } : {}),
          ...(override.posture ? { posture: 'sit' as const } : {}),
          ...(override.pose ? { pose: seatedPoseOf({ ...actor, pose: override.pose }) } : {}),
        })),
      }));
    }
  });

  const people = contacts.some(contact => contact.kind === 'hold') ? cast() : [];
  contacts.forEach(contact => {
    if (contact.kind !== 'hold') return;
    const prop = landmark(contact.target);
    const actor = people.find(item => item.name === contact.actor);
    if (!prop || !actor) return;
    const hand = handOf(contact);
    const found = options.hand?.(actor, hand) ?? formulaHandPoint(actor, hand);
    const grip: HandGrip = Array.isArray(found) ? { point: found } : found;
    const point = grip.point;
    if (grip.along && carriedAlongFist(prop)) {
      // Gripped near its end and pointing where the fist points it: the piece's foot goes a hilt's length behind the hand.
      const hilt = Math.min(HILT_M, prop.size[2] * HILT_SHARE);
      const foot: SpacePoint = [point[0] - grip.along[0] * hilt, point[1] - grip.along[1] * hilt, point[2] - grip.along[2] * hilt];
      setLandmark(prop.name, {
        position: [round3(foot[0]), round3(foot[2])], elevation_m: round3(foot[1]), yaw_deg: actor.yaw_deg,
        tilt: { up: grip.along, forward: grip.forward ?? [Math.sin((actor.yaw_deg * Math.PI) / 180), 0, Math.cos((actor.yaw_deg * Math.PI) / 180)] },
      });
      return;
    }
    const position: GroundPoint = [round3(point[0]), round3(point[2])];
    const elevation = round3(Math.max(0, point[1] - prop.size[2] / 2));
    const yaw = actor.yaw_deg;
    if (prop.position[0] === position[0] && prop.position[1] === position[1] && (prop.elevation_m ?? 0) === elevation && (prop.yaw_deg ?? 0) === yaw) return;
    setLandmark(prop.name, { position, elevation_m: elevation, yaw_deg: yaw });
  });

  settle();

  if (actors === plan.actors && shots === plan.shots && landmarks === plan.landmarks) return plan;
  return { ...plan, actors, shots, landmarks };
}

/**
 * The stored plan as the server keeps it after every edit (backend contacts.settle): contacts that
 * name something gone are dropped, and every whole-scene contact is written into the stored marks
 * with the formula hand. Contacts tied to shots leave the marks alone: that is where things are in
 * the other shots.
 */
export function bakeContacts(plan: StagePlan): StagePlan {
  if (!plan.contacts?.length) return plan;
  const people = new Set(plan.actors.map(actor => actor.name));
  const pieces = new Set(plan.landmarks.map(item => item.name));
  const kept = plan.contacts.filter(contact => pieces.has(contact.target) && (!contact.support || pieces.has(contact.support)) && (!contact.actor || people.has(contact.actor)));
  return resolveContacts(kept.length === plan.contacts.length ? plan : { ...plan, contacts: kept }, null, { bake: true });
}

/** An operation that puts `contact` back as it is. */
export function contactOperation(contact: StageContact): StageOperation {
  return {
    op: 'set_contact', kind: contact.kind, actor: contact.actor, target: contact.target, support: contact.support,
    hand: contact.hand, shot_ids: [...contact.shot_ids],
  };
}

/**
 * Operations that undo every contact that names `name` — as what is held, sat on or rested, or as
 * what something rests on — one per target. Sent ahead of removing or renaming the piece.
 */
export function detachOperations(plan: Pick<StagePlan, 'contacts'>, name: string): StageOperation[] {
  const targets = [...new Set((plan.contacts || []).filter(contact => contact.target === name || contact.support === name).map(contact => contact.target))];
  return targets.map(target => ({ op: 'remove_contact', target }));
}

/** `shot` as a scope for a new contact: this shot alone, or the whole scene. */
export function scopeOf(shot: StageShot | undefined, scene: boolean): number[] {
  return scene || !shot ? [] : [shot.shot_id];
}
