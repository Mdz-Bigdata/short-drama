import { RefreshCcw, ServerCrash, WandSparkles } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { API_BASE, apiRequest } from '../../api/client';
import { CharacterDesignerPage } from './CharacterDesignerPage';
import {
  buildLegacyCharacterDashboard,
  normalizeCharacterDashboard,
  sanitizeCharacterMediaUrl,
  type CharacterDashboardResponse,
} from './types';

type LoadingState = 'loading' | 'ready' | 'error';

function mediaUrl(value: string | null): string | null {
  const safeValue = sanitizeCharacterMediaUrl(value);
  if (!safeValue) return null;
  return safeValue.startsWith('/media/')
    ? sanitizeCharacterMediaUrl(`${API_BASE}${safeValue}`)
    : safeValue;
}

function resolveDashboardMedia(dashboard: CharacterDashboardResponse): CharacterDashboardResponse {
  return {
    ...dashboard,
    characters: dashboard.characters.map(character => ({
      ...character,
      sheetUrl: mediaUrl(character.sheetUrl),
      views: character.views.map(view => ({ ...view, imageUrl: mediaUrl(view.imageUrl) })),
    })),
  };
}

export function CharacterDesignerPageContainer({
  taskId,
  refreshKey,
  title,
  fallbackCharacters,
  fallbackSheets,
  fallbackDna,
  fallbackRaw,
  onRefresh,
  onRegenerate,
  onContinue,
}: {
  taskId: string;
  refreshKey?: string;
  title?: string;
  fallbackCharacters?: unknown;
  fallbackSheets?: unknown;
  fallbackDna?: unknown;
  fallbackRaw?: unknown;
  onRefresh: () => void;
  onRegenerate: () => void;
  onContinue: () => void;
}) {
  const fallback = useMemo(() => resolveDashboardMedia(buildLegacyCharacterDashboard({
    title,
    characters: fallbackCharacters,
    sheets: fallbackSheets,
    dna: fallbackDna,
    raw: fallbackRaw,
  })), [fallbackCharacters, fallbackDna, fallbackRaw, fallbackSheets, title]);
  const [dashboard, setDashboard] = useState<CharacterDashboardResponse | null>(null);
  const [loadingState, setLoadingState] = useState<LoadingState>('loading');
  const [syncMessage, setSyncMessage] = useState('');
  const [requestVersion, setRequestVersion] = useState(0);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    if (!taskId) return;
    const controller = new AbortController();
    void apiRequest<CharacterDashboardResponse>(`/api/drama/${encodeURIComponent(taskId)}/character-dashboard`, {
      signal: controller.signal,
    }).then(response => {
      setDashboard(resolveDashboardMedia(normalizeCharacterDashboard(response)));
      setLoadingState('ready');
      setSyncMessage('');
    }).catch(error => {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      setDashboard(null);
      setLoadingState('error');
      setSyncMessage(fallback.characters.length
        ? '角色看板服务暂不可用，当前显示任务内嵌资产；旧版整板图仅作参考。'
        : '角色看板服务暂不可用，请检查后端服务后重试。');
    });
    return () => controller.abort();
  }, [fallback.characters.length, refreshKey, requestVersion, taskId]);

  const refresh = () => {
    onRefresh();
    setLoadingState('loading');
    setRequestVersion(version => version + 1);
  };

  const exportDashboard = async () => {
    setExporting(true);
    try {
      const response = await fetch(`${API_BASE}/api/drama/${encodeURIComponent(taskId)}/character-dashboard/export`, {
        credentials: 'include',
      });
      if (!response.ok) throw new Error(`character dashboard export failed: ${response.status}`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${dashboard?.title || title || 'character-designer'}-dashboard.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      setSyncMessage('角色看板 JSON 已导出。');
    } catch {
      setSyncMessage('角色看板导出失败，请稍后重试。');
    } finally {
      setExporting(false);
    }
  };

  const visibleDashboard = dashboard || fallback;
  const hasFallback = fallback.characters.length > 0;

  if (loadingState === 'loading' && !dashboard && !hasFallback) {
    return (
      <section className="character-designer-loader" aria-busy="true" aria-label="正在加载角色设计看板">
        <div className="character-designer-loader__header" />
        <div className="character-designer-loader__stats" />
        <div className="character-designer-loader__workspace">
          <span /><strong /><span />
        </div>
      </section>
    );
  }

  if ((!taskId || loadingState === 'error') && !dashboard && !hasFallback) {
    return (
      <section className="character-designer-error" role="alert">
        <ServerCrash size={42} aria-hidden="true" />
        <h1>角色看板连接失败</h1>
        <p>{!taskId ? '缺少任务 ID，无法读取角色设计看板。' : syncMessage}</p>
        <div>
          <button type="button" onClick={refresh}><RefreshCcw size={16} aria-hidden="true" /> 重新连接</button>
          <button type="button" onClick={onRegenerate}><WandSparkles size={16} aria-hidden="true" /> 重新生成角色</button>
        </div>
      </section>
    );
  }

  return (
    <CharacterDesignerPage
      dashboard={visibleDashboard}
      syncMessage={syncMessage || (loadingState === 'loading' ? '正在同步后端角色看板…' : '')}
      refreshing={loadingState === 'loading'}
      exporting={exporting}
      onRefresh={refresh}
      onRegenerate={onRegenerate}
      onExport={() => { void exportDashboard(); }}
      onContinue={onContinue}
    />
  );
}
