// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { DeliveryChecklist } from './DeliveryChecklist';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('DeliveryChecklist', () => {
  it('names the shot, the rule and why, and says so when nothing needs fixing', () => {
    const { rerender } = render(<DeliveryChecklist issues={[
      { shot_uid: 100401, scene_id: 'E1S04', shot_id: 1, rule: 'dialogue', detail: '台词约需 12 秒，这一镜只有 8 秒' },
      { shot_uid: null, scene_id: '', shot_id: null, rule: 'few_sizes', detail: '整条成片只用了中景' },
    ]} />);
    const items = screen.getAllByRole('listitem').map(item => item.textContent);
    expect(items[0]).toContain('E1S04 第1镜');
    expect(items[0]).toContain('台词放不下');
    expect(items[1]).toContain('整条成片');
    rerender(<DeliveryChecklist issues={[]} />);
    expect(screen.getByRole('status').textContent).toContain('没发现要改的镜头');
  });

  it('groups problems by layer with their tier, and lists unchecked layers as unverified, not passed', () => {
    render(<DeliveryChecklist issues={[
      { shot_uid: 1, scene_id: 'E1S01', shot_id: 1, rule: 'dub_over_face', detail: '换成了配音', layer: '表演', tier: 'manual', tier_label: '需人工确认' },
      { shot_uid: 2, scene_id: 'E1S01', shot_id: 2, rule: 'dialogue', detail: '放不下', layer: '阅读', tier: 'must', tier_label: '必须修复' },
      { shot_uid: null, scene_id: '', shot_id: null, rule: 'unverified', detail: '授权没有记录', layer: '授权', tier: 'manual', tier_label: '需人工确认' },
    ]} />);
    expect(screen.getByText('表演')).toBeTruthy();
    expect(screen.getByText('必须修复')).toBeTruthy();
    expect(screen.getByText('配音盖了原口型')).toBeTruthy();
    expect(screen.getByText('未验证（需人工确认）')).toBeTruthy();
    expect(screen.getByText('授权没有记录')).toBeTruthy();
  });

  it('shows the cost per usable shot as the last line, not as a problem', () => {
    render(<DeliveryChecklist issues={[
      { shot_uid: null, scene_id: '', shot_id: null, rule: 'unit_cost', detail: '可用镜头单价：每镜约 3.00 元', layer: '', tier: 'info', tier_label: '' },
    ]} />);
    expect(screen.getByText('可用镜头单价：每镜约 3.00 元')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toContain('没发现要改的镜头');
  });

  it('notes a licence on a rights item and hands back the new timeline', async () => {
    const calls: Array<{ url: string; body?: unknown }> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      calls.push({ url: String(input), body: init?.body ? JSON.parse(String(init.body)) : undefined });
      return { ok: true, json: async () => ({ acceptance: [] }) } as Response;
    });
    const onTimeline = vi.fn();
    const user = userEvent.setup();
    render(<DeliveryChecklist taskId="t1" onTimeline={onTimeline} issues={[
      { shot_uid: null, scene_id: '', shot_id: null, rule: 'rights', detail: '字幕字体 STHeiti：系统自带字体', layer: '授权', tier: 'manual', tier_label: '需人工确认', rights_key: 'font:STHeiti.ttc' },
    ]} />);
    expect(screen.getByText('授权待确认')).toBeTruthy();
    await user.type(screen.getByLabelText('授权说明'), '已购商用授权');
    await user.click(screen.getByRole('button', { name: '记下' }));
    expect(calls.at(-1)).toMatchObject({ url: expect.stringContaining('/api/drama/t1/rights/note'), body: { key: 'font:STHeiti.ttc', note: '已购商用授权' } });
    expect(onTimeline).toHaveBeenCalledWith({ acceptance: [] });
  });

  it('with only unverified layers it does not read as a pass', () => {
    render(<DeliveryChecklist issues={[
      { shot_uid: null, scene_id: '', shot_id: null, rule: 'unverified', detail: '黑帧没查', layer: '技术', tier: 'manual', tier_label: '需人工确认' },
    ]} />);
    expect(screen.getByRole('status').textContent).toContain('需要人看过才算通过');
  });
});
