// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/lib/canvas/canvas-frame.ts.
// Snap targets follow web/src/lib/canvas/canvas-project-domain.ts (createNodeAlignmentContext).
import { boundsOf } from './canvasGeometry';
import { newNode } from './canvasGraph';
import type { CanvasDoc, CanvasEdge, CanvasNode, NodePayload, Rect } from './canvasTypes';

export const FRAME_HEADER = 36;
export const FRAME_PADDING = 24;
export const COLLAPSED_WIDTH = 240;
export const COLLAPSED_HEIGHT = 144;
/** A group may sit inside one other group, never deeper. */
export const MAX_GROUP_DEPTH = 1;

type Nodes = readonly CanvasNode[];

function nodesOf(source: CanvasDoc | Nodes): Nodes {
  return Array.isArray(source) ? source : (source as CanvasDoc).nodes;
}

export function isGroup(node: CanvasNode | undefined | null): node is CanvasNode {
  return node?.kind === 'group';
}

export function isCollapsed(node: CanvasNode | undefined | null) {
  return isGroup(node) && node.payload.collapsed === true;
}

function childrenByParent(nodes: Nodes) {
  const children = new Map<string, CanvasNode[]>();
  for (const node of nodes) {
    const parent = node.payload.groupId;
    if (parent) children.set(parent, [...(children.get(parent) ?? []), node]);
  }
  return children;
}

/** Everything inside a group, members of its nested groups included; a cycle in bad data stops the walk. */
export function descendantIds(source: CanvasDoc | Nodes, groupId: string): Set<string> {
  const children = childrenByParent(nodesOf(source));
  const found = new Set<string>();
  const stack = [groupId];
  while (stack.length) {
    for (const child of children.get(stack.pop()!) ?? []) {
      if (child.id === groupId || found.has(child.id)) continue;
      found.add(child.id);
      stack.push(child.id);
    }
  }
  return found;
}

/**
 * Everything that moves when these nodes are dragged: canvasGraph.movingIds, but a nested group brings its
 * members too. With no nesting the two agree.
 */
export function carriedIds(nodes: Nodes, selected: ReadonlySet<string>): Set<string> {
  const carried = new Set<string>();
  for (const node of nodes) {
    if (!selected.has(node.id)) continue;
    carried.add(node.id);
    if (node.kind === 'group') descendantIds(nodes, node.id).forEach(id => carried.add(id));
  }
  return carried;
}

/** The selected nodes a layout moves as one: a member whose (outer) group is also selected rides along with it. */
export function layoutUnits(nodes: Nodes, ids: Iterable<string>): CanvasNode[] {
  const selected = new Set(ids);
  const groups = nodes.filter(node => node.kind === 'group' && selected.has(node.id));
  const ridden = new Set<string>();
  for (const group of groups) descendantIds(nodes, group.id).forEach(id => ridden.add(id));
  return nodes.filter(node => selected.has(node.id) && !ridden.has(node.id));
}

/** How many groups enclose this node (0 for a top-level node), guarding against cycles. */
export function groupDepth(source: CanvasDoc | Nodes, id: string): number {
  const byId = new Map(nodesOf(source).map(node => [node.id, node]));
  const seen = new Set<string>([id]);
  let depth = 0;
  let parent = byId.get(id)?.payload.groupId;
  while (parent && byId.has(parent) && !seen.has(parent)) {
    seen.add(parent);
    depth += 1;
    parent = byId.get(parent)!.payload.groupId;
  }
  return depth;
}

function containsGroups(nodes: Nodes, groupId: string) {
  return nodes.some(node => node.kind === 'group' && node.payload.groupId === groupId);
}

/** Whether a group may be put inside another: one level only, never into itself or what it holds. */
export function canNest(source: CanvasDoc | Nodes, childGroupId: string, parentGroupId: string): boolean {
  const nodes = nodesOf(source);
  const child = nodes.find(node => node.id === childGroupId);
  const parent = nodes.find(node => node.id === parentGroupId);
  if (!isGroup(child) || !isGroup(parent) || child.id === parent.id) return false;
  if (descendantIds(nodes, child.id).has(parent.id)) return false;
  // The parent must be top level and the child must not hold groups of its own.
  if (groupDepth(nodes, parent.id) + 1 > MAX_GROUP_DEPTH) return false;
  return !containsGroups(nodes, child.id);
}

/** Members of collapsed groups (and anything nested inside them): not drawn, not hit, not snapped to. */
export function hiddenMemberIds(source: CanvasDoc | Nodes): Set<string> {
  const nodes = nodesOf(source);
  const hidden = new Set<string>();
  for (const node of nodes) if (isCollapsed(node)) descendantIds(nodes, node.id).forEach(id => hidden.add(id));
  return hidden;
}

export function visibleNodes(source: CanvasDoc | Nodes): CanvasNode[] {
  const nodes = nodesOf(source);
  const hidden = hiddenMemberIds(nodes);
  return nodes.filter(node => !hidden.has(node.id));
}

/** The outermost collapsed group that hides a node, or the node itself when it is shown. */
export function shownAs(source: CanvasDoc | Nodes, id: string): string {
  const byId = new Map(nodesOf(source).map(node => [node.id, node]));
  let shown = id;
  const seen = new Set<string>([id]);
  let parent = byId.get(id)?.payload.groupId;
  while (parent && !seen.has(parent)) {
    seen.add(parent);
    const group = byId.get(parent);
    if (!group) break;
    if (isCollapsed(group)) shown = group.id;
    parent = group.payload.groupId;
  }
  return shown;
}

/** Where an edge is drawn: an end hidden in a collapsed group attaches to that group; null when both ends fold into one. */
export function edgeEnds(source: CanvasDoc | Nodes, edge: Pick<CanvasEdge, 'source' | 'target'>): { source: string; target: string } | null {
  const from = shownAs(source, edge.source);
  const to = shownAs(source, edge.target);
  return from === to ? null : { source: from, target: to };
}

/** Rectangles a drag may snap to: everything not moving and not hidden in a collapsed group. */
export function snapTargets(source: CanvasDoc | Nodes, moving: ReadonlySet<string>): CanvasNode[] {
  const nodes = nodesOf(source);
  const hidden = hiddenMemberIds(nodes);
  return nodes.filter(node => !moving.has(node.id) && !hidden.has(node.id));
}

function patchGroup(doc: CanvasDoc, id: string, update: (group: CanvasNode) => CanvasNode): CanvasDoc {
  let changed = false;
  const nodes = doc.nodes.map(node => {
    if (node.id !== id || node.kind !== 'group') return node;
    const next = update(node);
    changed = next !== node;
    return next;
  });
  return changed ? { ...doc, nodes } : doc;
}

/** Fold a group to a small card; its full size is kept to unfold to. */
export function collapseGroup(doc: CanvasDoc, groupId: string): CanvasDoc {
  return patchGroup(doc, groupId, group => {
    if (group.payload.collapsed) return group;
    return {
      ...group, width: COLLAPSED_WIDTH, height: COLLAPSED_HEIGHT,
      payload: { ...group.payload, collapsed: true, expandedSize: { width: group.width, height: group.height } },
    };
  });
}

export function expandGroup(doc: CanvasDoc, groupId: string): CanvasDoc {
  return patchGroup(doc, groupId, group => {
    if (!group.payload.collapsed) return group;
    const size = group.payload.expandedSize as { width?: number; height?: number } | undefined;
    const payload: NodePayload = { ...group.payload, collapsed: false };
    delete payload.expandedSize;
    return { ...group, width: size?.width ?? group.width, height: size?.height ?? group.height, payload };
  });
}

export function toggleGroupCollapsed(doc: CanvasDoc, groupId: string): CanvasDoc {
  const group = doc.nodes.find(node => node.id === groupId);
  return isCollapsed(group) ? expandGroup(doc, groupId) : collapseGroup(doc, groupId);
}

function memberBox(nodes: Nodes, groupId: string): Rect | null {
  return boundsOf(nodes.filter(node => node.payload.groupId === groupId && node.id !== groupId));
}

function frameAround(box: Rect, padding: number, titleBar: number): Rect {
  return { x: box.x - padding, y: box.y - titleBar - padding, width: box.width + padding * 2, height: box.height + titleBar + padding * 2 };
}

/** Wrap a group snugly around its direct members (title bar above them). A collapsed or empty group is left as is. */
export function fitGroupToMembers(doc: CanvasDoc, groupId: string, padding = FRAME_PADDING, titleBar = FRAME_HEADER): CanvasDoc {
  const box = memberBox(doc.nodes, groupId);
  if (!box) return doc;
  const frame = frameAround(box, padding, titleBar);
  return patchGroup(doc, groupId, group => (group.payload.collapsed ? group : { ...group, ...frame }));
}

/** Grow (never shrink) a group so its members fit, then its parent so the group fits. */
function growToFit(doc: CanvasDoc, groupId: string): CanvasDoc {
  let next = doc;
  const seen = new Set<string>();
  let id: string | undefined = groupId;
  while (id && !seen.has(id)) {
    seen.add(id);
    const group = next.nodes.find(node => node.id === id);
    if (!isGroup(group) || group.payload.collapsed) break;
    const box = memberBox(next.nodes, group.id);
    if (box) {
      const wanted = boundsOf([group, frameAround(box, FRAME_PADDING, FRAME_HEADER)])!;
      if (wanted.x !== group.x || wanted.y !== group.y || wanted.width !== group.width || wanted.height !== group.height) {
        next = patchGroup(next, group.id, current => ({ ...current, ...wanted }));
      }
    }
    id = group.payload.groupId;
  }
  return next;
}

/** Groups draw first so a frame stays behind what it holds; an outer frame before the one nested in it. */
export function drawingOrder(nodes: Nodes): CanvasNode[] {
  const depth = new Map(nodes.filter(isGroup).map(node => [node.id, groupDepth(nodes, node.id)]));
  const groups = nodes.filter(isGroup).map((node, index) => ({ node, index })).sort((a, b) => depth.get(a.node.id)! - depth.get(b.node.id)! || a.index - b.index);
  return [...groups.map(item => item.node), ...nodes.filter(node => !isGroup(node))];
}

function bodyContains(group: CanvasNode, x: number, y: number) {
  return x >= group.x && x <= group.x + group.width && y >= group.y + FRAME_HEADER && y <= group.y + group.height;
}

function centre(node: Rect) {
  return { x: node.x + node.width / 2, y: node.y + node.height / 2 };
}

function mayHold(nodes: Nodes, group: CanvasNode, unit: CanvasNode) {
  if (group.id === unit.id || group.payload.collapsed) return false;
  return unit.kind === 'group' ? canNest(nodes, unit.id, group.id) : true;
}

/**
 * The group a drop lands in: the innermost, topmost open group whose body (below its title bar) holds the
 * pointer when one is given, and the centre of every dragged node that may join it.
 */
export function dropTarget(doc: CanvasDoc, draggedIds: ReadonlySet<string>, point?: { x: number; y: number } | null): string | null {
  const units = layoutUnits(doc.nodes, draggedIds);
  if (!units.length) return null;
  const carried = carriedIds(doc.nodes, draggedIds);
  const ordered = drawingOrder(doc.nodes).filter(isGroup).reverse();
  const target = ordered.find(group => {
    if (carried.has(group.id) || group.payload.collapsed) return false;
    if (point && !bodyContains(group, point.x, point.y)) return false;
    return units.every(unit => {
      const at = centre(unit);
      return mayHold(doc.nodes, group, unit) && bodyContains(group, at.x, at.y);
    });
  });
  return target?.id ?? null;
}

/**
 * Commit a drop into a group. Dragged nodes whose centres lie in the target's body join it and the target
 * grows to hold them. Without a target, a node whose centre left its group's frame leaves that group.
 */
export function dropIntoGroup(doc: CanvasDoc, draggedIds: ReadonlySet<string>, point?: { x: number; y: number } | null): CanvasDoc {
  const units = layoutUnits(doc.nodes, draggedIds);
  if (!units.length) return doc;
  const targetId = dropTarget(doc, draggedIds, point);
  const byId = new Map(doc.nodes.map(node => [node.id, node]));
  const target = targetId ? byId.get(targetId) : undefined;
  const changes = new Map<string, string | undefined>();
  for (const unit of units) {
    const at = centre(unit);
    if (target && mayHold(doc.nodes, target, unit) && bodyContains(target, at.x, at.y)) {
      if (unit.payload.groupId !== target.id) changes.set(unit.id, target.id);
      continue;
    }
    const parent = unit.payload.groupId ? byId.get(unit.payload.groupId) : undefined;
    if (!parent) continue;
    const inside = at.x >= parent.x && at.x <= parent.x + parent.width && at.y >= parent.y && at.y <= parent.y + parent.height;
    if (inside) continue;
    // Leaving a nested group lands it in the outer group when its centre is still there.
    const outer = parent.payload.groupId ? byId.get(parent.payload.groupId) : undefined;
    changes.set(unit.id, outer && mayHold(doc.nodes, outer, unit) && bodyContains(outer, at.x, at.y) ? outer.id : undefined);
  }
  if (!changes.size) return doc;
  const nodes = doc.nodes.map(node => {
    if (!changes.has(node.id)) return node;
    const payload = { ...node.payload };
    const home = changes.get(node.id);
    if (home) payload.groupId = home;
    else delete payload.groupId;
    return { ...node, payload };
  });
  let next: CanvasDoc = { ...doc, nodes: drawingOrder(nodes) };
  for (const home of new Set(changes.values())) if (home) next = growToFit(next, home);
  return next;
}

/**
 * groupNodes that may also wrap groups (one level deep). Members are the selected nodes not already riding in a
 * selected group; when they all sit in one top-level group the new group is nested in it. Null when fewer than
 * two members, or when the result would nest deeper than one level.
 */
export function groupNodes2(doc: CanvasDoc, ids: ReadonlySet<string>, label: string): { doc: CanvasDoc; groupId: string } | null {
  const units = layoutUnits(doc.nodes, ids);
  const box = boundsOf(units);
  if (!box || units.length < 2) return null;
  const parents = new Set(units.map(unit => unit.payload.groupId));
  const shared = parents.size === 1 ? [...parents][0] : undefined;
  const wrapsGroups = units.some(unit => unit.kind === 'group');
  if (wrapsGroups && (shared || units.some(unit => unit.kind === 'group' && containsGroups(doc.nodes, unit.id)))) return null;
  if (shared && (groupDepth(doc.nodes, shared) + 1 > MAX_GROUP_DEPTH || isCollapsed(doc.nodes.find(node => node.id === shared)))) return null;
  const frame = frameAround(box, FRAME_PADDING, FRAME_HEADER);
  const group: CanvasNode = { ...newNode('group', frame.x, frame.y, shared ? { label, groupId: shared } : { label }), width: frame.width, height: frame.height };
  const members = new Set(units.map(unit => unit.id));
  const nodes = doc.nodes.map(node => (members.has(node.id) ? { ...node, payload: { ...node.payload, groupId: group.id } } : node));
  let next: CanvasDoc = { ...doc, nodes: drawingOrder([group, ...nodes]) };
  if (shared) next = growToFit(next, shared);
  return { doc: next, groupId: group.id };
}
