// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CanvasBeefPromptOptimizer } from './CanvasBeefPromptOptimizer';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
const OPTIONS = {
  modes: [{ id: 'refine', label: '精修已有提示词' }, { id: 'structure', label: '黄金结构' }],
  text_models: ['deepseek-flash'], default_text_model: 'deepseek-flash',
};
const answer = (check: Record<string, unknown>) => ({
  prompt: '【一、生成任务】\n生成一段 10 秒的视频\n【六、分段镜头脚本】\n0—5秒｜上船\n5—10秒｜回头', avoid: [], changes: ['重排成八段'],
  assumptions: [], alternatives: [], mode: 'structure', text_model: 'deepseek-flash', structure_check: check,
});

function serve(check: Record<string, unknown>) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => (init?.method === 'POST' ? ok(answer(check)) : ok(OPTIONS)));
}

describe('the eight-part structure mode in the prompt optimizer', () => {
  it('sends the clip length with the request and shows the passing rule check', async () => {
    const fetchMock = serve({ ok: true, problems: [], summary: '八段齐全；分段时间首尾相接，合计 10 秒。', total_s: 10, segments: 2 });
    render(<CanvasBeefPromptOptimizer taskId="t1" prompt="雨夜码头，林夏提灯上船，回头看了一眼" medium="video" durationSeconds={10} onAdopt={() => undefined} onClose={() => undefined} />);
    const panel = await screen.findByRole('dialog', { name: '提示词优化' });
    fireEvent.click(await within(panel).findByRole('radio', { name: '黄金结构' }));
    await waitFor(() => expect((within(panel).getByRole('button', { name: '开始优化' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(within(panel).getByRole('button', { name: '开始优化' }));
    expect(await within(panel).findByText('八段齐全；分段时间首尾相接，合计 10 秒。')).toBeTruthy();
    const sent = JSON.parse(String(fetchMock.mock.calls.find(call => call[1]?.method === 'POST')![1]!.body));
    expect(sent).toMatchObject({ mode: 'structure', medium: 'video', duration: 10 });
    expect((within(panel).getByRole('textbox', { name: '优化后的提示词（可以再改）' }) as HTMLTextAreaElement).value).toContain('【六、分段镜头脚本】');
  });

  it('lists what the rule check found wrong instead of the summary', async () => {
    serve({ ok: false, problems: ['分段时间合计 15 秒，片段时长是 10 秒，差了 5 秒。'], summary: '', total_s: 15, segments: 5 });
    render(<CanvasBeefPromptOptimizer taskId="t1" prompt="雨夜码头" medium="video" durationSeconds={10} onAdopt={() => undefined} onClose={() => undefined} />);
    const panel = await screen.findByRole('dialog', { name: '提示词优化' });
    fireEvent.click(await within(panel).findByRole('radio', { name: '黄金结构' }));
    await waitFor(() => expect((within(panel).getByRole('button', { name: '开始优化' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(within(panel).getByRole('button', { name: '开始优化' }));
    expect(await within(panel).findByText('分段时间合计 15 秒，片段时长是 10 秒，差了 5 秒。')).toBeTruthy();
    expect(within(panel).getByText('结构检查（按规则，不调用模型）')).toBeTruthy();
  });

  it('cannot be chosen for a picture node', async () => {
    serve({ ok: true, problems: [], summary: '', total_s: 0, segments: 0 });
    render(<CanvasBeefPromptOptimizer taskId="t1" prompt="雨夜码头" medium="image" onAdopt={() => undefined} onClose={() => undefined} />);
    const panel = await screen.findByRole('dialog', { name: '提示词优化' });
    expect((await within(panel).findByRole('radio', { name: '黄金结构' }) as HTMLInputElement).disabled).toBe(true);
  });

  it('offers the fight layout to clips only and the performance layout to pictures too', async () => {
    const modes = [...OPTIONS.modes, { id: 'fight', label: '动作调度' }, { id: 'performance', label: '微表情表演' }];
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => (
      init?.method === 'POST'
        ? ok(answer({ ok: false, problems: ['正文里还留着情绪的名字：伤心。把它们换成看得见的动作。'], summary: '', total_s: 0, segments: 0 }))
        : ok({ ...OPTIONS, modes })
    ));
    render(<CanvasBeefPromptOptimizer taskId="t1" prompt="她低头看信，很伤心" medium="image" onAdopt={() => undefined} onClose={() => undefined} />);
    const panel = await screen.findByRole('dialog', { name: '提示词优化' });
    expect((await within(panel).findByRole('radio', { name: '动作调度' }) as HTMLInputElement).disabled).toBe(true);
    const acting = within(panel).getByRole('radio', { name: '微表情表演' }) as HTMLInputElement;
    expect(acting.disabled).toBe(false);
    fireEvent.click(acting);
    fireEvent.click(within(panel).getByRole('button', { name: '开始优化' }));
    expect(await within(panel).findByText(/还留着情绪的名字：伤心/)).toBeTruthy();
    const sent = JSON.parse(String(fetchMock.mock.calls.find(call => call[1]?.method === 'POST')![1]!.body));
    expect(sent).toMatchObject({ mode: 'performance', medium: 'image', duration: 0 });
  });
});
