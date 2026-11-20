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
  modes: [{ id: 'refine', label: '精修已有提示词' }, { id: 'camera', label: '机位诊断' }],
  text_models: ['deepseek-flash'], default_text_model: 'deepseek-flash',
};
const EMOTION = {
  id: 'lonely', label: '孤独 / 疏离', why: '离得远，画面里又没有第二个人。', avoid: '别给特写：一靠近就不孤独了。',
  recipe: [
    { dimension: '景别', take: '大远景或远景，人很小' }, { dimension: '高度', take: '平视略高' }, { dimension: '朝向', take: '背面' },
    { dimension: '镜头', take: '广角' }, { dimension: '构图', take: '大片留白' }, { dimension: '运镜', take: '固定机位' },
  ],
};
const REFERENCE = {
  principle: '机位是情绪的落点。', emotions: [EMOTION], turns: [{ name: '收紧', how: '一镜比一镜近' }],
  beats: [{ name: '揭示', shots: '反应 → 插入 → 变化' }], beat_rule: '每个节拍至少有一镜给信息、一镜给反应。',
};
const FOUND = {
  findings: [
    { check: 1, code: 'no_angle', title: '没有说相机在哪', detail: '没有写机位的高度和朝向。', evidence: [] },
    { check: 2, code: 'emotion_clash', title: '机位和情绪对不上', detail: '这条写的是「孤独 / 疏离」，却用了「特写」。', evidence: ['特写'] },
  ],
  main: 'no_angle', emotion: '孤独 / 疏离', moves: [], reference: REFERENCE,
};
const REWRITE = {
  prompt: '大远景，略高，背面；女孩站在站台右下角', avoid: [], changes: ['主因是第①项：没有说相机在哪'], assumptions: [], alternatives: [],
  mode: 'camera', text_model: 'deepseek-flash',
};

function serve(found: unknown = FOUND) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes('/camera-diagnosis')) return ok(found);
    return init?.method === 'POST' ? ok(REWRITE) : ok(OPTIONS);
  });
}

const PROMPT = '一个女孩站在空荡的地铁站里，孤独，电影感，特写';

describe('camera diagnosis in the prompt optimizer', () => {
  it('shows the rule check as soon as the mode is chosen, before any rewrite is asked for', async () => {
    const fetchMock = serve();
    render(<CanvasBeefPromptOptimizer taskId="t1" prompt={PROMPT} medium="video" onAdopt={() => undefined} onClose={() => undefined} />);
    const panel = await screen.findByRole('dialog', { name: '提示词优化' });
    expect(within(panel).queryByRole('region', { name: '规则检查' })).toBeNull();
    fireEvent.click(await within(panel).findByRole('radio', { name: '机位诊断' }));
    const check = await within(panel).findByRole('region', { name: '规则检查' });
    const items = await within(check).findAllByRole('listitem');
    expect(items[0].textContent).toContain('没有说相机在哪');
    expect(items[0].textContent).toContain('主因');
    expect(items[1].textContent).toContain('机位和情绪对不上');
    expect(items[1].textContent).not.toContain('主因');
    expect(within(check).getByText('「孤独 / 疏离」通常这样拍')).toBeTruthy();
    const diagnosed = fetchMock.mock.calls.find(call => String(call[0]).includes('/camera-diagnosis'))!;
    expect(JSON.parse(String(diagnosed[1]!.body))).toEqual({ prompt: PROMPT, medium: 'video' });
    expect(fetchMock.mock.calls.some(call => String(call[0]).endsWith('/prompt-optimize') && call[1]?.method === 'POST')).toBe(false);
  });

  it('asks for the rewrite in camera mode and adopts only what the person accepts', async () => {
    const fetchMock = serve();
    const onAdopt = vi.fn();
    render(<CanvasBeefPromptOptimizer taskId="t1" prompt={PROMPT} medium="video" onAdopt={onAdopt} onClose={() => undefined} />);
    const panel = await screen.findByRole('dialog', { name: '提示词优化' });
    fireEvent.click(await within(panel).findByRole('radio', { name: '机位诊断' }));
    await waitFor(() => expect((within(panel).getByRole('button', { name: '开始优化' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(within(panel).getByRole('button', { name: '开始优化' }));
    const edited = await within(panel).findByRole('textbox', { name: '优化后的提示词（可以再改）' }) as HTMLTextAreaElement;
    expect(edited.value).toBe(REWRITE.prompt);
    const sent = fetchMock.mock.calls.find(call => String(call[0]).endsWith('/prompt-optimize') && call[1]?.method === 'POST')!;
    expect(JSON.parse(String(sent[1]!.body))).toMatchObject({ mode: 'camera', medium: 'video', prompt: PROMPT });
    expect(onAdopt).not.toHaveBeenCalled();
    fireEvent.click(within(panel).getByRole('button', { name: '采用' }));
    expect(onAdopt).toHaveBeenCalledWith(REWRITE.prompt);
  });

  it('says so when the four checks find nothing', async () => {
    serve({ ...FOUND, findings: [], main: '', emotion: '' });
    render(<CanvasBeefPromptOptimizer taskId="t1" prompt="中景，平视，她低头看信，固定机位" medium="video" onAdopt={() => undefined} onClose={() => undefined} />);
    const panel = await screen.findByRole('dialog', { name: '提示词优化' });
    fireEvent.click(await within(panel).findByRole('radio', { name: '机位诊断' }));
    expect(await within(panel).findByText(/四项检查都没有查出明显问题/)).toBeTruthy();
  });
});
