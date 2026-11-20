import { ApiError, apiRequest, apiUrl } from '../../api/client';
import { acceptLanguage, t } from '../../i18n';

const bundlePath = (projectId: string, canvasId: string) =>
  `/api/studio/projects/${encodeURIComponent(projectId)}/canvas/bundle?canvas_id=${encodeURIComponent(canvasId)}`;

export interface BundleImportReport {
  files: number;
  failed: { name: string; reason: string }[];
  missing: number;
}

/** A downloaded bundle: the zip, and the name the server gave it. */
export interface BundleDownload {
  blob: Blob;
  fileName: string;
}

function fileNameOf(disposition: string | null, fallback: string) {
  const encoded = disposition?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded);
    } catch {
      // A malformed name falls back to the plain one.
    }
  }
  return disposition?.match(/filename="([^"]+)"/i)?.[1] ?? fallback;
}

/**
 * The board with its media as one zip (`backend/app/service/canvas_bundle.py`). A plain fetch rather than
 * `apiRequest`, which reads JSON; the error detail is read the same way it would be.
 */
export async function downloadBundle(projectId: string, canvasId: string, fallbackName: string): Promise<BundleDownload> {
  const response = await fetch(apiUrl(bundlePath(projectId, canvasId)), { credentials: 'include', headers: { 'Accept-Language': acceptLanguage() } });
  if (!response.ok) {
    let detail = t('打包失败');
    try {
      const data = await response.json() as { detail?: string };
      if (data.detail) detail = data.detail;
    } catch {
      // Keep the generic message when the answer is not JSON.
    }
    throw new ApiError(detail, response.status);
  }
  return { blob: await response.blob(), fileName: fileNameOf(response.headers.get('Content-Disposition'), fallbackName) };
}

/** Sends a bundle; every file in it is checked and stored again, and the canvas comes back as a plain export to merge. */
export function importBundle(projectId: string, canvasId: string, file: File) {
  const form = new FormData();
  form.append('file', file, file.name);
  return apiRequest<{ manifest: unknown; report: BundleImportReport }>(bundlePath(projectId, canvasId), { method: 'POST', body: form });
}

/** Whether a picked file is a bundle (zip) rather than a plain canvas JSON. */
export function isBundleFile(file: File) {
  return /\.zip$/i.test(file.name) || file.type === 'application/zip' || file.type === 'application/x-zip-compressed';
}

/** Saves a blob under a name, the way the plain export does. */
export function saveBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
