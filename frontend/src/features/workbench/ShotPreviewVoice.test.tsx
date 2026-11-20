// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ShotVisualWorkspace } from './ShotVisualWorkspace';
import type { ShotVisualWorkspace as Workspace } from './shotVisual';

function workspace(preview_url: string | null): Workspace {
  return {
    task_id: 'visual-task', current_stage: 5, running: false, video_model: 'MiniMax-H3', provider_family: 'minimax_h3',
    duration_options: [4, 5, 6], camera_motions: [{ value: 'Static', label: '固定' }], shot_types: [{ value: 'Medium Shot', label: '中景' }],
    recipe_categories: [],
    shots: [{
      shot_id: 1, scene_id: 'E1S01', desc: '沈砚推门而入', dialogue: '沈砚：退下。', sound: '',
      settings: { camera_motion: 'Static', shot_type: 'Medium Shot', duration_seconds: 5, action: '', ambiance_audio: '', lighting: '', ambiance: '' },
      settings_source: 'derived', derived_notes: [], image_url: '/media/p1.png', video_url: '/media/c1.mp4', preview_url,
      candidate_urls: ['/media/c1.mp4', '/media/c1-b.mp4'], image_prompt: '', video_prompt: '', contract_fingerprint: '', route: null, stale: false, stale_reason: '',
    }],
  } as Workspace;
}

function serve(current: Workspace) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const url = String(input);
    if (url.includes('/usage')) return { ok: true, json: async () => ({ summary: null }) } as Response;
    if (url.endsWith('/shots/admission')) return { ok: true, json: async () => ({}) } as Response;
    return { ok: true, json: async () => current } as Response;
  });
}

describe('a shot re-voiced after a voice change', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it('plays the re-voiced preview and still marks the clip in use', async () => {
    serve(workspace('/media/c1_revoiced.mp4'));
    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" />);
    const video = await screen.findByLabelText('镜头 1 视频');
    expect(video.getAttribute('src')).toBe('/media/c1_revoiced.mp4');
    expect(screen.getByRole('button', { name: '预览版本 1' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('plays the clip itself when there is no re-voiced preview', async () => {
    serve(workspace(null));
    render(<ShotVisualWorkspace taskId="visual-task" videoModel="MiniMax-H3" imageModel="seedream" />);
    expect((await screen.findByLabelText('镜头 1 视频')).getAttribute('src')).toBe('/media/c1.mp4');
  });
});
