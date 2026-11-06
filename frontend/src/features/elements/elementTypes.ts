export type ElementKind = 'actor' | 'scene' | 'prop' | 'costume' | 'effect' | 'product' | 'extra' | 'vehicle' | 'stunt' | 'set_dressing' | 'makeup';

/** A derived look of a character (backend app/core/character_variants.py), kept on the actor's metadata. */
export interface ElementVariant {
  of: string;
  label: string;
  triggers: string[];
  episodes: [number, number] | null;
  /** 分散的几段集数；只有一段时看 episodes。 */
  spans?: Array<[number, number]>;
  /** 'costume'：这是角色化好妆、穿好戏服的定妆图（表演妆造）。 */
  source?: string;
  /** 从这一集的这一场开始才穿：[集, 场]。 */
  starts?: [number, number];
  /** 剧本已不需要这张定妆图：图留着，但不再穿，也不再补画。 */
  retired?: boolean;
}

export function variantOf(item: { metadata?: Record<string, unknown> }): ElementVariant | null {
  const raw = item.metadata?.variant as Partial<ElementVariant> | undefined;
  return raw && typeof raw.of === 'string' && raw.of.trim()
    ? {
      of: raw.of,
      label: String(raw.label ?? ''),
      triggers: Array.isArray(raw.triggers) ? raw.triggers.map(String) : [],
      episodes: Array.isArray(raw.episodes) && raw.episodes.length === 2 ? [Number(raw.episodes[0]), Number(raw.episodes[1])] : null,
      ...(Array.isArray(raw.spans) ? { spans: raw.spans.map(span => [Number(span[0]), Number(span[1])] as [number, number]) } : {}),
      ...(raw.source ? { source: String(raw.source) } : {}),
      ...(raw.retired ? { retired: true } : {}),
      ...(Array.isArray(raw.starts) && raw.starts.length === 2 ? { starts: [Number(raw.starts[0]), Number(raw.starts[1])] as [number, number] } : {}),
    }
    : null;
}

export function isLook(item: { metadata?: Record<string, unknown> }): boolean {
  return variantOf(item)?.source === 'costume';
}

/** 定妆图画完后妆效核对没过（后端 metadata.look_check，已按问题重画过一次）：哪里不对；过了或没核对返回空。 */
export function lookCheckProblems(item: { metadata?: Record<string, unknown> }): string[] {
  const check = item.metadata?.look_check;
  if (!check || typeof check !== 'object' || (check as { passed?: unknown }).passed !== false) return [];
  const problems = (check as { problems?: unknown }).problems;
  return Array.isArray(problems) ? problems.map(String).filter(Boolean) : [];
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
  /** 道具的最长边：人填的、描述里写的，或按物件类别估的。 */
  prop_scale?: { longest_cm: number; manual_cm: number | null; source: 'manual' | 'description' | 'estimate' };
  /** Set on listings; an element outside any folder is simply unfiled. */
  folder_id?: string | null;
}

export function findPoster(item: ElementItem): ElementFile | undefined {
  // 主参考图优先(道具的主参考图就是四视图里的正面，场地的是主场景全景)；没有时退回第一张图。
  return item.files.find(file => file.slot === 'reference' && file.media_kind === 'image' && Boolean(file.url))
    ?? item.files.find(file => file.media_kind === 'image' && Boolean(file.url));
}

/** 拍摄道具可能有的视图，顺序即展示顺序；与后端 core/prop_turnaround 一致。画哪几个看物件本身。 */
export const PROP_VIEW_SLOTS: ReadonlyArray<readonly [slot: string, label: string]> = [
  ['prop_board', '比例总览'],
  ['prop_front', '正面'],
  ['prop_left_45', '左侧45°'],
  ['prop_right_45', '右侧45°'],
  ['prop_side', '侧面'],
  ['prop_back', '背面'],
  ['prop_top', '顶面'],
  ['prop_detail', '关键细节'],
  ['prop_in_use', '比例参照'],
];

/** 拍摄场地的四视角(都是空景)，顺序即展示顺序；与后端 core/scene_turnaround.SCENE_VIEWS 一致。全景同时是主参考图。 */
export const SCENE_VIEW_SLOTS: ReadonlyArray<readonly [slot: string, label: string]> = [
  ['scene_main', '主场景全景'],
  ['scene_45', '45°斜角'],
  ['scene_depth', '纵深视角'],
  ['scene_detail', '关键细节'],
];

export type BoardView = { slot: string; label: string; file: ElementFile | undefined };

function boardViews(item: ElementItem, slots: typeof PROP_VIEW_SLOTS): BoardView[] {
  return slots.map(([slot, label]) => ({
    slot,
    label,
    file: item.files.find(file => file.slot === slot && file.media_kind === 'image' && Boolean(file.url)),
  }));
}

/** 一件道具已有的视图；还没生成时给一个总览占位。 */
export function propViews(item: ElementItem): BoardView[] {
  const views = boardViews(item, PROP_VIEW_SLOTS).filter(view => view.file);
  return views.length ? views : boardViews(item, PROP_VIEW_SLOTS.slice(0, 1));
}

/** 一处场地的四视角，没生成的格子 file 为空。 */
export function sceneViews(item: ElementItem): BoardView[] {
  return boardViews(item, SCENE_VIEW_SLOTS);
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
