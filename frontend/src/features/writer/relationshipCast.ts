import type { WriterRelationship, WriterRole } from './types';

/** How many people the relationship field draws; the rest are named under it. */
export const MAX_GRAPH_NODES = 12;

/** A pairing counted from shared scenes (同场互动 · N 场) or left unnamed: not a relation, never shown as one. */
export function isUnnamedPairing(edge: WriterRelationship) {
  const relation = String(edge.relation || '').trim();
  return !relation || /同场|共同出场|共现|剧情关联|有关联/.test(relation);
}

/** The relations worth drawing: both ends named, two different people, and a real relation between them. */
export function namedRelationships(relationships: WriterRelationship[]) {
  return relationships.filter(edge => edge.from && edge.to && edge.from !== edge.to && !isUnnamedPairing(edge));
}

export function isBidirectional(edge: WriterRelationship) {
  return edge.bidirectional === true || /^同场互动(?:\s|·|$)/.test(String(edge.relation || ''));
}

function collectNames(roles: WriterRole[], relationships: WriterRelationship[], declaredLead?: string) {
  const names: string[] = [];
  const seen = new Set<string>();
  const add = (name?: string) => {
    if (!name || seen.has(name) || names.length >= 500) return;
    seen.add(name);
    names.push(name);
  };
  add(declaredLead);
  for (const edge of relationships) {
    add(edge.from);
    add(edge.to);
    if (names.length >= 500) break;
  }
  for (const role of roles) {
    add(role.name);
    if (names.length >= 500) break;
  }
  return names;
}

/** Who sits in the picture: the lead in the middle, the best-connected others around it, the rest named below. */
export function graphCast(roles: WriterRole[], relationships: WriterRelationship[]) {
  const declaredLead = roles.find(role => role.name && /主角|女主|男主/.test(role.position || ''))?.name;
  const allNames = collectNames(roles, relationships, declaredLead);
  const valid = relationships.filter(edge => edge.from && edge.to && edge.from !== edge.to);
  const degrees = new Map<string, number>();
  valid.forEach(edge => {
    degrees.set(String(edge.from), (degrees.get(String(edge.from)) || 0) + 1);
    degrees.set(String(edge.to), (degrees.get(String(edge.to)) || 0) + 1);
  });
  const degree = (name: string) => degrees.get(name) || 0;
  const lead = declaredLead || [...allNames].sort((a, b) => degree(b) - degree(a))[0];
  const order = new Map(allNames.map((name, index) => [name, index]));
  const others = allNames
    .filter(name => name !== lead)
    .sort((a, b) => degree(b) - degree(a) || Number(order.get(a)) - Number(order.get(b)));
  const names = lead ? [lead, ...others].slice(0, MAX_GRAPH_NODES) : [];
  const shown = new Set(names);
  return { allNames, lead, names, hidden: allNames.filter(name => !shown.has(name)), valid };
}
