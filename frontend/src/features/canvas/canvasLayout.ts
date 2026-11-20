// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/lib/canvas/canvas-layout.ts.
import { boundsOf } from './canvasGeometry';
import { carriedIds, layoutUnits } from './canvasFrames';
import type { CanvasDoc, CanvasEdge, CanvasNode } from './canvasTypes';

export type AlignKind = 'left' | 'hcenter' | 'right' | 'top' | 'vcenter' | 'bottom';
export type DistributeAxis = 'horizontal' | 'vertical';
export type ArrangeKind = 'row' | 'column' | 'grid' | 'edges' | 'spread';

/** New top-left corners by node id. A moved group's members are in it too, shifted by the group's own move. */
export type PositionPatch = Record<string, { x: number; y: number }>;

export const ARRANGE_GAP = 40;
export const FLOW_COLUMN_GAP = 120;
export const FLOW_ROW_GAP = 40;

type Nodes = readonly CanvasNode[];
type Box = { id: string; x: number; y: number; width: number; height: number };

/** Turn unit moves into a patch that carries each moved group's members along (nested ones too). */
function carry(nodes: Nodes, moves: ReadonlyMap<string, { x: number; y: number }>): PositionPatch {
  const byId = new Map(nodes.map(node => [node.id, node]));
  const patch: PositionPatch = {};
  for (const [id, to] of moves) {
    const unit = byId.get(id);
    if (!unit) continue;
    const dx = to.x - unit.x;
    const dy = to.y - unit.y;
    if (!dx && !dy) continue;
    for (const moved of carriedIds(nodes, new Set([id]))) {
      const node = byId.get(moved)!;
      patch[moved] = { x: node.x + dx, y: node.y + dy };
    }
  }
  return patch;
}

/** Apply a patch; nodes it does not name keep their place. */
export function applyPositions(doc: CanvasDoc, patch: PositionPatch): CanvasDoc {
  if (!Object.keys(patch).length) return doc;
  return { ...doc, nodes: doc.nodes.map(node => (patch[node.id] ? { ...node, ...patch[node.id] } : node)) };
}

function byReadingOrder(a: CanvasNode, b: CanvasNode) {
  return a.y - b.y || a.x - b.x || a.id.localeCompare(b.id);
}

export function align(nodes: Nodes, ids: Iterable<string>, kind: AlignKind): PositionPatch {
  const units = layoutUnits(nodes, ids);
  const box = boundsOf(units);
  if (!box || units.length < 2) return {};
  const right = box.x + box.width;
  const bottom = box.y + box.height;
  const moves = new Map(units.map(unit => {
    const x = kind === 'left' ? box.x : kind === 'hcenter' ? box.x + box.width / 2 - unit.width / 2 : kind === 'right' ? right - unit.width : unit.x;
    const y = kind === 'top' ? box.y : kind === 'vcenter' ? box.y + box.height / 2 - unit.height / 2 : kind === 'bottom' ? bottom - unit.height : unit.y;
    return [unit.id, { x, y }];
  }));
  return carry(nodes, moves);
}

/** Equal gaps between neighbours along an axis; the outermost two stay put. Needs three. */
export function distribute(nodes: Nodes, ids: Iterable<string>, axis: DistributeAxis): PositionPatch {
  const units = layoutUnits(nodes, ids);
  if (units.length < 3) return {};
  const horizontal = axis === 'horizontal';
  const start = (node: CanvasNode) => (horizontal ? node.x : node.y);
  const size = (node: CanvasNode) => (horizontal ? node.width : node.height);
  const sorted = [...units].sort((a, b) => start(a) - start(b) || a.id.localeCompare(b.id));
  const first = start(sorted[0]);
  const end = Math.max(...sorted.map(node => start(node) + size(node)));
  const gap = (end - first - sorted.reduce((sum, node) => sum + size(node), 0)) / (sorted.length - 1);
  const moves = new Map<string, { x: number; y: number }>();
  let at = first;
  for (const node of sorted) {
    moves.set(node.id, horizontal ? { x: at, y: node.y } : { x: node.x, y: at });
    at += size(node) + gap;
  }
  return carry(nodes, moves);
}

export function arrangeRow(nodes: Nodes, ids: Iterable<string>, gap = ARRANGE_GAP): PositionPatch {
  const units = layoutUnits(nodes, ids);
  const box = boundsOf(units);
  if (!box || units.length < 2) return {};
  const moves = new Map<string, { x: number; y: number }>();
  let x = box.x;
  for (const unit of [...units].sort((a, b) => a.x - b.x || a.y - b.y || a.id.localeCompare(b.id))) {
    moves.set(unit.id, { x, y: box.y });
    x += unit.width + gap;
  }
  return carry(nodes, moves);
}

export function arrangeColumn(nodes: Nodes, ids: Iterable<string>, gap = ARRANGE_GAP): PositionPatch {
  const units = layoutUnits(nodes, ids);
  const box = boundsOf(units);
  if (!box || units.length < 2) return {};
  const moves = new Map<string, { x: number; y: number }>();
  let y = box.y;
  for (const unit of [...units].sort(byReadingOrder)) {
    moves.set(unit.id, { x: box.x, y });
    y += unit.height + gap;
  }
  return carry(nodes, moves);
}

/** Lay boxes out in reading order on a grid; each column is as wide, and each row as tall, as its largest box. */
function gridOf(boxes: readonly Box[], columns: number, gap: number): Map<string, { x: number; y: number }> {
  const widths = Array.from({ length: columns }, (_, column) => Math.max(0, ...boxes.filter((_, index) => index % columns === column).map(box => box.width)));
  const rows = Math.ceil(boxes.length / columns);
  const heights = Array.from({ length: rows }, (_, row) => Math.max(0, ...boxes.slice(row * columns, row * columns + columns).map(box => box.height)));
  const result = new Map<string, { x: number; y: number }>();
  boxes.forEach((box, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    const x = widths.slice(0, column).reduce((sum, width) => sum + width + gap, 0);
    const y = heights.slice(0, row).reduce((sum, height) => sum + height + gap, 0);
    result.set(box.id, { x, y });
  });
  return result;
}

export function arrangeGrid(nodes: Nodes, ids: Iterable<string>, columns?: number, gap = ARRANGE_GAP): PositionPatch {
  const units = layoutUnits(nodes, ids);
  const box = boundsOf(units);
  if (!box || units.length < 2) return {};
  const count = Math.max(1, Math.min(units.length, columns ?? Math.ceil(Math.sqrt(units.length))));
  const local = gridOf([...units].sort(byReadingOrder), count, gap);
  return carry(nodes, new Map([...local].map(([id, at]) => [id, { x: box.x + at.x, y: box.y + at.y }])));
}

interface Block {
  positions: Map<string, { x: number; y: number }>;
  width: number;
  height: number;
  anchor: { x: number; y: number };
}

/** One connected piece: break cycles by DFS, layer by longest path, order layers by barycentre, centre children on parents. */
function layeredBlock(units: readonly CanvasNode[], links: ReadonlyArray<[string, string]>): Block {
  const byId = new Map(units.map(node => [node.id, node]));
  const ordered = [...units].sort(byReadingOrder);
  const outbound = new Map(units.map(node => [node.id, [] as string[]]));
  links.forEach(([from, to]) => outbound.get(from)!.push(to));
  const dagOut = new Map(units.map(node => [node.id, [] as string[]]));
  const dagIn = new Map(units.map(node => [node.id, [] as string[]]));
  const state = new Map<string, 1 | 2>();
  const visit = (root: string) => {
    // Iterative DFS: a back edge (to a node still on the stack) is dropped, every other edge keeps its direction.
    const stack: Array<{ id: string; next: number }> = [{ id: root, next: 0 }];
    state.set(root, 1);
    while (stack.length) {
      const frame = stack[stack.length - 1];
      const targets = outbound.get(frame.id)!;
      if (frame.next >= targets.length) {
        state.set(frame.id, 2);
        stack.pop();
        continue;
      }
      const target = targets[frame.next++];
      if (state.get(target) === 1) continue;
      dagOut.get(frame.id)!.push(target);
      dagIn.get(target)!.push(frame.id);
      if (!state.has(target)) {
        state.set(target, 1);
        stack.push({ id: target, next: 0 });
      }
    }
  };
  const hasInbound = new Set(links.map(([, to]) => to));
  ordered.filter(node => !hasInbound.has(node.id)).forEach(node => { if (!state.has(node.id)) visit(node.id); });
  ordered.forEach(node => { if (!state.has(node.id)) visit(node.id); });

  const layer = new Map<string, number>();
  const pending = new Map(units.map(node => [node.id, dagIn.get(node.id)!.length]));
  const queue = ordered.filter(node => !pending.get(node.id)).map(node => node.id);
  queue.forEach(id => layer.set(id, 0));
  for (let head = 0; head < queue.length; head += 1) {
    const id = queue[head];
    for (const target of dagOut.get(id)!) {
      layer.set(target, Math.max(layer.get(target) ?? 0, layer.get(id)! + 1));
      pending.set(target, pending.get(target)! - 1);
      if (!pending.get(target)) queue.push(target);
    }
  }
  const layerCount = Math.max(...layer.values()) + 1;
  const layers: string[][] = Array.from({ length: layerCount }, () => []);
  ordered.forEach(node => layers[layer.get(node.id) ?? 0].push(node.id));

  const indexOf = new Map<string, number>();
  const reindex = (ids: string[]) => ids.forEach((id, index) => indexOf.set(id, index));
  layers.forEach(reindex);
  const sortByBarycentre = (ids: string[], neighbours: Map<string, string[]>) => {
    const score = new Map(ids.map(id => {
      const linked = neighbours.get(id)!;
      return [id, linked.length ? linked.reduce((sum, other) => sum + indexOf.get(other)!, 0) / linked.length : indexOf.get(id)!];
    }));
    ids.sort((a, b) => score.get(a)! - score.get(b)! || indexOf.get(a)! - indexOf.get(b)!);
    reindex(ids);
  };
  for (let sweep = 0; sweep < 4; sweep += 1) {
    for (let index = 1; index < layerCount; index += 1) sortByBarycentre(layers[index], dagIn);
    for (let index = layerCount - 2; index >= 0; index -= 1) sortByBarycentre(layers[index], dagOut);
  }

  const positions = new Map<string, { x: number; y: number }>();
  let columnX = 0;
  for (const ids of layers) {
    let previousBottom = -Infinity;
    for (const id of ids) {
      const node = byId.get(id)!;
      const parents = dagIn.get(id)!.filter(parent => positions.has(parent));
      const desired = parents.length
        ? parents.reduce((sum, parent) => sum + positions.get(parent)!.y + byId.get(parent)!.height / 2, 0) / parents.length - node.height / 2
        : Number.isFinite(previousBottom) ? previousBottom + FLOW_ROW_GAP : 0;
      const y = Math.max(desired, previousBottom + FLOW_ROW_GAP);
      positions.set(id, { x: columnX, y });
      previousBottom = y + node.height;
    }
    columnX += Math.max(...ids.map(id => byId.get(id)!.width)) + FLOW_COLUMN_GAP;
  }
  const top = Math.min(...[...positions.values()].map(at => at.y));
  let height = 0;
  for (const [id, at] of positions) {
    at.y -= top;
    height = Math.max(height, at.y + byId.get(id)!.height);
  }
  const anchor = boundsOf(units)!;
  return { positions, width: columnX - FLOW_COLUMN_GAP, height, anchor: { x: anchor.x, y: anchor.y } };
}

/**
 * Lay out by connections: each connected piece flows left to right by dependency depth (columns 120 apart,
 * rows 40 apart); pieces stack downwards, and loose nodes follow on a grid. Cycles are tolerated.
 * An edge to a member of a selected group counts as an edge to that group.
 */
export function arrangeByEdges(nodes: Nodes, edges: readonly CanvasEdge[], ids: Iterable<string>): PositionPatch {
  const units = layoutUnits(nodes, ids);
  const box = boundsOf(units);
  if (!box || units.length < 2) return {};
  const owner = new Map<string, string>();
  for (const unit of units) for (const id of carriedIds(nodes, new Set([unit.id]))) owner.set(id, unit.id);
  const seen = new Set<string>();
  const links: Array<[string, string]> = [];
  for (const edge of edges) {
    const from = owner.get(edge.source);
    const to = owner.get(edge.target);
    const key = `${from}\u0000${to}`;
    if (!from || !to || from === to || seen.has(key)) continue;
    seen.add(key);
    links.push([from, to]);
  }
  const root = new Map(units.map(unit => [unit.id, unit.id]));
  const find = (id: string): string => {
    let at = id;
    while (root.get(at) !== at) at = root.get(at)!;
    root.set(id, at);
    return at;
  };
  links.forEach(([from, to]) => root.set(find(from), find(to)));
  const pieces = new Map<string, CanvasNode[]>();
  for (const unit of units) pieces.set(find(unit.id), [...(pieces.get(find(unit.id)) ?? []), unit]);
  const blocks: Block[] = [];
  const loose: CanvasNode[] = [];
  for (const members of pieces.values()) {
    if (members.length === 1) { loose.push(members[0]); continue; }
    const inside = new Set(members.map(member => member.id));
    blocks.push(layeredBlock(members, links.filter(([from]) => inside.has(from))));
  }
  blocks.sort((a, b) => a.anchor.y - b.anchor.y || a.anchor.x - b.anchor.x);
  if (loose.length) {
    const sorted = loose.sort(byReadingOrder);
    const positions = gridOf(sorted, Math.ceil(Math.sqrt(sorted.length)), ARRANGE_GAP);
    const placed = boundsOf(sorted.map(node => ({ ...node, ...positions.get(node.id)! })))!;
    blocks.push({ positions, width: placed.width, height: placed.height, anchor: { x: 0, y: 0 } });
  }
  const moves = new Map<string, { x: number; y: number }>();
  let y = box.y;
  for (const block of blocks) {
    for (const [id, at] of block.positions) moves.set(id, { x: box.x + at.x, y: y + at.y });
    y += block.height + FLOW_COLUMN_GAP;
  }
  return carry(nodes, moves);
}

/**
 * Push overlapping boxes apart, each pair along the axis where it overlaps least and split between the two,
 * so nothing moves further than it has to. `gap` is the clearance kept between neighbours.
 */
export function spreadOut(nodes: Nodes, ids: Iterable<string>, gap = ARRANGE_GAP): PositionPatch {
  const units = layoutUnits(nodes, ids);
  if (units.length < 2) return {};
  const items: Box[] = units.map(unit => ({ id: unit.id, x: unit.x, y: unit.y, width: unit.width, height: unit.height }));
  for (let pass = 0; pass < 64; pass += 1) {
    let moved = false;
    for (let i = 0; i < items.length; i += 1) {
      for (let j = i + 1; j < items.length; j += 1) {
        const a = items[i];
        const b = items[j];
        const overlapX = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x) + gap;
        const overlapY = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y) + gap;
        if (overlapX <= 0.001 || overlapY <= 0.001) continue;
        const centreDx = a.x + a.width / 2 - (b.x + b.width / 2);
        const centreDy = a.y + a.height / 2 - (b.y + b.height / 2);
        const tie = a.id < b.id ? -1 : 1;
        if (overlapX <= overlapY) {
          const direction = centreDx === 0 ? tie : Math.sign(centreDx);
          a.x += (direction * overlapX) / 2;
          b.x -= (direction * overlapX) / 2;
        } else {
          const direction = centreDy === 0 ? tie : Math.sign(centreDy);
          a.y += (direction * overlapY) / 2;
          b.y -= (direction * overlapY) / 2;
        }
        moved = true;
      }
    }
    if (!moved) break;
  }
  return carry(nodes, new Map(items.map(item => [item.id, { x: item.x, y: item.y }])));
}

/** One entry point for the toolbar's arrange buttons. */
export function arrange(doc: CanvasDoc, ids: Iterable<string>, kind: ArrangeKind): PositionPatch {
  switch (kind) {
    case 'row': return arrangeRow(doc.nodes, ids);
    case 'column': return arrangeColumn(doc.nodes, ids);
    case 'grid': return arrangeGrid(doc.nodes, ids);
    case 'edges': return arrangeByEdges(doc.nodes, doc.edges, ids);
    case 'spread': return spreadOut(doc.nodes, ids);
  }
}
