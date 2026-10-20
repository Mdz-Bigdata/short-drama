import { API_BASE } from '../../api/client';

const EXTENSION_BY_TYPE: Record<string, string> = {
  'image/png': 'png',
  'image/jpeg': 'jpg',
  'image/webp': 'webp',
  'image/gif': 'gif',
};

async function saveApiFile(path: string, filenameBase: string): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}${path}`, { credentials: 'include' });
    if (!response.ok) return false;
    const blob = await response.blob();
    const extension = EXTENSION_BY_TYPE[blob.type] || 'png';
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${filenameBase}.${extension}`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    return true;
  } catch {
    return false;
  }
}

export function downloadStoryboardGrid(taskId: string, filenameBase: string): Promise<boolean> {
  return saveApiFile(
    `/api/drama/${encodeURIComponent(taskId)}/storyboard/download?target=grid`,
    filenameBase,
  );
}

export function downloadStoryboardScene(
  taskId: string,
  sceneId: string,
  filenameBase: string,
): Promise<boolean> {
  return saveApiFile(
    `/api/drama/${encodeURIComponent(taskId)}/storyboard/download?target=scene&scene=${encodeURIComponent(sceneId)}`,
    filenameBase,
  );
}

export function downloadStoryboardShot(
  taskId: string,
  shotIndex: number,
  filenameBase: string,
): Promise<boolean> {
  return saveApiFile(
    `/api/drama/${encodeURIComponent(taskId)}/storyboard/download?target=shot&shot=${shotIndex}`,
    filenameBase,
  );
}
