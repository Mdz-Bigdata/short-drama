import { apiRequest } from '../../api/client';

/** What a library file is to the project: read by people only, one file of the whole source, or one episode's own text. */
export type ScriptDocumentRole = 'reference' | 'source' | 'episode';
/** How a source file is read: adapted from prose, or extracted verbatim from a finished screenplay. */
export type ScriptSourceKind = 'novel' | 'screenplay';

export const DOCUMENT_ROLE_LABELS: Record<ScriptDocumentRole, string> = {
  source: '整本源文',
  episode: '逐集原文',
  reference: '参考资料',
};

export const SOURCE_KIND_LABELS: Record<ScriptSourceKind, string> = {
  novel: '小说（改编）',
  screenplay: '成品剧本（逐字提取）',
};

export interface ScriptDocument {
  id: string;
  name: string;
  sizeBytes: number;
  updatedAt: string;
  role: ScriptDocumentRole;
  sourceKind?: ScriptSourceKind | null;
  order?: number | null;
  /** Own-source files: their place in broadcast order, and the episode number the ledger gave them once stage 2 ran. */
  position?: number | null;
  episode?: number | null;
}

export interface ScriptDocumentDetail extends ScriptDocument {
  content: string;
}

interface ScriptLibraryResponse {
  documents: ScriptDocument[];
  total: number;
}

const base = (taskId: string) => `/api/drama/${encodeURIComponent(taskId)}/script-documents`;

export function listScriptDocuments(taskId: string) {
  return apiRequest<ScriptLibraryResponse>(base(taskId));
}

export function readScriptDocument(taskId: string, documentId: string) {
  return apiRequest<ScriptDocumentDetail>(`${base(taskId)}/${encodeURIComponent(documentId)}`);
}

export function createScriptDocument(
  taskId: string,
  name: string,
  content: string,
  options: { role?: ScriptDocumentRole; sourceKind?: ScriptSourceKind } = {},
) {
  return apiRequest<ScriptDocument>(base(taskId), {
    method: 'POST',
    body: JSON.stringify({ name, content, role: options.role, sourceKind: options.sourceKind }),
  });
}

export function updateScriptDocument(
  taskId: string,
  documentId: string,
  patch: { name?: string; content?: string; role?: ScriptDocumentRole; sourceKind?: ScriptSourceKind | null; order?: number },
) {
  return apiRequest<ScriptDocumentDetail>(`${base(taskId)}/${encodeURIComponent(documentId)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
}

export function deleteScriptDocument(taskId: string, documentId: string) {
  return apiRequest<{ deleted: boolean; id: string }>(
    `${base(taskId)}/${encodeURIComponent(documentId)}`,
    { method: 'DELETE' },
  );
}

export function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size <= 0) return '0 B';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

/** The library's contribution to stage 2, in one line. */
export function describeSources(documents: ScriptDocument[]): string {
  const whole = documents.filter(document => document.role === 'source').length;
  const own = documents.filter(document => document.role === 'episode').length;
  if (!whole && !own) return '尚未指定源文：导入后把整本小说或剧本标为「整本源文」，逐集的剧情标为「逐集原文」。';
  const parts = [];
  if (whole) parts.push(`整本源文 ${whole} 份（按顺序拼接后切分成集）`);
  if (own) parts.push(`逐集原文 ${own} 集（排在切出的集之后）`);
  return parts.join(' · ');
}
