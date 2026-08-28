export type ElementKind = 'actor' | 'scene' | 'prop' | 'costume' | 'effect';

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
  return item.files.find(file => file.media_kind === 'image' && Boolean(file.url));
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
