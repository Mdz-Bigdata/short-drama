import { useEffect, useState } from 'react';

import { API_BASE, ApiError, apiRequest, isUnauthorized } from '../../api/client';
import { normalizeScriptTitle } from '../workbench/scriptTitle';
import { WriterAgentPage } from './WriterAgentPage';
import type { WriterDashboardResponse, WriterEpisode, WriterRelationship } from './types';

function mergeEpisodeUpdates(serverEpisodes: WriterEpisode[], liveEpisodes: WriterEpisode[]) {
  const serverIndexes = new Set(serverEpisodes.map(episode => episode.index));
  const merged = serverEpisodes.map(serverEpisode => {
    const liveEpisode = liveEpisodes.find(episode => episode.index === serverEpisode.index);
    if (!liveEpisode) return serverEpisode;
    const runtimeEpisode = liveEpisode as WriterEpisode & Record<string, unknown>;
    const result = { ...serverEpisode, ...liveEpisode };
    if (typeof runtimeEpisode.video_url === 'string' || runtimeEpisode.video_url === null) {
      result.videoUrl = runtimeEpisode.video_url;
    }
    return result;
  });
  return [...merged, ...liveEpisodes.filter(episode => !serverIndexes.has(episode.index))];
}

function normalizeSourceHash(value: unknown) {
  const normalized = typeof value === 'string' ? value.trim().toLowerCase() : '';
  return /^[a-f\d]{64}$/.test(normalized) ? normalized : '';
}

export function WriterAgentPageContainer({
  taskId,
  refreshKey,
  displayTitle,
  title,
  fallbackBreakdown,
  fallbackScript,
  requestedEpisodeCount,
  episodes,
  episodesSourceHash,
  episodesBusy,
  onPlanEpisodes,
  onProduceEpisode,
  onScriptSaved,
  onOpenScenes,
  onOpenActors,
}: {
  taskId: string;
  refreshKey?: string;
  displayTitle?: string;
  title?: string;
  fallbackBreakdown?: unknown;
  fallbackScript?: unknown;
  requestedEpisodeCount?: number;
  episodes: WriterEpisode[];
  episodesSourceHash?: string;
  episodesBusy: boolean;
  onPlanEpisodes: () => void;
  onProduceEpisode: (index: number) => void;
  onScriptSaved?: (dashboard: WriterDashboardResponse) => void;
  onOpenScenes?: () => void;
  onOpenActors?: () => void;
}) {
  const [dashboardState, setDashboardState] = useState<{
    taskId: string;
    data: WriterDashboardResponse;
  } | null>(null);
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
      setDashboardState({
        taskId,
        data,
      });
      setSyncError('');
    }).catch(error => {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      setDashboardState(null);
      setSyncError(isUnauthorized(error)
        ? '登录状态已过期，请重新登录后继续。'
        : '后端编剧看板暂不可用，当前显示任务内嵌资产。');
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
  const parentEpisodesSourceHash = normalizeSourceHash(episodesSourceHash);
  const dashboardSourceHash = normalizeSourceHash(dashboard?.sourceHash);
  const parentEpisodesMatchDashboard = Boolean(parentEpisodesSourceHash)
    && parentEpisodesSourceHash === dashboardSourceHash;
  const resolvedEpisodes = dashboard
    ? (parentEpisodesMatchDashboard
      ? mergeEpisodeUpdates(dashboard.episodes, episodes)
      : dashboard.episodes)
    : episodes;

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

  const saveRelationships = async (relationships: WriterRelationship[]) => {
    try {
      const data = await apiRequest<WriterDashboardResponse>(
        `/api/drama/${encodeURIComponent(taskId)}/relationships`,
        {
          method: 'PUT',
          body: JSON.stringify({
            relationships: relationships.map(edge => ({
              from: String(edge.from || '').trim(),
              to: String(edge.to || '').trim(),
              relation: String(edge.relation || '').trim() || '剧情关联',
              bidirectional: edge.bidirectional === true,
            })),
          }),
        },
      );
      setDashboardState({ taskId, data });
      setSyncError('');
    } catch (error) {
      const message = isUnauthorized(error)
        ? '登录状态已过期，请重新登录后再保存人物关系。'
        : '人物关系保存失败，请确认后端服务可用后重试。';
      setSyncError(message);
      throw new Error(message, { cause: error });
    }
  };

  const saveScript = async (content: string, fileName: string, baseSourceHash: string) => {
    if (!dashboard) {
      throw new Error('无法确认剧本版本，请恢复后端连接并刷新页面后再保存。');
    }
    if (!/^[a-f\d]{64}$/i.test(baseSourceHash)) {
      throw new Error('无法确认编辑起始版本，请关闭编辑器、刷新页面后重试。');
    }
    const persist = (confirmInvalidate: boolean) => apiRequest<WriterDashboardResponse>(
      `/api/drama/${encodeURIComponent(taskId)}/script`,
      {
        method: 'PATCH',
        body: JSON.stringify({
          content,
          file_name: fileName,
          expected_source_hash: baseSourceHash,
          confirm_invalidate: confirmInvalidate,
        }),
      },
    );
    try {
      let data: WriterDashboardResponse;
      try {
        data = await persist(false);
      } catch (error) {
        const requiresArchive = error instanceof ApiError
          && error.status === 409
          && /归档|下游|成片|角色、分镜/.test(error.message);
        if (!requiresArchive) throw error;
        const confirmed = window.confirm(
          '应用新剧本会归档当前角色、分镜和成片，并从编剧阶段重新开始。旧成果仍保留在版本归档中。是否继续？',
        );
        if (!confirmed) {
          throw new Error('已取消应用新剧本，本地草稿仍保留。', { cause: error });
        }
        data = await persist(true);
      }
      setDashboardState({
        taskId,
        data,
      });
      onScriptSaved?.(data);
      setSyncError('');
      return data.sourceHash;
    } catch (error) {
      setSyncError('剧本保存失败，本地草稿仍保留在编辑器中。');
      throw error instanceof Error ? error : new Error('剧本保存失败，请稍后重试。');
    }
  };

  return (
    <div className="writer-board-container">
      {syncError && <p className="writer-sync-warning" role="status">{syncError}</p>}
      <WriterAgentPage
        title={resolvedTitle}
        taskId={taskId}
        breakdown={breakdown}
        script={dashboard?.script || fallbackScript}
        scriptFileName={dashboard?.scriptFileName || undefined}
        scriptSourceHash={dashboard?.sourceHash || undefined}
        requestedEpisodeCount={dashboard?.stats.totalEpisodes || requestedEpisodeCount}
        episodes={resolvedEpisodes}
        episodesBusy={episodesBusy}
        serverStats={dashboard?.stats}
        onExport={downloadDashboard}
        onPlanEpisodes={onPlanEpisodes}
        onProduceEpisode={onProduceEpisode}
        onSaveScript={saveScript}
        onSaveRelationships={taskId ? saveRelationships : undefined}
        onOpenScenes={onOpenScenes}
        onOpenActors={onOpenActors}
      />
    </div>
  );
}
