import { apiRequest } from '../../api/client';

export interface ScriptDocument {
  id: string;
  name: string;
  sizeBytes: number;
  updatedAt: string;
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

export function createScriptDocument(taskId: string, name: string, content: string) {
  return apiRequest<ScriptDocument>(base(taskId), {
    method: 'POST',
    body: JSON.stringify({ name, content }),
  });
}

export function updateScriptDocument(
  taskId: string,
  documentId: string,
  patch: { name?: string; content?: string },
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
