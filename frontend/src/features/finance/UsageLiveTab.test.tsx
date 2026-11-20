// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { FinanceConsolePage } from './FinanceConsolePage';
import { amounts, fine } from './financeFormat';
import { QuoteTab } from './QuoteTab';
import { quoteSheet } from './quoteSheet';
import { UsageLiveTab, type LiveUsage, type UsageFigures } from './UsageLiveTab';


const figures = (over: Partial<UsageFigures> = {}): UsageFigures => ({
  calls: 0, failed: 0, unpriced_calls: 0, input_tokens: 0, output_tokens: 0, reasoning_tokens: 0, cached_tokens: 0, tokens: 0,
  images: 0, seconds: 0, characters: 0, cost: {}, quote: {}, ...over,
});

function usage(calls: number): LiveUsage {
  const text = figures({ calls, failed: 1, input_tokens: 120000, output_tokens: 3456, tokens: 123456, cost: { CNY: 10 }, quote: { CNY: 12 } });
  return {
    generated_at: '2026-11-19T04:00:00+00:00', since: '2026-11-19T03:00:00+00:00', window_minutes: 60, bucket_seconds: 60, markup: 0.2,
    usd_cny: 7.2, converted_from_usd: true,
    total: figures({ ...text, calls: calls + 1, unpriced_calls: 1, images: 1, seconds: 15, cost: { CNY: 32.866 }, quote: { CNY: 39.4392 } }),
    by_model: [
      { media_type: 'video', provider: 'ark', model: 'seedance-2-5', ...figures({ calls: 1, seconds: 15, cost: { CNY: 22.65 }, quote: { CNY: 27.18 } }) },
      { media_type: 'text', provider: 'deepseek', model: 'deepseek-flash', ...text },
      { media_type: 'image', provider: 'ark', model: 'doubao-seedream-5-5', ...figures({ calls: 1, unpriced_calls: 1, images: 1 }) },
    ],
    by_user: [{ user_id: 'u1', user_name: '林夕', ...text }, { user_id: '', ...figures({ calls: 1 }) }],
    by_task: [{ task_id: 'drama-1', user_id: 'u1', user_name: '林夕', title: '雪夜归人', ...text }],
    series: [
      { at: '2026-11-19T03:58:00+00:00', ...figures({ calls: 2, tokens: 1000, quote: { CNY: 1.2 } }) },
      { at: '2026-11-19T03:59:00+00:00', ...figures({ calls: 5, tokens: 4000, quote: { CNY: 6 } }) },
    ],
    recent: [
      { at: '2026-11-19T03:59:30+00:00', media_type: 'text', provider: 'deepseek', model: 'deepseek-flash', purpose: 'stage_2', status: 'success', user_id: 'u1', user_name: '林夕', task_id: 'drama-1', input_tokens: 800, output_tokens: 200, cost: 0.0032, quote: 0.00384, currency: 'CNY' },
      { at: '2026-11-19T03:59:10+00:00', media_type: 'video', provider: 'ark', model: 'seedance-2-5', purpose: 'stage_5', status: 'failed', user_id: 'u1', user_name: '林夕', task_id: 'drama-1', input_tokens: 0, output_tokens: 0, cost: null, quote: null, currency: '' },
      { at: '2026-11-19T03:59:00+00:00', media_type: 'image', provider: 'ark', model: 'doubao-seedream-5-5', purpose: 'stage_3', status: 'success', user_id: 'u1', user_name: '林夕', task_id: 'drama-1', input_tokens: 0, output_tokens: 0, cost: null, quote: null, currency: '' },
    ],
    unpriced_models: [{ model: 'doubao-seedream-5-5', calls: 1 }],
  };
}

const QUOTES = {
  markup: 0.2,
  usd_cny: 7.2,
  items: [
    { model: 'deepseek-flash', kind: 'per_million_tokens', currency: 'CNY', official: { input: 2, output: 8 }, quote: { input: 2.4, output: 9.6 } },
    { model: 'seedance-2-5', kind: 'per_second', currency: 'CNY', official: { price: 1.51, by_resolution: { '480p': 0.67 } }, quote: { price: 1.812, by_resolution: { '480p': 0.804 } } },
    { model: 'music_v2', kind: 'per_second', currency: 'CNY', priced_in: 'USD', official: { price: 0.018 }, quote: { price: 0.0216 } },
  ],
};

/** Answers every request; the live figures count one more call each time they are asked for. */
function serve() {
  const urls: string[] = [];
  let asked = 0;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const url = String(input);
    urls.push(url);
    const body = url.includes('/usage/live') ? usage(40 + (asked += 1)) : url.includes('/pricing/quote') ? QUOTES : { items: [], total: 0 };
    return { ok: true, status: 200, json: async () => body } as Response;
  });
  return { urls, live: () => urls.filter(url => url.includes('/usage/live')) };
}

const wait = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

describe('live usage and the outward quote', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('shows calls, tokens, the official cost and the quote a fifth above it', async () => {
    serve();
    render(<UsageLiveTab />);
    await wait(10);
    expect(screen.getByText('42')).toBeTruthy();
    // The total, and the same figure on the project's and the account's rows.
    expect(screen.getAllByText('123,456').length).toBe(3);
    expect(screen.getByText('输入 120,000 · 输出 3,456')).toBeTruthy();
    // One figure in yuan; the page says dollar-priced models were converted, and at what rate.
    expect(screen.getByText('¥32.87')).toBeTruthy();
    expect(screen.getByText('¥39.44')).toBeTruthy();
    expect(screen.getByText('美元计价的模型按 1 美元 = ¥7.2 折算')).toBeTruthy();
    expect(document.body.textContent).not.toContain('USD');
    expect(screen.getAllByText('对外报价（+20%）').length).toBeGreaterThan(1);
    expect(screen.getByText('官方价 × 1.2')).toBeTruthy();
    expect(screen.getByText('雪夜归人')).toBeTruthy();
  });

  it('names the models it could not price instead of counting them as free', async () => {
    serve();
    render(<UsageLiveTab />);
    await wait(10);
    expect(screen.getByText(/这些模型没有官方价.*doubao-seedream-5-5（1 次）/)).toBeTruthy();
    expect(screen.getAllByText('没有官方价').length).toBe(2);
    expect(screen.getByText('失败，不计成本')).toBeTruthy();
    // A fraction of a fen is still shown, not rounded to nothing.
    expect(screen.getByText('¥0.0032')).toBeTruthy();
    expect(screen.getByText('¥0.0038')).toBeTruthy();
  });

  it('asks again every five seconds, and stops while paused', async () => {
    const calls = serve();
    render(<UsageLiveTab />);
    await wait(10);
    expect(calls.live().length).toBe(1);
    await wait(5000);
    expect(calls.live().length).toBe(2);
    expect(screen.getByText('43')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /暂停刷新/ }));
    await wait(15000);
    expect(calls.live().length).toBe(2);
    expect(screen.getByText(/已暂停/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /继续刷新/ }));
    await wait(5000);
    expect(calls.live().length).toBe(3);
  });

  it('asks for the window that was picked', async () => {
    const calls = serve();
    render(<UsageLiveTab />);
    await wait(10);
    fireEvent.change(screen.getByLabelText('时间范围'), { target: { value: '1440' } });
    await wait(10);
    expect(calls.live().at(-1)).toContain('minutes=1440');
  });

  it('reads one bar of the chart, in the measure that was picked', async () => {
    serve();
    render(<UsageLiveTab />);
    await wait(10);
    const bars = screen.getAllByRole('img');
    expect(bars.length).toBe(2);
    expect(bars[1].getAttribute('aria-label')).toMatch(/4,000，5 次调用/);
    fireEvent.click(screen.getByRole('button', { name: '对外报价' }));
    expect(screen.getAllByRole('img')[1].getAttribute('aria-label')).toMatch(/¥6\.00，5 次调用/);
    fireEvent.mouseEnter(screen.getAllByRole('img')[0]);
    expect(screen.getByText(/¥1\.20，2 次调用/)).toBeTruthy();
  });

  it('lists each model at its official price and at the quote', async () => {
    serve();
    render(<QuoteTab />);
    await wait(10);
    expect(screen.getByText('输入 ¥2 · 输出 ¥8')).toBeTruthy();
    expect(screen.getByText('输入 ¥2.4 · 输出 ¥9.6')).toBeTruthy();
    expect(screen.getByText('¥0.0216')).toBeTruthy();
    expect(screen.getByText(/官方价按美元计的模型按 1 美元 = ¥7\.2 折成人民币/)).toBeTruthy();
    expect(document.body.textContent).not.toContain('USD');
    expect(screen.getByText(/官方价 × 1\.2（加 20%）/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('按模型名查找'), { target: { value: 'SEEDANCE' } });
    expect(screen.queryByText('deepseek-flash')).toBeNull();
    expect(screen.getByText('480p ¥0.804')).toBeTruthy();
  });

  it('writes the sheet that goes out with the quote alone', () => {
    const sheet = quoteSheet(QUOTES.items);
    expect(sheet.charCodeAt(0)).toBe(0xfeff);
    const lines = sheet.slice(1).trim().split('\r\n');
    expect(lines[0]).toBe('模型,计价方式,币种,输入价,输出价,单价,按分辨率');
    expect(lines[1]).toBe('deepseek-flash,每百万 token,CNY,2.4,9.6,,');
    expect(lines[2]).toBe('seedance-2-5,每秒,CNY,,,1.812,480p 0.804');
    expect(lines[3]).toBe('music_v2,每秒,CNY,,,0.0216,');
    expect(sheet).not.toContain('1.51');
  });

  it('offers both tabs to finance and to nobody else', async () => {
    serve();
    render(<FinanceConsolePage user={{ user_id: 'u', permissions: ['recon:read'] }} onBack={() => undefined} />);
    fireEvent.click(screen.getByRole('tab', { name: '实时用量' }));
    await wait(10);
    expect(screen.getByText('Token 消耗')).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: '对外报价' }));
    await wait(10);
    expect(screen.getByText('deepseek-flash')).toBeTruthy();
    cleanup();
    render(<FinanceConsolePage user={{ user_id: 'u', permissions: ['order:read_any'] }} onBack={() => undefined} />);
    expect(screen.queryByRole('tab', { name: '实时用量' })).toBeNull();
    expect(screen.queryByRole('tab', { name: '对外报价' })).toBeNull();
  });

  it('keeps small amounts readable', () => {
    expect(fine(0.00384)).toBe('¥0.0038');
    expect(fine(12)).toBe('¥12.00');
    expect(fine(0)).toBe('¥0.00');
    expect(amounts({})).toBe('—');
    // A currency the server has no rate for keeps its own name, apart from the yuan.
    expect(amounts({ CNY: 12, EUR: 3 })).toBe('¥12.00 · EUR 3.00');
  });
});
