// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ScriptReviewDialog, type ScriptReviewReport, type ScriptReviewView } from './ScriptReviewDialog';

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
const refuse = (status: number, detail: string) => ({ ok: false, status, json: async () => ({ detail }) }) as Response;

const REPORT: ScriptReviewReport = {
  built_at: '2026-11-19T07:00:00+00:00', model: 'deepseek-flash', calls: 1,
  summary: '开场立得住，中段的因果有一处接不上。',
  dimensions: [
    { key: 'logic', label: '故事逻辑', verdict: 'revise', verdict_label: '建议修改', note: '第二集的转折缺一步' },
    { key: 'opening', label: '开场', verdict: 'pass', verdict_label: '通过', note: '第一场就出事' },
  ],
  findings: [
    { dimension: 'logic', dimension_label: '故事逻辑', severity: 'high', severity_label: '硬伤', scene: '2-1', where: '第 2-1 场', quote: '站住。', issue: '周教授怎么知道她在门口没有交代', fix: '在 1-2 末尾让他看见监控' },
    { dimension: 'dialogue', dimension_label: '台词', severity: 'low', severity_label: '小问题', scene: '', where: '全剧', quote: '', issue: '两人说话口气太像', fix: '让周教授只说短句' },
  ],
  strengths: ['第一场用找录音笔立住了悬念'], quotes_dropped: 1,
};

const view = (changes: Partial<ScriptReviewView> = {}): ScriptReviewView => ({
  title: '暗室回声', report: null, stale: false,
  facts: [{ key: 'episodes', label: '集数', value: '2' }, { key: 'scenes', label: '场次', value: '3' }],
  calls_needed: 2, attempts: 3, model: 'deepseek-flash', advice: '这份报告是给创作者参考的建议，不会改动剧本。', ...changes,
});

describe('ScriptReviewDialog', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('opens on the facts without calling the model, and asks before a paid run', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((_input, init) => Promise.resolve(
      (init as RequestInit | undefined)?.method === 'POST' ? ok(view({ report: REPORT })) : ok(view()),
    ));
    render(<ScriptReviewDialog taskId="t 1" onClose={() => {}} />);
    const facts = await screen.findByRole('list', { name: '从剧本直接数出的概况' });
    expect(within(facts).getByText('集数').textContent).toBe('集数2');
    expect(screen.getByText('还没有生成过审核报告。')).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/drama/t%201/script-review');
    expect((fetchMock.mock.calls[0][1] as RequestInit | undefined)?.method).toBeUndefined();

    fireEvent.click(screen.getByRole('button', { name: '生成审核报告' }));
    expect(screen.getByText(/会用 deepseek-flash 调用 2 次文本模型.*每段最多 3 次/)).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '先不用' }));
    expect(screen.getByRole('button', { name: '生成审核报告' })).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: '生成审核报告' }));
    fireEvent.click(screen.getByRole('button', { name: '确定生成' }));
    expect(await screen.findByText('开场立得住，中段的因果有一处接不上。')).toBeTruthy();
    expect((fetchMock.mock.calls[1][1] as RequestInit).method).toBe('POST');
  });

  it('switches to a focused check, reads and writes that check, and says when it cannot run', async () => {
    const focuses = [
      { key: '', label: '全面审核', about: '按七个方面读一遍剧本。' },
      { key: 'opening', label: '前三集主线体检', about: '只读前三集，看三件事有没有交代清楚。' },
      { key: 'voice', label: '台词对照人物小传', about: '把台词对照人物小传读一遍。' },
    ];
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const url = String(input);
      const focus = url.includes('focus=voice') ? 'voice' : url.includes('focus=opening') ? 'opening' : '';
      const posted = (init as RequestInit | undefined)?.method === 'POST';
      return Promise.resolve(ok(view({
        focuses, focus, calls_needed: 1, report: posted ? REPORT : null,
        blocked: focus === 'voice' ? '这个项目还没有人物小传，没法对照台词；先写好人物设定再来。' : '',
      })));
    });
    render(<ScriptReviewDialog taskId="t1" onClose={() => {}} />);
    const scope = await screen.findByRole('group', { name: '审核范围' });
    expect(within(scope).getByRole('button', { name: '全面审核' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText('按七个方面读一遍剧本。')).toBeTruthy();

    fireEvent.click(within(scope).getByRole('button', { name: '前三集主线体检' }));
    await waitFor(() => expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain('script-review?focus=opening'));
    expect(await screen.findByText('只读前三集，看三件事有没有交代清楚。')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '生成审核报告' }));
    fireEvent.click(screen.getByRole('button', { name: '确定生成' }));
    expect(await screen.findByText('开场立得住，中段的因果有一处接不上。')).toBeTruthy();
    const posted = fetchMock.mock.calls.find(call => (call[1] as RequestInit | undefined)?.method === 'POST');
    expect(String(posted?.[0])).toContain('script-review?focus=opening');
    expect(screen.getByRole('link', { name: /下载报告/ }).getAttribute('href')).toContain('script-review?focus=opening&format=md');

    fireEvent.click(within(scope).getByRole('button', { name: '台词对照人物小传' }));
    expect(await screen.findByText(/还没有人物小传/)).toBeTruthy();
    expect((screen.getByRole('button', { name: '生成审核报告' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('lays out the kept report: verdicts, findings with their scene and quote, strengths, and the download', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok(view({ report: REPORT, stale: true })));
    render(<ScriptReviewDialog taskId="t1" onClose={() => {}} />);
    expect(await screen.findByText('建议修改')).toBeTruthy();
    expect(screen.getByText(/剧本在这份报告生成之后改过/)).toBeTruthy();
    expect(screen.getByText('问题与改法（2 条）')).toBeTruthy();
    const items = screen.getAllByRole('listitem').filter(node => node.className.startsWith('is-'));
    expect(items.map(node => node.className)).toEqual(['is-high', 'is-low']);
    expect(within(items[0]).getByText('故事逻辑 · 硬伤 · 第 2-1 场')).toBeTruthy();
    expect(within(items[0]).getByText('站住。').tagName).toBe('BLOCKQUOTE');
    expect(items[1].querySelector('blockquote')).toBeNull();
    expect(within(items[1]).getByText('台词 · 小问题 · 全剧')).toBeTruthy();
    expect(screen.getByText(/有 1 条引文在剧本里找不到原话/)).toBeTruthy();
    expect(screen.getByText('第一场用找录音笔立住了悬念')).toBeTruthy();
    expect(screen.getByRole('button', { name: '重新生成审核报告' })).toBeTruthy();
    expect(screen.getByRole('link', { name: /下载报告/ }).getAttribute('href')).toContain('/api/drama/t1/script-review?format=md');
  });

  it('says in the server’s words why a report was not written, and keeps the old one on show', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((_input, init) => Promise.resolve(
      (init as RequestInit | undefined)?.method === 'POST' ? refuse(502, '文本模型没有给出回答，审核报告没有生成；检查模型设置后可以再试一次。') : ok(view({ report: REPORT })),
    ));
    render(<ScriptReviewDialog taskId="t1" onClose={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: '重新生成审核报告' }));
    fireEvent.click(screen.getByRole('button', { name: '确定生成' }));
    expect((await screen.findByRole('alert')).textContent).toContain('文本模型没有给出回答');
    expect(screen.getByText('开场立得住，中段的因果有一处接不上。')).toBeTruthy();
  });

  it('cannot ask without a text model, shows a script-less project its reason, and closes on Escape', async () => {
    const onClose = vi.fn();
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(ok(view({ model: '' })));
    const { unmount } = render(<ScriptReviewDialog taskId="t1" onClose={onClose} />);
    expect(((await screen.findByRole('button', { name: '生成审核报告' })) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('这个项目还没有选文本模型，先到模型设置里选一个')).toBeTruthy();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
    unmount();
    fetchMock.mockResolvedValue(refuse(409, '这个项目还没有剧本，写完剧本再来审核。'));
    render(<ScriptReviewDialog taskId="t1" onClose={onClose} />);
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('还没有剧本'));
    expect(screen.queryByRole('button', { name: '生成审核报告' })).toBeNull();
  });
});
