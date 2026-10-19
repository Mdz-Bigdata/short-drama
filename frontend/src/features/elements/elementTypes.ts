export type ElementKind = 'actor' | 'scene' | 'prop' | 'costume' | 'effect' | 'product';

/** A derived look of a character (backend app/core/character_variants.py), kept on the actor's metadata. */
export interface ElementVariant {
  of: string;
  label: string;
  triggers: string[];
  episodes: [number, number] | null;
}

export function variantOf(item: { metadata?: Record<string, unknown> }): ElementVariant | null {
  const raw = item.metadata?.variant as Partial<ElementVariant> | undefined;
  return raw && typeof raw.of === 'string' && raw.of.trim()
    ? { of: raw.of, label: String(raw.label ?? ''), triggers: Array.isArray(raw.triggers) ? raw.triggers.map(String) : [], episodes: Array.isArray(raw.episodes) && raw.episodes.length === 2 ? [Number(raw.episodes[0]), Number(raw.episodes[1])] : null }
    : null;
}

/** 资产库里数字演员的设定集重新生成进度（后端 metadata.regeneration）；超过 15 分钟仍在跑视为已中断。 */
export const ACTOR_REGENERATION_STALE_MS = 15 * 60 * 1000;

export function actorRegeneration(
  item: { metadata?: Record<string, unknown> },
  now: number = Date.now(),
): { running: boolean; error: string } {
  const raw = item.metadata?.regeneration as { status?: unknown; error?: unknown; started_epoch?: unknown } | undefined;
  if (!raw || typeof raw !== 'object') return { running: false, error: '' };
  const started = Number(raw.started_epoch) * 1000;
  const running = raw.status === 'running' && Number.isFinite(started) && now - started < ACTOR_REGENERATION_STALE_MS;
  const error = raw.status === 'failed' ? String(raw.error ?? '') || '重新生成失败' : '';
  return { running, error };
}

export interface ElementFile {
  id: string;
  slot: string;
  mime_type: string;
  media_kind: 'image' | 'model';
  size_bytes: number;
  sha256: string;
  url: string | null;
}

export interface ElementModelStats {
  nodes?: number;
  meshes?: number;
  vertices?: number;
  triangles?: number;
  materials?: number;
  textures?: number;
  animations?: number;
  drawCalls?: number;
}

export interface ElementModel3D {
  schemaVersion: 'element-model.v1';
  state: 'ready';
  format: 'glb';
  contentUrl: string;
  sha256: string;
  sizeBytes: number;
  stats: ElementModelStats;
  validation: {
    passed: boolean;
    warnings: string[];
  };
  unit: string;
  upAxis: string;
}

export interface ElementItem {
  id: string;
  kind: ElementKind;
  name: string;
  description: string;
  status: string;
  version: number;
  metadata: Record<string, unknown>;
  files: ElementFile[];
  model3d: ElementModel3D | null;
}

export function findPoster(item: ElementItem): ElementFile | undefined {
  // 主参考图优先(道具的主参考图就是四视图里的正面)；没有时退回第一张图。
  return item.files.find(file => file.slot === 'reference' && file.media_kind === 'image' && Boolean(file.url))
    ?? item.files.find(file => file.media_kind === 'image' && Boolean(file.url));
}

/** 拍摄道具的四视图槽位，顺序即展示顺序；与后端 core/prop_turnaround.PROP_VIEWS 一致。 */
export const PROP_VIEW_SLOTS: ReadonlyArray<readonly [slot: string, label: string]> = [
  ['prop_front', '正面'],
  ['prop_left_45', '左侧45°'],
  ['prop_right_45', '右侧45°'],
  ['prop_back', '背面'],
];

/** 一件道具的四视图，没生成的格子 file 为空。 */
export function propViews(item: ElementItem): Array<{ slot: string; label: string; file: ElementFile | undefined }> {
  return PROP_VIEW_SLOTS.map(([slot, label]) => ({
    slot,
    label,
    file: item.files.find(file => file.slot === slot && file.media_kind === 'image' && Boolean(file.url)),
  }));
}

/** The image stored for one specific five-view slot, if it has been uploaded. */
export function findViewImage(item: ElementItem, slot: string): ElementFile | undefined {
  return item.files.find(
    file => file.media_kind === 'image' && file.slot === slot && Boolean(file.url),
  );
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

export function formatMetric(value?: number): string {
  return typeof value === 'number' ? value.toLocaleString('zh-CN') : '—';
}
