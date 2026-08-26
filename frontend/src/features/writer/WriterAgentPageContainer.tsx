import { useEffect, useState } from 'react';

import { API_BASE, apiRequest } from '../../api/client';
import { normalizeScriptTitle } from '../workbench/scriptTitle';
import { WriterAgentPage } from './WriterAgentPage';
import type { WriterDashboardResponse, WriterEpisode } from './types';

export function WriterAgentPageContainer({
  taskId,
  refreshKey,
  displayTitle,
  title,
  fallbackBreakdown,
  fallbackScript,
  requestedEpisodeCount,
  episodes,
  episodesBusy,
  onPlanEpisodes,
  onProduceEpisode,
}: {
  taskId: string;
  refreshKey?: string;
  displayTitle?: string;
  title?: string;
  fallbackBreakdown?: unknown;
  fallbackScript?: unknown;
  requestedEpisodeCount?: number;
  episodes: WriterEpisode[];
  episodesBusy: boolean;
  onPlanEpisodes: () => void;
  onProduceEpisode: (index: number) => void;
}) {
  const [dashboardState, setDashboardState] = useState<{ taskId: string; data: WriterDashboardResponse } | null>(null);
  const [syncError, setSyncError] = useState('');
  const dashboard = dashboardState?.taskId === taskId ? dashboardState.data : null;
  const resolvedTitle = normalizeScriptTitle(displayTitle)
    || normalizeScriptTitle(dashboard?.title)
    || normalizeScriptTitle(title)
    || '未命名剧本';

  useEffect(() => {
    if (!taskId) return;
    const controller = new AbortController();
    void apiRequest<WriterDashboardResponse>(`/api/drama/${encodeURIComponent(taskId)}/writer-dashboard`, {
      signal: controller.signal,
    }).then(data => {
      setDashboardState({ taskId, data });
      setSyncError('');
    }).catch(error => {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      setDashboardState(null);
      setSyncError('后端编剧看板暂不可用，当前显示任务内嵌资产。');
    });
    return () => controller.abort();
  }, [taskId, refreshKey]);

  const breakdown = dashboard ? {
    overview: {
      ...dashboard.overview,
      world_setting: dashboard.overview.worldSetting || dashboard.overview.world_setting,
    },
    scenes: dashboard.scenes.map(scene => ({
      ...scene,
      scene_id: scene.sceneId,
      duration: scene.durationLabel,
    })),
    timeline: dashboard.timeline,
    roles: dashboard.roles,
    relationships: dashboard.relationships,
  } : fallbackBreakdown;
  const resolvedEpisodes = dashboard?.episodes.map(serverEpisode => {
    const liveEpisode = episodes.find(item => item.index === serverEpisode.index);
    return liveEpisode ? { ...serverEpisode, ...liveEpisode } : serverEpisode;
  }) || episodes;

  const downloadDashboard = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/drama/${encodeURIComponent(taskId)}/writer-dashboard/export`, {
        credentials: 'include',
      });
      if (!response.ok) throw new Error(`export failed: ${response.status}`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${resolvedTitle || 'writer-agent'}-dashboard.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      setSyncError('后端 JSON 导出失败，请稍后重试。');
    }
  };

  return (
    <div className="writer-board-container">
      {syncError && <p className="writer-sync-warning" role="status">{syncError}</p>}
      <WriterAgentPage
        title={resolvedTitle}
        breakdown={breakdown}
        script={dashboard?.script || fallbackScript}
        requestedEpisodeCount={dashboard?.stats.totalEpisodes || requestedEpisodeCount}
        episodes={resolvedEpisodes}
        episodesBusy={episodesBusy}
        serverStats={dashboard?.stats}
        onExport={downloadDashboard}
        onPlanEpisodes={onPlanEpisodes}
        onProduceEpisode={onProduceEpisode}
      />
    </div>
  );
}
