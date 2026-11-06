import type { Condition, PlaytestRun, Scalar, StoryChoice, StoryEffect, StoryGraph, StoryRoute, StorySegment, StoryVariable } from './storyTypes';

/** Variables by id. A Map, so a story's own ids can never collide with anything on Object.prototype. */
export type Values = ReadonlyMap<string, Scalar>;

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/** Mismatched types are false for every operator, `ne` included; the backend and exported player say the same. */
export function compare(actual: unknown, op: string, expected: unknown): boolean {
  if (typeof actual === 'boolean' || typeof expected === 'boolean') {
    if (typeof actual !== 'boolean' || typeof expected !== 'boolean') return false;
    return op === 'eq' ? actual === expected : op === 'ne' ? actual !== expected : false;
  }
  if (!isNumber(actual) || !isNumber(expected)) return false;
  switch (op) {
    case 'eq': return actual === expected;
    case 'ne': return actual !== expected;
    case 'gt': return actual > expected;
    case 'gte': return actual >= expected;
    case 'lt': return actual < expected;
    case 'lte': return actual <= expected;
    default: return false;
  }
}

export function evaluate(condition: Condition | null | undefined, values: Values): boolean {
  if (!condition) return true;
  if ('all' in condition) return condition.all.every(item => evaluate(item, values));
  if ('any' in condition) return condition.any.some(item => evaluate(item, values));
  return values.has(condition.var) && compare(values.get(condition.var), condition.op, condition.value);
}

function clamp(value: number, variable: StoryVariable): number {
  let result = value;
  if (variable.min !== null && variable.min !== undefined) result = Math.max(result, variable.min);
  if (variable.max !== null && variable.max !== undefined) result = Math.min(result, variable.max);
  return result;
}

export function initialValues(variables: readonly StoryVariable[]): Map<string, Scalar> {
  const values = new Map<string, Scalar>();
  for (const variable of variables) {
    values.set(variable.id, variable.kind === 'flag' ? variable.initial === true : clamp(Number(variable.initial) || 0, variable));
  }
  return values;
}

export function applyEffects(effects: readonly StoryEffect[], values: Values, variables: readonly StoryVariable[]): Map<string, Scalar> {
  const result = new Map(values);
  for (const effect of effects) {
    const variable = variables.find(item => item.id === effect.var);
    if (!variable) continue;
    if (variable.kind === 'flag') {
      if (effect.op === 'set' && typeof effect.value === 'boolean') result.set(effect.var, effect.value);
    } else if (isNumber(effect.value)) {
      const current = result.get(effect.var);
      const base = effect.op === 'add' && typeof current === 'number' ? current : 0;
      result.set(effect.var, clamp(Math.round((base + effect.value) * 1e6) / 1e6, variable));
    }
  }
  return result;
}

export interface ChoiceOption { choice: StoryChoice; locked: boolean; unconnected: boolean }

export type NextStep =
  | { kind: 'ending'; options: ChoiceOption[] }
  | { kind: 'route'; route: StoryRoute; options: ChoiceOption[] }
  | { kind: 'choices'; options: ChoiceOption[] }
  | { kind: 'stuck'; options: ChoiceOption[] };

/** What follows a segment. Unlike the exported player, an unconnected choice stays visible: the author needs to see it. */
export function nextStep(segment: StorySegment, values: Values, known: (id: string | null) => boolean): NextStep {
  if (segment.kind === 'ending') return { kind: 'ending', options: [] };
  for (const route of segment.routes) {
    if (known(route.target) && evaluate(route.condition, values)) return { kind: 'route', route, options: [] };
  }
  const options: ChoiceOption[] = [];
  for (const choice of segment.choices) {
    const open = evaluate(choice.condition, values);
    if (!open && choice.when_locked === 'hide') continue;
    options.push({ choice, locked: !open, unconnected: !known(choice.target) });
  }
  return { kind: options.some(item => !item.locked && !item.unconnected) ? 'choices' : 'stuck', options };
}

/** A timed-out viewer gets the default, or the first open choice when the default is locked. */
export function timedChoice(segment: StorySegment, options: readonly ChoiceOption[]): StoryChoice | null {
  const open = options.filter(item => !item.locked && !item.unconnected);
  return (open.find(item => item.choice.id === segment.timer?.default_choice) ?? open[0])?.choice ?? null;
}

export type MapStatus = 'current' | 'played' | 'unlocked' | 'unexplored';

export interface Playthrough {
  current: string | null;
  values: Values;
  /** Each segment with the choice that led into it, as the backend keys a route. */
  steps: PlaytestRun['steps'];
  fromStart: boolean;
  timeouts: number;
  played: ReadonlyMap<string, Values>;
  unlocked: ReadonlyMap<string, Values>;
  endings: ReadonlySet<string>;
}

function arrive(graph: StoryGraph, run: Playthrough, target: string, values: Values, via: string | null): Playthrough {
  const known = (id: string | null) => graph.segments.some(item => item.id === id);
  const segment = graph.segments.find(item => item.id === target);
  if (!segment) return { ...run, current: null };
  const played = new Map(run.played).set(target, values);
  const unlocked = new Map(run.unlocked);
  unlocked.delete(target);
  // Each open door remembers the values it opens with, so replaying from it starts where taking it would have.
  for (const option of nextStep(segment, values, known).options) {
    const next = option.choice.target;
    if (!option.locked && !option.unconnected && next && !played.has(next) && !unlocked.has(next)) {
      unlocked.set(next, applyEffects(option.choice.effects, values, graph.variables));
    }
  }
  return {
    ...run, current: target, values, played, unlocked,
    steps: [...run.steps, { segment: target, choice: via }],
    endings: segment.kind === 'ending' ? new Set(run.endings).add(target) : run.endings,
  };
}

export function startRun(graph: StoryGraph, previous?: Playthrough): Playthrough {
  const empty: Playthrough = {
    current: null, values: initialValues(graph.variables), steps: [], fromStart: true, timeouts: 0,
    played: previous?.played ?? new Map(), unlocked: previous?.unlocked ?? new Map(), endings: previous?.endings ?? new Set(),
  };
  return arrive(graph, empty, graph.start, empty.values, null);
}

export function takeChoice(graph: StoryGraph, run: Playthrough, choice: StoryChoice, timedOut = false): Playthrough {
  if (!choice.target) return run;
  const moved = arrive(graph, run, choice.target, applyEffects(choice.effects, run.values, graph.variables), choice.id);
  return timedOut ? { ...moved, timeouts: moved.timeouts + 1 } : moved;
}

export function followRoute(graph: StoryGraph, run: Playthrough, route: StoryRoute): Playthrough {
  return route.target ? arrive(graph, run, route.target, run.values, null) : run;
}

/** Replay from anything already seen or unlocked; it starts a new run that is not a route through the whole story. */
export function replayFrom(graph: StoryGraph, run: Playthrough, target: string): Playthrough {
  const values = run.played.get(target) ?? run.unlocked.get(target);
  if (!values) return run;
  return arrive(graph, { ...run, steps: [], fromStart: false, timeouts: 0 }, target, values, null);
}

/** A run carried across an edit of the story: new variables start fresh, removed ones go, a deleted segment ends it. */
export function reconcileRun(graph: StoryGraph, run: Playthrough): Playthrough {
  const fresh = initialValues(graph.variables);
  const same = fresh.size === run.values.size && [...fresh.keys()].every(id => run.values.has(id));
  const stillThere = graph.segments.some(item => item.id === run.current);
  if (same && stillThere) return run;
  for (const [id, value] of run.values) {
    if (fresh.has(id) && typeof fresh.get(id) === typeof value) fresh.set(id, value);
  }
  return { ...run, values: fresh, current: stillThere ? run.current : null };
}

export function runToRecord(graph: StoryGraph, run: Playthrough): PlaytestRun {
  const last = graph.segments.find(item => item.id === run.current);
  return { steps: [...run.steps], ending: last?.kind === 'ending' ? last.id : null, from_start: run.fromStart, timeouts: run.timeouts };
}

export function mapStatus(run: Playthrough, id: string): MapStatus {
  if (run.current === id) return 'current';
  if (run.played.has(id)) return 'played';
  return run.unlocked.has(id) ? 'unlocked' : 'unexplored';
}
