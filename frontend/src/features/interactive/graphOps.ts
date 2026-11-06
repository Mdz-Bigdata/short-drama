import type { Condition, Point, StoryChoice, StoryGraph, StoryRoute, StorySegment, StoryVariable } from './storyTypes';

export const NODE_WIDTH = 220;
const NODE_HEADER = 58;
const NODE_ROW = 26;
const COLUMN_GAP = 110;
const ROW_GAP = 34;

export const MAX_SEGMENTS = 300;
export const MAX_CHOICES = 8;
export const MAX_ROUTES = 8;
export const MAX_VARIABLES = 60;

/** A node's height follows from its data, so edges land on their ports without measuring the DOM. */
export function nodeHeight(segment: StorySegment): number {
  return NODE_HEADER + (segment.choices.length + segment.routes.length) * NODE_ROW + (segment.kind === 'ending' ? 0 : NODE_ROW);
}

export function outPort(position: Point, row: number): Point {
  return { x: position.x + NODE_WIDTH, y: position.y + NODE_HEADER + NODE_ROW * row + NODE_ROW / 2 };
}

export function inPort(position: Point): Point {
  return { x: position.x, y: position.y + 24 };
}

/** A curve that leaves to the right and enters from the left; a backward edge swings wide so it stays readable. */
export function edgePath(from: Point, to: Point): string {
  const reach = to.x >= from.x + 40 ? Math.max(40, (to.x - from.x) / 2) : 110 + Math.abs(to.y - from.y) / 6;
  return `M ${from.x} ${from.y} C ${from.x + reach} ${from.y}, ${to.x - reach} ${to.y}, ${to.x} ${to.y}`;
}

export function positionOf(segment: StorySegment): Point {
  return segment.position ?? { x: 0, y: 0 };
}

export interface GraphEdge {
  id: string;
  kind: 'choice' | 'route';
  from: string;
  to: string;
  row: number;
  label: string;
  gated: boolean;
  isDefault: boolean;
  hasEffects: boolean;
}

export function graphEdges(graph: StoryGraph): GraphEdge[] {
  const known = new Set(graph.segments.map(item => item.id));
  const edges: GraphEdge[] = [];
  for (const segment of graph.segments) {
    segment.choices.forEach((choice, row) => {
      if (choice.target && known.has(choice.target)) {
        edges.push({
          id: choice.id, kind: 'choice', from: segment.id, to: choice.target, row, label: choice.text,
          gated: Boolean(choice.condition), isDefault: segment.timer?.default_choice === choice.id, hasEffects: choice.effects.length > 0,
        });
      }
    });
    segment.routes.forEach((route, index) => {
      if (route.target && known.has(route.target)) {
        edges.push({
          id: route.id, kind: 'route', from: segment.id, to: route.target, row: segment.choices.length + index, label: '',
          gated: Boolean(route.condition), isDefault: false, hasEffects: false,
        });
      }
    });
  }
  return edges;
}

/** The node under a point; the later one in the list is drawn on top. */
export function nodeAt(graph: StoryGraph, point: Point): string | null {
  for (let index = graph.segments.length - 1; index >= 0; index -= 1) {
    const segment = graph.segments[index];
    const { x, y } = positionOf(segment);
    if (point.x >= x && point.x <= x + NODE_WIDTH && point.y >= y && point.y <= y + nodeHeight(segment)) return segment.id;
  }
  return null;
}

export function graphBounds(graph: StoryGraph): { left: number; top: number; right: number; bottom: number } {
  if (!graph.segments.length) return { left: 0, top: 0, right: NODE_WIDTH, bottom: 120 };
  const boxes = graph.segments.map(segment => ({ ...positionOf(segment), height: nodeHeight(segment) }));
  return {
    left: Math.min(...boxes.map(box => box.x)),
    top: Math.min(...boxes.map(box => box.y)),
    right: Math.max(...boxes.map(box => box.x + NODE_WIDTH)),
    bottom: Math.max(...boxes.map(box => box.y + box.height)),
  };
}

/** Columns by distance from the start; whatever cannot be reached goes in a column of its own at the far end. */
export function autoLayout(graph: StoryGraph): StoryGraph {
  const byId = new Map(graph.segments.map(item => [item.id, item]));
  const depth = new Map<string, number>();
  const queue = byId.has(graph.start) ? [graph.start] : [];
  if (queue.length) depth.set(graph.start, 0);
  for (let head = 0; head < queue.length; head += 1) {
    const segment = byId.get(queue[head])!;
    const level = depth.get(segment.id)!;
    for (const edge of [...segment.choices, ...segment.routes]) {
      if (edge.target && byId.has(edge.target) && !depth.has(edge.target)) {
        depth.set(edge.target, level + 1);
        queue.push(edge.target);
      }
    }
  }
  const lastColumn = Math.max(-1, ...depth.values()) + 1;
  const columnTop = new Map<number, number>();
  const segments = graph.segments.map(segment => {
    const column = depth.get(segment.id) ?? lastColumn;
    const top = columnTop.get(column) ?? 0;
    columnTop.set(column, top + nodeHeight(segment) + ROW_GAP);
    return { ...segment, position: { x: column * (NODE_WIDTH + COLUMN_GAP), y: top } };
  });
  return { ...graph, segments };
}

/** A draft straight from the model has no layout; a partly placed graph keeps what the author arranged. */
export function ensureLayout(graph: StoryGraph): StoryGraph {
  return graph.segments.some(segment => !segment.position) ? autoLayout(graph) : graph;
}

function freshId(prefix: string, taken: ReadonlySet<string>): string {
  let number = taken.size + 1;
  while (taken.has(`${prefix}${number}`)) number += 1;
  return `${prefix}${number}`;
}

function edgeIds(graph: StoryGraph): Set<string> {
  return new Set(graph.segments.flatMap(segment => [...segment.choices, ...segment.routes].map(edge => edge.id)));
}

function updateSegments(graph: StoryGraph, id: string, change: (segment: StorySegment) => StorySegment): StoryGraph {
  return { ...graph, segments: graph.segments.map(item => (item.id === id ? change(item) : item)) };
}

export function blankSegment(id: string, kind: StorySegment['kind'], title: string, position: Point | null): StorySegment {
  return {
    id, title, kind, narration: '', dialogue: [], media: null, est_seconds: null, ending_label: '', timer: null,
    choices: [], routes: [], position,
  };
}

export function blankChoice(id: string, text: string, target: string | null): StoryChoice {
  return { id, text, target, condition: null, when_locked: 'lock', locked_hint: '', effects: [] };
}

export function starterGraph(openingTitle: string, endingTitle: string, choiceText: string): StoryGraph {
  return autoLayout({
    title: '', synopsis: '', outline: [], start: 's1', variables: [],
    segments: [
      { ...blankSegment('s1', 'scene', openingTitle, null), choices: [blankChoice('c1', choiceText, 'end1')] },
      blankSegment('end1', 'ending', endingTitle, null),
    ],
  });
}

export function addSegment(graph: StoryGraph, kind: StorySegment['kind'], title: string, position: Point): { graph: StoryGraph; id: string } {
  const id = freshId(kind === 'ending' ? 'end' : 's', new Set(graph.segments.map(item => item.id)));
  const next = { ...graph, segments: [...graph.segments, blankSegment(id, kind, title, position)] };
  return { graph: next.start ? next : { ...next, start: id }, id };
}

export function updateSegment(graph: StoryGraph, id: string, patch: Partial<StorySegment>): StoryGraph {
  return updateSegments(graph, id, segment => ({ ...segment, ...patch }));
}

/** Everything pointing at a deleted segment goes back to unconnected, which validation then names. */
export function deleteSegment(graph: StoryGraph, id: string): StoryGraph {
  const segments = graph.segments.filter(item => item.id !== id).map(segment => ({
    ...segment,
    choices: segment.choices.map(choice => (choice.target === id ? { ...choice, target: null } : choice)),
    routes: segment.routes.map(route => (route.target === id ? { ...route, target: null } : route)),
  }));
  return { ...graph, segments, start: graph.start === id ? (segments[0]?.id ?? '') : graph.start };
}

/** An ending has no exits, so turning a scene into one has to drop them rather than leave them lying around. */
export function setKind(graph: StoryGraph, id: string, kind: StorySegment['kind']): StoryGraph {
  return updateSegments(graph, id, segment => (kind === 'ending'
    ? { ...segment, kind, choices: [], routes: [], timer: null }
    : { ...segment, kind }));
}

export function addChoice(graph: StoryGraph, segmentId: string, text: string, target: string | null = null): { graph: StoryGraph; id: string } {
  const id = freshId('c', edgeIds(graph));
  return { graph: updateSegments(graph, segmentId, segment => ({ ...segment, choices: [...segment.choices, blankChoice(id, text, target)] })), id };
}

export function updateChoice(graph: StoryGraph, segmentId: string, choiceId: string, patch: Partial<StoryChoice>): StoryGraph {
  return updateSegments(graph, segmentId, segment => ({
    ...segment, choices: segment.choices.map(choice => (choice.id === choiceId ? { ...choice, ...patch } : choice)),
  }));
}

export function deleteChoice(graph: StoryGraph, segmentId: string, choiceId: string): StoryGraph {
  return updateSegments(graph, segmentId, segment => ({
    ...segment,
    choices: segment.choices.filter(choice => choice.id !== choiceId),
    timer: segment.timer?.default_choice === choiceId ? { ...segment.timer, default_choice: '' } : segment.timer,
  }));
}

export function moveItem<T>(items: readonly T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (target < 0 || target >= items.length) return [...items];
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export function moveChoice(graph: StoryGraph, segmentId: string, choiceId: string, delta: number): StoryGraph {
  return updateSegments(graph, segmentId, segment => ({
    ...segment, choices: moveItem(segment.choices, segment.choices.findIndex(item => item.id === choiceId), delta),
  }));
}

export function addRoute(graph: StoryGraph, segmentId: string, target: string | null = null): { graph: StoryGraph; id: string } {
  const id = freshId('r', edgeIds(graph));
  const route: StoryRoute = { id, condition: null, target };
  return { graph: updateSegments(graph, segmentId, segment => ({ ...segment, routes: [...segment.routes, route] })), id };
}

export function updateRoute(graph: StoryGraph, segmentId: string, routeId: string, patch: Partial<StoryRoute>): StoryGraph {
  return updateSegments(graph, segmentId, segment => ({
    ...segment, routes: segment.routes.map(route => (route.id === routeId ? { ...route, ...patch } : route)),
  }));
}

export function deleteRoute(graph: StoryGraph, segmentId: string, routeId: string): StoryGraph {
  return updateSegments(graph, segmentId, segment => ({ ...segment, routes: segment.routes.filter(route => route.id !== routeId) }));
}

export function moveRoute(graph: StoryGraph, segmentId: string, routeId: string, delta: number): StoryGraph {
  return updateSegments(graph, segmentId, segment => ({
    ...segment, routes: moveItem(segment.routes, segment.routes.findIndex(item => item.id === routeId), delta),
  }));
}

/** Point an existing edge somewhere else; ``null`` disconnects it. */
export function connectEdge(graph: StoryGraph, segmentId: string, edgeId: string, target: string | null): StoryGraph {
  return updateSegments(graph, segmentId, segment => ({
    ...segment,
    choices: segment.choices.map(choice => (choice.id === edgeId ? { ...choice, target } : choice)),
    routes: segment.routes.map(route => (route.id === edgeId ? { ...route, target } : route)),
  }));
}

function conditionUses(condition: Condition | null, id: string): number {
  if (!condition) return 0;
  if ('all' in condition) return condition.all.reduce((sum, item) => sum + conditionUses(item, id), 0);
  if ('any' in condition) return condition.any.reduce((sum, item) => sum + conditionUses(item, id), 0);
  return condition.var === id ? 1 : 0;
}

export function variableUses(graph: StoryGraph, id: string): number {
  let uses = 0;
  for (const segment of graph.segments) {
    for (const choice of segment.choices) {
      uses += conditionUses(choice.condition, id) + choice.effects.filter(effect => effect.var === id).length;
    }
    for (const route of segment.routes) uses += conditionUses(route.condition, id);
  }
  return uses;
}

export function addVariable(graph: StoryGraph, kind: StoryVariable['kind'], label: string): { graph: StoryGraph; id: string } {
  const id = freshId(kind === 'flag' ? 'flag' : 'var', new Set(graph.variables.map(item => item.id)));
  const variable: StoryVariable = { id, label, kind, initial: kind === 'flag' ? false : 0, min: null, max: null };
  return { graph: { ...graph, variables: [...graph.variables, variable] }, id };
}

export function updateVariable(graph: StoryGraph, id: string, patch: Partial<StoryVariable>): StoryGraph {
  return { ...graph, variables: graph.variables.map(item => (item.id === id ? { ...item, ...patch } : item)) };
}

export function deleteVariable(graph: StoryGraph, id: string): StoryGraph {
  return { ...graph, variables: graph.variables.filter(item => item.id !== id) };
}
