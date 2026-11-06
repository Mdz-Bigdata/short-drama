// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AcquisitionPanel, type AcquisitionView, type Lead } from './AcquisitionPanel';

const LEAD: Lead = {
  id: 'l1', platform: 'youtube', author_name: 'Ann', intent: 'watch_full', score: 75, judged_by: 'model',
  status: 'new', reply: 'The full series is on YouTube.', dm: '', reply_to: 'Ugx1',
  evidence: [{ comment_id: 'Ugx1', work_id: 'w1', text: 'Where can I watch the full series?', published_at: '', intent: 'watch_full' }],
  send_state: '', note: '',
};

function view(overrides: Partial<AcquisitionView> = {}): AcquisitionView {
  return {
    channels: [
      { id: 'douyin', name: '抖音', color: '#1f2430', language: 'zh', autoRead: false, autoReply: false },
      { id: 'youtube', name: 'YouTube', color: '#dd3838', language: 'en', autoRead: true, autoReply: true },
    ],
    capabilities: { youtubeRead: true, youtubeReply: true, timezone: 'Asia/Shanghai' },
    settings: { auto_sync: true }, syncedAt: null, syncErrors: [],
    works: [{ id: 'w1', platform: 'youtube', url: 'https://youtu.be/dQw4w9WgXcQ', episode: 1, title: '', metrics: { views: 1200 }, metrics_at: null, comments: 1 }],
    leads: [LEAD], followUps: [], inbox: [],
    review: {
      generated_at: '2026-10-30T11:00:00+08:00',
      funnel: { comments: 1, leads: 1, reached: 0, replied: 0, won: 0 }, due_follow_ups: 0,
      suggestions: ['1 位观众在问全集去哪看：回复里写清平台和剧名'], last_24h: { comments: 1, leads: 1 }, platforms: [],
    },
    ...overrides,
  };
}

function serve(handler: (path: string, init?: RequestInit) => AcquisitionView) {
  const calls: Array<{ path: string; method: string; body: unknown }> = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const path = String(input).split('/api/drama/t1/acquisition')[1] ?? '';
    calls.push({ path, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined });
    return { ok: true, status: 200, json: async () => handler(path, init) } as Response;
  });
  return calls;
}

describe('AcquisitionPanel', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('shows the funnel and suggestions, and posts a YouTube reply only when clicked', async () => {
    const calls = serve((path) => (path === '/leads/l1/send'
      ? { ...view({ leads: [{ ...LEAD, status: 'contacted', send_state: 'sent' }] }), result: { state: 'sent' } }
      : view()));
    render(<AcquisitionPanel taskId="t1" />);

    expect(await screen.findByText('“Where can I watch the full series?”')).toBeTruthy();
    expect(screen.getByText('1 位观众在问全集去哪看：回复里写清平台和剧名')).toBeTruthy();
    expect(calls.filter(call => call.path.endsWith('/send'))).toHaveLength(0);

    await userEvent.click(screen.getByRole('button', { name: /发到 YouTube/ }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('回复已发到 YouTube'));
    await userEvent.click(screen.getByRole('button', { name: /已联系/ }));
    expect(screen.getByText('已在 YouTube 回复')).toBeTruthy();
    expect(calls.filter(call => call.path === '/leads/l1/send' && call.method === 'POST')).toHaveLength(1);
  });

  it('asks a person to check after an unclear send instead of offering to send again', async () => {
    const calls = serve(path => (path === '/leads/l1/send-result'
      ? view({ leads: [{ ...LEAD, send_state: '' }] })
      : view({ leads: [{ ...LEAD, send_state: 'unknown', send_error: '发送时连接中断' }] })));
    render(<AcquisitionPanel taskId="t1" />);

    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /发到 YouTube/ })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: '没发出' }));
    expect(calls.find(call => call.path === '/leads/l1/send-result')?.body).toEqual({ sent: false });
  });

  it('schedules a follow-up from plain words and imports pasted comments for platforms without an API', async () => {
    const douyin = { id: 'w2', platform: 'douyin', url: 'https://www.douyin.com/video/7', episode: 2, title: '', metrics: {}, metrics_at: null, comments: 0 };
    const calls = serve(() => view({ works: [douyin] }));
    render(<AcquisitionPanel taskId="t1" />);

    await userEvent.type(await screen.findByRole('textbox', { name: '跟进时间' }), '明天');
    await userEvent.click(screen.getByRole('button', { name: '安排跟进' }));
    expect(calls.find(call => call.path === '/leads/l1/follow-up')?.body).toEqual({ when: '明天' });

    await userEvent.click(screen.getByRole('tab', { name: /作品与评论/ }));
    await userEvent.click(screen.getByRole('button', { name: '粘贴导入评论' }));
    await userEvent.type(screen.getByRole('textbox', { name: '粘贴评论' }), '阿青：在哪看全集');
    await userEvent.click(screen.getByRole('button', { name: '导入并找线索' }));
    expect(calls.find(call => call.path === '/comments/import')?.body).toEqual({ work_id: 'w2', text: '阿青：在哪看全集' });
  });
});
