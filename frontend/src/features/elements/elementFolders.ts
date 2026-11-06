import { useCallback, useState } from 'react';

import { apiRequest } from '../../api/client';
import type { ElementKind } from './elementTypes';

export const UNFILED = 'unfiled';

export interface ElementFolderEntry {
  id: string;
  name: string;
  count: number;
  cover_element_id: string | null;
  cover_url: string | null;
}

export interface ElementFolderListing {
  folders: ElementFolderEntry[];
  total: number;
  unfiled: number;
}

const EMPTY: ElementFolderListing = { folders: [], total: 0, unfiled: 0 };

/** The folders and counts for one kind. A failed read leaves the library usable, just without folders. */
export function useElementFolders(kind: ElementKind, enabled: boolean) {
  const [listing, setListing] = useState<ElementFolderListing>(EMPTY);
  const reload = useCallback(async () => {
    if (!enabled) return;
    try {
      const data = await apiRequest<Partial<ElementFolderListing>>(`/api/elements/folders?kind=${kind}`);
      setListing({ folders: Array.isArray(data.folders) ? data.folders : [], total: Number(data.total) || 0, unfiled: Number(data.unfiled) || 0 });
    } catch {
      setListing(EMPTY);
    }
  }, [enabled, kind]);
  return { listing, reload };
}

export function moveElementsToFolder(elementIds: string[], folderId: string | null): Promise<unknown> {
  return apiRequest('/api/elements/folders/move', { method: 'POST', body: JSON.stringify({ element_ids: elementIds, folder_id: folderId }) });
}
