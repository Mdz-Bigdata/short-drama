// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CharacterDesignerPageContainer } from './CharacterDesignerPageContainer';

const response = {
  schemaVersion: 'character-dashboard.v1',
  taskId: 'task-3',
  sourceHash: 'a'.repeat(64),
  title: '服务端角色集',
  state: 'READY',
  viewContract: {
    version: 'five-view.v1',
    order: ['front', 'front_three_quarter', 'profile', 'rear_three_quarter', 'back'],
    views: [
      { key: 'front', order: 1, angleDegrees: 0, labelZh: '正面', labelEn: 'Front view' },
      { key: 'front_three_quarter', order: 2, angleDegrees: 45, labelZh: '正面四分之三', labelEn: 'Front three-quarter view' },
      { key: 'profile', order: 3, angleDegrees: 90, labelZh: '标准侧面', labelEn: 'Standard profile view' },
      { key: 'rear_three_quarter', order: 4, angleDegrees: 135, labelZh: '背面四分之三', labelEn: 'Rear three-quarter view' },
      { key: 'back', order: 5, angleDegrees: 180, labelZh: '背面', labelEn: 'Back view' },
    ],
  },
  project: {}, assumptions: [], risks: [], rawText: '服务端原文',
  characters: [{
    characterId: 'character-0123456789abcdef', name: '沈知微', role: '女主角', description: '', identity: '侦探学徒', voiceId: '', colors: [], states: [], sheetUrl: null,
    assetState: 'READY',
    views: ['front', 'front_three_quarter', 'profile', 'rear_three_quarter', 'back'].map((key, index) => ({ key, order: index + 1, imageUrl: `/media/${key}.png`, available: true })),
    quality: { passed: true, paletteSimilarity: 0.94, uniqueViewHashes: 5, entropy: [], issues: [] },
  }],
};

const props = {
  taskId: 'task-3',
  onRefresh: vi.fn(),
  onRegenerate: vi.fn(),
  onContinue: vi.fn(),
};

describe('CharacterDesignerPageContainer', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('loads the backend dashboard contract and resolves relative media URLs', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, json: async () => response } as Response);
    render(<CharacterDesignerPageContainer {...props} />);

    expect(await screen.findByRole('heading', { level: 1, name: '沈知微' })).toBeTruthy();
    expect(screen.getByAltText('沈知微 正面 0度').getAttribute('src')).toBe('http://localhost:8000/media/front.png');
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith(
      'http://localhost:8000/api/drama/task-3/character-dashboard',
      expect.objectContaining({ credentials: 'include' }),
    ));
  });

  it('falls back to legacy task assets when the backend is unavailable', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('offline'));
    render(
      <CharacterDesignerPageContainer
        {...props}
        fallbackSheets={{ 陆行远: 'https://img.test/sheet.png' }}
        fallbackDna={{ characters: [{ name: '陆行远', identity: '巡警' }] }}
        fallbackRaw="旧版角色原文"
      />,
    );

    expect(screen.getAllByText('陆行远').length).toBeGreaterThan(0);
    expect((await screen.findByRole('status')).textContent).toContain('任务内嵌资产');
    expect(screen.getByLabelText('五视图已完成 0 / 5')).toBeTruthy();
  });

  it('does not render malicious media URLs from an offline legacy fallback', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('offline'));
    const { container } = render(
      <CharacterDesignerPageContainer
        {...props}
        fallbackCharacters={[{
          name: '旧任务危险角色',
          sheet: 'javascript:alert(1)',
          views: [
            { key: 'front', imageUrl: 'data:image/svg+xml,<svg onload=alert(1)/>' },
            { key: 'profile', imageUrl: '/media/%252e%252e/private.png' },
          ],
        }]}
        fallbackSheets={{ 旧任务危险角色: 'https://user:secret@img.test/sheet.png' }}
      />,
    );

    expect((await screen.findByRole('status')).textContent).toContain('任务内嵌资产');
    expect(screen.getByLabelText('五视图已完成 0 / 5')).toBeTruthy();
    expect(container.querySelectorAll('img')).toHaveLength(0);
  });
});
