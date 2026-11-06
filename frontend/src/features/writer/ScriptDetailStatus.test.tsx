// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('./screenwritingApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./screenwritingApi')>()),
  fetchScreenwritingState: vi.fn().mockResolvedValue({
    available: true,
    ledger: [
      { episode: 1, title: '匿名录音', hook: '雨夜里的一盘磁带', storyBeats: ['林夏收到录音', '导师避而不谈'], nextEpisodeTeaser: '实验室的门开了', ledgerStatus: 'planned' },
      { episode: 2, title: '实验室疑云', hook: '', storyBeats: [], ledgerStatus: 'planned' },
    ],
  }),
}));

import { shouldPollWorkflow } from '../workbench/workflowMessages';
import type { TaskResponse } from '../../types';
import { WriterAgentPage } from './WriterAgentPage';
import { scriptDetailPhase } from './scriptDetail';

const now = Date.now() / 1000;
const writing = { status: 'writing', written: 1, total: 2, percent: 40, label: '编剧 · 第 2 集视觉层', updated_at: now };
const stats = { totalEpisodes: 2, scriptedEpisodes: 0, missingEpisodes: [1, 2], sceneCount: 0, characterCount: 2, mainEventCount: 0, relationshipCount: 0, totalDurationSeconds: 0, tone: '' };

describe('outline first, screenplay in the background', () => {
  afterEach(() => cleanup());

  it('tells writing, failed and interrupted runs apart', () => {
    expect(scriptDetailPhase(undefined)).toBeNull();
    expect(scriptDetailPhase({ status: 'done' })).toBeNull();
    expect(scriptDetailPhase(writing, now)).toBe('writing');
    expect(scriptDetailPhase({ ...writing, updated_at: now - 1300 }, now)).toBe('interrupted');
    expect(scriptDetailPhase({ status: 'failed' })).toBe('failed');
  });

  it('shows the outline and the progress, and offers no repair while the episodes are written', async () => {
    const user = userEvent.setup();
    const onContinueScript = vi.fn().mockResolvedValue(undefined);
    render(<WriterAgentPage taskId="t1" script="" serverStats={stats} onContinueScript={onContinueScript} scriptDetail={writing} />);

    expect(screen.getByText('剧本大纲已完成，详细剧本正在后台撰写')).toBeTruthy();
    expect(screen.getByText(/已写完 1\/2 集/)).toBeTruthy();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('40');

    await user.click(screen.getByRole('button', { name: '查看分集大纲' }));
    expect(await screen.findByText('匿名录音')).toBeTruthy();
    expect(screen.getByText('实验室疑云')).toBeTruthy();
    expect(screen.getByText('林夏收到录音')).toBeTruthy();
    expect(screen.queryByText(/正文缺失|剧本缺少/)).toBeNull();
    expect(screen.queryByRole('button', { name: /补写缺失/ })).toBeNull();
  });

  it('offers to continue a run that failed part way', () => {
    render(<WriterAgentPage taskId="t1" script="" serverStats={stats} onContinueScript={vi.fn()}
      scriptDetail={{ status: 'failed', written: 0, total: 2, error: 'RuntimeError: provider down' }} />);
    expect(screen.getByText('详细剧本后台撰写失败')).toBeTruthy();
    expect(screen.getByText(/provider down/)).toBeTruthy();
    expect(screen.getAllByRole('button', { name: '补写缺失的 2 集' }).length).toBeGreaterThan(0);
  });

  it('keeps polling an idle project while its screenplay is being written', () => {
    const idle = { status: 'idle', assets: {} } as unknown as TaskResponse;
    expect(shouldPollWorkflow(idle)).toBe(false);
    expect(shouldPollWorkflow({ ...idle, assets: { '2_detail': writing } } as unknown as TaskResponse)).toBe(true);
    expect(shouldPollWorkflow({ ...idle, assets: { '2_detail': { ...writing, status: 'done' } } } as unknown as TaskResponse)).toBe(false);
  });
});
