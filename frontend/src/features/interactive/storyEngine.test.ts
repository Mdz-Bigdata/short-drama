import { describe, expect, it } from 'vitest';

import { applyEffects, evaluate, followRoute, initialValues, mapStatus, nextStep, reconcileRun, replayFrom, runToRecord, startRun, takeChoice, timedChoice } from './storyEngine';
import type { Condition, StoryChoice, StoryGraph, StorySegment, StoryVariable } from './storyTypes';
import { blankChoice, blankSegment } from './graphOps';

// The same table as backend/tests/test_interactive_story.py runs through Python and the exported player.
const TABLE: Array<[Condition | null, Record<string, number | boolean>, boolean]> = [
  [null, {}, true],
  [{ var: 'x', op: 'eq', value: 1 }, { x: 1 }, true],
  [{ var: 'x', op: 'eq', value: 1 }, { x: 1.0 }, true],
  [{ var: 'x', op: 'ne', value: 1 }, { x: 2 }, true],
  [{ var: 'x', op: 'gt', value: 1 }, { x: 1 }, false],
  [{ var: 'x', op: 'gte', value: 1 }, { x: 1 }, true],
  [{ var: 'x', op: 'lt', value: 1 }, { x: 0.5 }, true],
  [{ var: 'x', op: 'lte', value: 1 }, { x: 2 }, false],
  [{ var: 'missing', op: 'ne', value: 1 }, { x: 1 }, false],
  [{ var: 'f', op: 'eq', value: true }, { f: true }, true],
  [{ var: 'f', op: 'ne', value: true }, { f: false }, true],
  [{ var: 'f', op: 'gt', value: false }, { f: true }, false],
  [{ var: 'f', op: 'eq', value: 1 }, { f: true }, false],
  [{ var: 'x', op: 'eq', value: true }, { x: 1 }, false],
  [{ var: 'x', op: 'ne', value: true }, { x: 1 }, false],
  [{ all: [] }, {}, true],
  [{ any: [] }, {}, false],
  [{ all: [{ var: 'x', op: 'gt', value: 0 }, { var: 'f', op: 'eq', value: true }] }, { x: 1, f: false }, false],
  [{ any: [{ var: 'x', op: 'gt', value: 5 }, { var: 'f', op: 'eq', value: true }] }, { x: 1, f: true }, true],
  [{ all: [{ any: [{ var: 'x', op: 'eq', value: 1 }, { var: 'x', op: 'eq', value: 2 }] }, { var: 'x', op: 'ne', value: 2 }] }, { x: 2 }, false],
];

const number = (id: string, extra: Partial<StoryVariable> = {}): StoryVariable => ({ id, label: id, kind: 'number', initial: 0, min: null, max: null, ...extra });
const flag = (id: string): StoryVariable => ({ id, label: id, kind: 'flag', initial: false, min: null, max: null });

function choice(id: string, target: string | null, extra: Partial<StoryChoice> = {}): StoryChoice {
  return { ...blankChoice(id, id, target), ...extra };
}

function scene(id: string, choices: StoryChoice[], extra: Partial<StorySegment> = {}): StorySegment {
  return { ...blankSegment(id, 'scene', id, null), choices, ...extra };
}

const ending = (id: string): StorySegment => blankSegment(id, 'ending', id, null);

const story: StoryGraph = {
  title: '', synopsis: '', outline: [], start: 'a', variables: [number('x'), flag('f')],
  segments: [
    scene('a', [choice('go', 'b', { effects: [{ var: 'x', op: 'add', value: 1 }] }), choice('skip', 'b')]),
    scene('b', [choice('gold', 'good', { condition: { var: 'x', op: 'gte', value: 1 } }), choice('other', 'bad')]),
    ending('good'), ending('bad'), ending('secret'),
  ],
};

describe('conditions', () => {
  it.each(TABLE)('%j with %j is %s', (condition, values, expected) => {
    expect(evaluate(condition, new Map(Object.entries(values)))).toBe(expected);
  });

  it('never finds a variable on the prototype chain', () => {
    expect(evaluate({ var: 'constructor', op: 'ne', value: 1 }, new Map())).toBe(false);
  });
});

describe('effects', () => {
  const variables = [number('x', { min: 0, max: 10 }), number('y'), flag('f')];
  const values = new Map<string, number | boolean>([['x', 9], ['y', 0], ['f', false]]);

  it('adds, sets and clamps without touching the input', () => {
    expect(applyEffects([{ var: 'x', op: 'add', value: 5 }], values, variables).get('x')).toBe(10);
    expect(applyEffects([{ var: 'x', op: 'add', value: -50 }], values, variables).get('x')).toBe(0);
    expect(applyEffects([{ var: 'x', op: 'set', value: 3 }, { var: 'x', op: 'add', value: 1 }], values, variables).get('x')).toBe(4);
    expect(values.get('x')).toBe(9);
  });

  it('settles float drift the way the backend does', () => {
    expect(applyEffects([{ var: 'y', op: 'add', value: 0.1 }, { var: 'y', op: 'add', value: 0.2 }], values, variables).get('y')).toBe(0.3);
  });

  it('ignores effects of the wrong type or on nothing', () => {
    expect(applyEffects([{ var: 'f', op: 'add', value: 1 }], values, variables)).toEqual(values);
    expect(applyEffects([{ var: 'x', op: 'set', value: true }], values, variables)).toEqual(values);
    expect(applyEffects([{ var: 'ghost', op: 'add', value: 1 }], values, variables)).toEqual(values);
  });

  it('starts inside the limits', () => {
    expect(initialValues([number('x', { initial: 50, max: 10 }), flag('f')])).toEqual(new Map<string, number | boolean>([['x', 10], ['f', false]]));
  });
});

describe('what follows a segment', () => {
  const known = (id: string | null) => id === 'b';
  const gated: StorySegment = scene('s', [
    choice('locked', 'b', { condition: { var: 'x', op: 'gte', value: 5 } }),
    choice('hidden', 'b', { condition: { var: 'x', op: 'gte', value: 5 }, when_locked: 'hide' }),
    choice('open', 'b'),
    choice('nowhere', null),
  ], { timer: { seconds: 5, default_choice: 'locked' } });

  it('shows locked choices, leaves out hidden ones, flags unconnected ones', () => {
    const step = nextStep(gated, new Map([['x', 0]]), known);
    expect(step.kind).toBe('choices');
    expect(step.options.map(item => [item.choice.id, item.locked, item.unconnected])).toEqual([
      ['locked', true, false], ['open', false, false], ['nowhere', false, true],
    ]);
  });

  it('is stuck when nothing can be taken', () => {
    const only = scene('s', [choice('locked', 'b', { condition: { var: 'x', op: 'gte', value: 5 } })]);
    expect(nextStep(only, new Map([['x', 0]]), known).kind).toBe('stuck');
  });

  it('follows the first route that holds, before any choice', () => {
    const routed = scene('s', [choice('open', 'b')], { routes: [
      { id: 'r1', condition: { var: 'x', op: 'gte', value: 5 }, target: 'b' },
      { id: 'r2', condition: null, target: 'gone' },
    ] });
    const low = nextStep(routed, new Map([['x', 0]]), known);
    expect(low.kind).toBe('choices');
    const high = nextStep(routed, new Map([['x', 5]]), known);
    expect(high.kind === 'route' && high.route.id).toBe('r1');
  });

  it('a timeout takes the default, or the first open choice when the default is locked', () => {
    const low = nextStep(gated, new Map([['x', 0]]), known);
    expect(timedChoice(gated, low.options)?.id).toBe('open');
    const high = nextStep(gated, new Map([['x', 9]]), known);
    expect(timedChoice(gated, high.options)?.id).toBe('locked');
    expect(timedChoice(gated, [])).toBeNull();
  });
});

describe('a playthrough', () => {
  it('tracks values, what was played, what is unlocked and which endings were seen', () => {
    let run = startRun(story);
    expect(run.current).toBe('a');
    expect([...run.unlocked.keys()]).toEqual(['b']);
    expect(mapStatus(run, 'a')).toBe('current');
    expect(mapStatus(run, 'b')).toBe('unlocked');
    expect(mapStatus(run, 'good')).toBe('unexplored');

    run = takeChoice(story, run, story.segments[0].choices[0]);
    expect(run.values.get('x')).toBe(1);
    expect(mapStatus(run, 'a')).toBe('played');
    expect(mapStatus(run, 'good')).toBe('unlocked');

    run = takeChoice(story, run, story.segments[1].choices[0]);
    expect(run.current).toBe('good');
    expect([...run.endings]).toEqual(['good']);
    expect(runToRecord(story, run)).toEqual({
      steps: [{ segment: 'a', choice: null }, { segment: 'b', choice: 'go' }, { segment: 'good', choice: 'gold' }],
      ending: 'good', from_start: true, timeouts: 0,
    });
  });

  it('does not unlock what a locked choice leads to', () => {
    const run = takeChoice(story, startRun(story), story.segments[0].choices[1]);
    expect(run.values.get('x')).toBe(0);
    expect(mapStatus(run, 'good')).toBe('unexplored');
    expect(mapStatus(run, 'bad')).toBe('unlocked');
  });

  it('a new run keeps what has been explored', () => {
    const first = takeChoice(story, startRun(story), story.segments[0].choices[0]);
    const again = startRun(story, first);
    expect(again.values.get('x')).toBe(0);
    expect(again.steps).toEqual([{ segment: 'a', choice: null }]);
    expect(mapStatus(again, 'b')).toBe('played');
  });

  it('replays with the values the segment was seen with and is not a whole route', () => {
    const first = takeChoice(story, startRun(story), story.segments[0].choices[0]);
    const overAgain = startRun(story, first);
    const replay = replayFrom(story, overAgain, 'b');
    expect(replay.current).toBe('b');
    expect(replay.values.get('x')).toBe(1);
    expect(replay.fromStart).toBe(false);
    expect(replay.steps).toEqual([{ segment: 'b', choice: null }]);
    expect(replayFrom(story, overAgain, 'secret')).toBe(overAgain);
  });

  it('replaying an unlocked segment starts with the effects of the choice that opens it', () => {
    const atB = takeChoice(story, startRun(story), story.segments[0].choices[0]);
    expect(replayFrom(story, atB, 'good').values.get('x')).toBe(1);
  });

  it('counts a timeout and follows routes', () => {
    const routed: StoryGraph = { ...story, segments: [scene('a', [], { routes: [{ id: 'r', condition: null, target: 'good' }] }), ending('good')] };
    const moved = followRoute(routed, startRun(routed), routed.segments[0].routes[0]);
    expect(moved.current).toBe('good');
    expect(moved.steps[1]).toEqual({ segment: 'good', choice: null });
    expect(takeChoice(story, startRun(story), story.segments[0].choices[0], true).timeouts).toBe(1);
  });

  it('survives the story being edited under it', () => {
    const run = takeChoice(story, startRun(story), story.segments[0].choices[0]);
    const edited: StoryGraph = { ...story, variables: [number('x'), number('new', { initial: 7 })], segments: story.segments.filter(item => item.id !== 'b') };
    const reconciled = reconcileRun(edited, run);
    expect(reconciled.current).toBeNull();
    expect(reconciled.values).toEqual(new Map([['x', 1], ['new', 7]]));
    expect(reconcileRun(story, run)).toBe(run);
  });
});
