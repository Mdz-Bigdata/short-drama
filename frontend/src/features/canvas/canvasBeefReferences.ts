import type { CanvasEdge, CanvasNode } from './canvasTypes';
import type { ReferenceLimits } from './canvasBeefApi';

/** The roles a picture or clip may play for a clip node, as the server reads them (studio_canvas._add_url). */
export type ReferenceRole = 'first_frame' | 'last_frame' | 'ref_image' | 'ref_video' | 'continue_from' | 'ref_audio';

export interface RoleSuggestion {
  edgeId: string;
  sourceId: string;
  from: ReferenceRole;
  to: ReferenceRole;
  reason: 'only_picture' | 'leftmost' | 'rightmost' | 'between';
}

export interface ReferenceProblem {
  code: 'too_many_images' | 'too_many_videos' | 'too_many_audios' | 'first_and_continue' | 'two_firsts' | 'two_lasts' | 'last_without_first';
  count?: number;
  limit?: number;
}

export interface ReferenceCheck {
  suggestions: RoleSuggestion[];
  problems: ReferenceProblem[];
  /** Roles as they will be once the suggestions are applied. */
  roles: Record<string, ReferenceRole>;
}

/** What a node hands on: a picture, a clip, a sound, or something a clip node does not take as a reference. */
export function producedMedium(node: CanvasNode): 'image' | 'video' | 'audio' | null {
  if (node.kind === 'image_gen') return 'image';
  if (node.kind === 'video_gen' || node.kind === 'video_compose') return 'video';
  if (node.kind === 'audio_gen') return 'audio';
  const medium = node.payload.output?.medium ?? node.payload.medium;
  return medium === 'image' || medium === 'video' || medium === 'audio' ? medium : null;
}

const DEFAULT_ROLE = { image: 'ref_image', video: 'ref_video', audio: 'ref_audio' } as const;

function roleOf(edge: CanvasEdge, medium: 'image' | 'video' | 'audio'): ReferenceRole {
  const role = edge.payload?.role;
  return typeof role === 'string' && role ? role as ReferenceRole : DEFAULT_ROLE[medium];
}

/**
 * Smart reference for a clip node: when none of its pictures was marked as the first or last frame, the
 * picture placed furthest left (then highest) becomes the first frame, and with two or more pictures the one
 * furthest right becomes the last frame; the rest stay references. A role the person set is never changed.
 * Then the reference counts are checked against the caps the server applies, and impossible combinations
 * (a first frame and a continued clip, two first frames) are named.
 */
export function checkReferences(target: CanvasNode, nodes: CanvasNode[], edges: CanvasEdge[], limits: ReferenceLimits): ReferenceCheck {
  const byId = new Map(nodes.map(node => [node.id, node]));
  const inputs = edges
    .filter(edge => edge.target === target.id && byId.has(edge.source))
    .map(edge => ({ edge, source: byId.get(edge.source)!, medium: producedMedium(byId.get(edge.source)!) }))
    .filter((item): item is { edge: CanvasEdge; source: CanvasNode; medium: 'image' | 'video' | 'audio' } => item.medium !== null);
  const roles: Record<string, ReferenceRole> = Object.fromEntries(inputs.map(item => [item.edge.id, roleOf(item.edge, item.medium)]));
  const suggestions: RoleSuggestion[] = [];

  if (target.kind === 'video_gen') {
    const pictures = inputs.filter(item => item.medium === 'image');
    const marked = pictures.some(item => item.edge.payload?.role === 'first_frame' || item.edge.payload?.role === 'last_frame');
    const continued = inputs.some(item => roles[item.edge.id] === 'continue_from');
    if (pictures.length && !marked && !continued) {
      const ordered = [...pictures].sort((a, b) => a.source.x - b.source.x || a.source.y - b.source.y);
      const suggest = (item: typeof ordered[number], to: ReferenceRole, reason: RoleSuggestion['reason']) => {
        if (roles[item.edge.id] === to) return;
        suggestions.push({ edgeId: item.edge.id, sourceId: item.source.id, from: roles[item.edge.id], to, reason });
        roles[item.edge.id] = to;
      };
      suggest(ordered[0], 'first_frame', ordered.length === 1 ? 'only_picture' : 'leftmost');
      if (ordered.length >= 2) suggest(ordered[ordered.length - 1], 'last_frame', 'rightmost');
    }
  }

  const count = (role: ReferenceRole) => Object.values(roles).filter(item => item === role).length;
  const problems: ReferenceProblem[] = [];
  const images = count('ref_image') + count('first_frame') + count('last_frame');
  if (images > limits.images) problems.push({ code: 'too_many_images', count: images, limit: limits.images });
  const videos = count('ref_video') + count('continue_from');
  if (videos > limits.videos) problems.push({ code: 'too_many_videos', count: videos, limit: limits.videos });
  if (count('ref_audio') > limits.audios) problems.push({ code: 'too_many_audios', count: count('ref_audio'), limit: limits.audios });
  if (count('first_frame') && count('continue_from')) problems.push({ code: 'first_and_continue' });
  if (count('first_frame') > 1) problems.push({ code: 'two_firsts', count: count('first_frame') });
  if (count('last_frame') > 1) problems.push({ code: 'two_lasts', count: count('last_frame') });
  if (count('last_frame') && !count('first_frame') && !count('continue_from')) problems.push({ code: 'last_without_first' });
  return { suggestions, problems, roles };
}

/** The edges with the suggested roles written into their payloads; other edges are returned unchanged. */
export function applySuggestions(edges: CanvasEdge[], suggestions: RoleSuggestion[]): CanvasEdge[] {
  const roles = new Map(suggestions.map(item => [item.edgeId, item.to]));
  return edges.map(edge => (roles.has(edge.id) ? { ...edge, payload: { ...edge.payload, role: roles.get(edge.id) } } : edge));
}
