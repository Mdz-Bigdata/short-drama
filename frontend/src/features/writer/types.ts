export interface WriterScene {
  scene_id?: string;
  sceneId?: string;
  duration?: string;
  durationLabel?: string;
  durationSeconds?: number;
  startSeconds?: number;
  episodeIndex?: number;
  sceneIndex?: number;
  keyEventIndex?: number | null;
  content?: string;
  characters?: string[];
}

export interface WriterTimelineEvent {
  eventId?: string;
  order?: number;
  phase?: string;
  title?: string;
  desc?: string;
  points?: string[];
  sceneId?: string | null;
  startSeconds?: number;
}

export interface WriterRelationship {
  from?: string;
  to?: string;
  relation?: string;
  bidirectional?: boolean;
}

export interface WriterRole {
  name?: string;
  position?: string;
}

export interface WriterBreakdown {
  overview?: {
    synopsis?: string;
    genre?: string;
    theme?: string;
    world_setting?: string;
    worldSetting?: string;
  };
  scenes?: WriterScene[];
  timeline?: WriterTimelineEvent[];
  relationships?: WriterRelationship[];
  roles?: WriterRole[];
}

export interface WriterEpisode {
  index: number;
  title: string;
  status: 'idle' | 'running' | 'completed' | 'failed';
  videoUrl?: string | null;
  sceneCount?: number;
  durationSeconds?: number;
}

export interface WriterDashboardStats {
  totalEpisodes: number;
  /** Episodes actually present in the screenplay text; short of totalEpisodes means truncated. */
  scriptedEpisodes?: number;
  sceneCount: number;
  characterCount: number;
  mainEventCount: number;
  relationshipCount: number;
  totalDurationSeconds: number;
  tone: string;
}

export interface WriterDashboardResponse {
  schemaVersion: 'writer-dashboard.v1';
  taskId: string;
  sourceHash: string;
  title: string;
  state: 'WAITING' | 'INCOMPLETE' | 'READY';
  overview: NonNullable<WriterBreakdown['overview']>;
  stats: WriterDashboardStats;
  scenes: WriterScene[];
  timeline: WriterTimelineEvent[];
  roles: WriterRole[];
  relationships: WriterRelationship[];
  /** True while the graph is only same-scene co-occurrence, not analysed relations. */
  relationshipsInferred?: boolean;
  episodes: WriterEpisode[];
  script: string;
  scriptFileName?: string | null;
}

export function normalizeWriterBreakdown(value: unknown): WriterBreakdown {
  if (!value || typeof value !== 'object') return {};
  const raw = value as WriterBreakdown;
  return {
    overview: raw.overview && typeof raw.overview === 'object' ? raw.overview : undefined,
    scenes: Array.isArray(raw.scenes) ? raw.scenes : [],
    timeline: Array.isArray(raw.timeline) ? raw.timeline : [],
    relationships: Array.isArray(raw.relationships) ? raw.relationships : [],
    roles: Array.isArray(raw.roles) ? raw.roles : [],
  };
}

export function sceneEpisode(scene: WriterScene) {
  if (scene.episodeIndex && scene.episodeIndex > 0) return scene.episodeIndex;
  const match = String(scene.scene_id || '').match(/E(\d+)/i);
  return match ? Number(match[1]) : 1;
}

export function relationshipsFromScenes(scenes: WriterScene[]): WriterRelationship[] {
  const maxCharacters = 100;
  const maxCharactersPerScene = 32;
  const maxRelationships = 500;
  const characterOrder = new Map<string, number>();
  const pairs = new Map<string, { from: string; to: string; count: number }>();
  scenes.forEach(scene => {
    const names: string[] = [];
    for (const name of Array.from(new Set((scene.characters || []).map(value => String(value).trim()).filter(Boolean)))) {
      if (names.length >= maxCharactersPerScene) break;
      if (!characterOrder.has(name)) {
        if (characterOrder.size >= maxCharacters) continue;
        characterOrder.set(name, characterOrder.size);
      }
      names.push(name);
    }
    for (let left = 0; left < names.length; left += 1) {
      for (let right = left + 1; right < names.length; right += 1) {
        const sorted = [names[left], names[right]].sort((a, b) => a.localeCompare(b, 'zh-CN'));
        const key = sorted.join('\u0000');
        const current = pairs.get(key);
        if (current) current.count += 1;
        else if (pairs.size < maxRelationships) pairs.set(key, { from: sorted[0], to: sorted[1], count: 1 });
      }
    }
  });
  return Array.from(pairs.values()).map(pair => ({
    from: pair.from,
    to: pair.to,
    relation: `同场互动 · ${pair.count} 场`,
    bidirectional: true,
  }));
}
