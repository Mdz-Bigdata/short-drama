import { actorsInShot, type SpacePoint, type StagePlan, type StageShot } from '../../spatial/spatialTypes';
import { cameraKeysOf, sampleActor, sampleShot, timelineOf } from './sampling';

// The route something takes through a shot, with the time it is at each point. The stage draws it
// as a moving trail: the part already travelled at the playhead, the part still ahead, arrows that
// say which way it runs, and a pulse that replays the timing while the shot stands still.

export interface TrailKey {
  time: number;
  position: SpacePoint;
  /** A lens key also says where it looks, so a ghost of the camera can be stood on it. */
  target?: SpacePoint;
}

export interface Trail {
  /** The selection key of whoever travels it: `camera:<id>` or `actor:<name>`. */
  key: string;
  kind: 'camera' | 'actor';
  /** The camera id or the actor's name. */
  owner: string;
  /** In time order; the traveller is at `points[i]` at `times[i]` seconds. */
  points: SpacePoint[];
  times: number[];
  keys: TrailKey[];
  durationS: number;
}

export interface TrailArrow {
  position: SpacePoint;
  /** Unit vector along the travel. */
  direction: SpacePoint;
}

/** Evenly spaced samples between keys; the keys themselves are always sampled, so corners stay corners. */
const STEPS = 48;
const SAME_TIME_S = 1e-6;
/** Arrows on a short walk sit this far apart; a long route spreads its arrows out instead of adding more. */
const ARROW_SPACING_M = 1.2;
const MAX_ARROWS = 14;
/** A route shorter than this goes nowhere worth pointing along. */
const MIN_ARROW_ROUTE_M = 0.4;
/** How long the pulse rests at the end of the route before it sets off again. */
export const PULSE_REST_S = 0.8;

function sampleTimes(durationS: number, keyTimes: number[], steps: number): number[] {
  const even = Array.from({ length: steps + 1 }, (_, index) => (durationS * index) / steps);
  const all = [...even, ...keyTimes.filter(time => time >= 0 && time <= durationS)].sort((a, b) => a - b);
  return all.filter((time, index) => index === 0 || time - all[index - 1] > SAME_TIME_S);
}

function distance(a: SpacePoint, b: SpacePoint): number {
  return Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
}

export function trailLength(points: SpacePoint[]): number {
  let total = 0;
  for (let index = 1; index < points.length; index += 1) total += distance(points[index - 1], points[index]);
  return total;
}

/** Every route of the shot: the filming lens when it travels, and each actor whose keys take them somewhere. */
export function shotTrails(plan: StagePlan, shot: StageShot | undefined, steps = STEPS): Trail[] {
  if (!shot) return [];
  const timeline = timelineOf(plan, shot.shot_id);
  const durationS = timeline.duration_s;
  const trails: Trail[] = [];
  const camera = plan.cameras.find(item => item.id === shot.camera_id);
  const cameraKeys = cameraKeysOf(timeline, camera);
  if (camera && (cameraKeys.length >= 2 || timeline.follow?.length)) {
    const times = sampleTimes(durationS, cameraKeys.map(key => key.time), steps);
    trails.push({
      key: `camera:${camera.id}`, kind: 'camera', owner: camera.id, times, durationS,
      // Asked for by id: a cut to another lens does not move this one. The whole lens, not just its keys: a follow clip moves it without any.
      points: times.map(time => sampleShot(plan, shot, time, camera.id).camera?.position ?? camera.position),
      keys: cameraKeys.map(key => ({ time: key.time, position: key.position, target: key.target })),
    });
  }
  const cast = actorsInShot(plan, shot);
  Object.entries(timeline.actors).forEach(([name, keys]) => {
    const placed = keys.filter(key => key.position);
    const actor = cast.find(item => item.name === name);
    if (placed.length < 2 || !actor) return;
    const times = sampleTimes(durationS, placed.map(key => key.time), steps);
    trails.push({
      key: `actor:${name}`, kind: 'actor', owner: name, times, durationS,
      // Authored: where the keys put the figure, without the stride that only moves its limbs.
      points: times.map(time => {
        const at = sampleActor(actor, keys, time, true).position;
        return [at[0], 0, at[1]];
      }),
      keys: placed.map(key => ({ time: key.time, position: [key.position![0], 0, key.position![1]] })),
    });
  });
  return trails;
}

export interface TrailSpot {
  position: SpacePoint;
  /** How many whole legs of `points` are already behind the traveller. */
  legs: number;
}

/** Where the traveller is at `time`, and how much of the route is behind it. */
export function trailSpot(trail: Pick<Trail, 'points' | 'times'>, time: number): TrailSpot {
  const { points, times } = trail;
  if (!points.length) return { position: [0, 0, 0], legs: 0 };
  if (!(time > times[0])) return { position: points[0], legs: 0 };
  const last = points.length - 1;
  if (time >= times[last]) return { position: points[last], legs: last };
  let low = 0;
  let high = last;
  while (high - low > 1) {
    const middle = (low + high) >> 1;
    if (times[middle] <= time) low = middle; else high = middle;
  }
  const span = times[high] - times[low];
  const weight = span > 0 ? (time - times[low]) / span : 0;
  const [a, b] = [points[low], points[high]];
  return { position: [a[0] + (b[0] - a[0]) * weight, a[1] + (b[1] - a[1]) * weight, a[2] + (b[2] - a[2]) * weight], legs: low };
}

/** Arrowheads along the route, evenly spaced by distance, each pointing the way the traveller goes. */
export function trailArrows(points: SpacePoint[], spacingM = ARROW_SPACING_M, max = MAX_ARROWS): TrailArrow[] {
  const total = trailLength(points);
  if (total < MIN_ARROW_ROUTE_M) return [];
  const count = Math.max(1, Math.min(max, Math.floor(total / spacingM)));
  const gap = total / count;
  const arrows: TrailArrow[] = [];
  let walked = 0;
  // The first arrow sits half a gap in, so neither end of the route wears one on top of its key.
  let next = gap / 2;
  for (let index = 1; index < points.length && arrows.length < count; index += 1) {
    const [a, b] = [points[index - 1], points[index]];
    const leg = distance(a, b);
    while (leg > 0 && next <= walked + leg && arrows.length < count) {
      const weight = (next - walked) / leg;
      arrows.push({
        position: [a[0] + (b[0] - a[0]) * weight, a[1] + (b[1] - a[1]) * weight, a[2] + (b[2] - a[2]) * weight],
        direction: [(b[0] - a[0]) / leg, (b[1] - a[1]) / leg, (b[2] - a[2]) / leg],
      });
      next += gap;
    }
    walked += leg;
  }
  return arrows;
}

/**
 * The shot time the pulse shows `elapsedS` seconds after it first set off: it runs the route at the
 * shot's own pace, rests at the end, and sets off again. `null` while it rests.
 */
export function pulseTime(elapsedS: number, durationS: number, restS = PULSE_REST_S): number | null {
  if (!(durationS > 0) || !Number.isFinite(elapsedS)) return null;
  const lap = durationS + restS;
  const within = ((elapsedS % lap) + lap) % lap;
  return within <= durationS ? within : null;
}

/**
 * The keys of a lens route that get a ghost camera: all of them while they are few, otherwise the
 * first, the last and an even spread between, so a hand-drawn route (a key every few steps) still
 * shows where the lens points along the way without burying the route in cameras.
 */
export function ghostKeys(keys: TrailKey[], max = 5): TrailKey[] {
  const aimed = keys.filter(key => key.target);
  if (aimed.length <= max || max < 2) return aimed.slice(0, Math.max(0, max));
  return Array.from({ length: max }, (_, index) => aimed[Math.round((index * (aimed.length - 1)) / (max - 1))]);
}

/** `1.5s`-style stamp for a key on the trail. */
export function keyStamp(time: number): string {
  return `${(Math.round(time * 10) / 10).toFixed(1)}s`;
}
