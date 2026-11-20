import { apiRequest } from '../../api/client';

export type ChapterList = 'characters' | 'scenes' | 'props';
export type ChapterAssetStatus = 'pending' | 'confirmed' | 'dismissed';

export interface ChapterRow {
  id: string;
  title: string;
  chars: number;
  extracted_at: string | null;
  counts: Record<ChapterList, number> | null;
  /** The chapter's text changed since it was last extracted. */
  changed: boolean;
}

export interface ChapterAssetItem {
  id: string;
  list: ChapterList;
  label: string;
  name: string;
  aliases: string[];
  description: string;
  chapters: string[];
  status: ChapterAssetStatus;
  /** The project already uses this name. */
  known: boolean;
  element_id?: string;
}

export interface ChapterAssetsView {
  chapters: ChapterRow[];
  items: ChapterAssetItem[];
  lists: { id: ChapterList; label: string }[];
  added?: Record<ChapterList, number>;
}

const base = (taskId: string) => `/api/drama/${encodeURIComponent(taskId)}/chapter-assets`;

export const readChapterAssets = (taskId: string) => apiRequest<ChapterAssetsView>(base(taskId));

export const extractChapter = (taskId: string, chapterId: string) => apiRequest<ChapterAssetsView>(
  `${base(taskId)}/extract`, { method: 'POST', body: JSON.stringify({ chapter_id: chapterId }) },
);

export const settleChapterAsset = (taskId: string, itemId: string, action: 'confirm' | 'dismiss' | 'restore') => apiRequest<ChapterAssetsView>(
  `${base(taskId)}/items/${encodeURIComponent(itemId)}`, { method: 'POST', body: JSON.stringify({ action }) },
);
