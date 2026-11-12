import { useCallback, useEffect, useRef, useState } from 'react';

import { apiRequest, apiUrl } from '../../api/client';
import { findPoster, type ElementItem } from '../elements/elementTypes';

/** 数字演员页角色库里的群演：本项目的 extra 类资产清单与缩略图。 */

interface ElementPage {
  items: ElementItem[];
  total: number;
}

const PAGE_SIZE = 100;

/** 本项目的全部群演(按页取完)；``reload`` 返回取到的清单。 */
export function useProjectExtras(taskId?: string) {
  const [extras, setExtras] = useState<ElementItem[]>([]);
  const sequence = useRef(0);

  const reload = useCallback(async (): Promise<ElementItem[] | null> => {
    const mine = ++sequence.current;
    const scope = taskId ? `&task_id=${encodeURIComponent(taskId)}` : '';
    const items: ElementItem[] = [];
    const seen = new Set<string>();
    try {
      for (let page = 1; ; page += 1) {
        const data = await apiRequest<ElementPage>(`/api/elements?kind=extra&page=${page}&page_size=${PAGE_SIZE}${scope}`);
        if (mine !== sequence.current) return null;
        const fresh = data.items.filter(item => !seen.has(item.id));
        fresh.forEach(item => seen.add(item.id));
        items.push(...fresh);
        if (!fresh.length || items.length >= data.total) break;
      }
    } catch {
      return null;
    }
    setExtras(items);
    return items;
  }, [taskId]);

  useEffect(() => {
    const handle = window.setTimeout(() => { void reload(); }, 0);
    return () => {
      window.clearTimeout(handle);
      sequence.current += 1;
    };
  }, [reload]);

  return { extras, reload };
}

export function extraThumbnail(item: ElementItem): string {
  const poster = findPoster(item);
  return poster?.url ? apiUrl(poster.url) : '';
}
