import { apiRequest } from '../../api/client';

export interface ShotRef { scene_id: string; shot_id: number | string; video_url: string }

export interface HandoffPair {
  from: ShotRef;
  to: ShotRef;
  verdict: 'good' | 'suspect' | 'unknown';
  label: string;
  findings: Array<{ code: string; text: string }>;
  /** 上一镜结尾量出来的样子。 */
  tail: string;
  /** 下一镜开头量出来的样子。 */
  head: string;
}

export interface HandoffReport {
  episode: number;
  pairs: HandoffPair[];
  suspect: number;
  summary: string;
}

export function fetchEpisodeHandoff(taskId: string, episode: number) {
  return apiRequest<HandoffReport>(`/api/drama/${encodeURIComponent(taskId)}/episodes/${episode}/handoff`);
}
