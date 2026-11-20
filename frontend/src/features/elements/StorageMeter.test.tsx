// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ASSETS_CHANGED_EVENT } from './assetEvents';
import { StorageMeter } from './StorageMeter';
import { formatBytes } from './storageFormat';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function serve(...answers: Array<Record<string, unknown> | 'fail'>) {
  let call = 0;
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
    const answer = answers[Math.min(call, answers.length - 1)];
    call += 1;
    if (answer === 'fail') return { ok: false, status: 500, json: async () => ({ detail: 'down' }) } as Response;
    return { ok: true, status: 200, json: async () => answer } as Response;
  });
}

const usage = (over: Record<string, unknown> = {}) => ({
  used_bytes: 1536 * 1024, quota_bytes: 5 * 1024 ** 3, remaining_bytes: 5 * 1024 ** 3 - 1536 * 1024,
  asset_count: 12, asset_quota: 1000, remaining_assets: 988, share: 0.012, level: 'ok', ...over,
});

describe('formatBytes', () => {
  it('writes a size in the largest unit that keeps it readable', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(900)).toBe('900 B');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(15 * 1024 ** 2)).toBe('15 MB');
    expect(formatBytes(5 * 1024 ** 3)).toBe('5 GB');
    expect(formatBytes(-4)).toBe('0 B');
  });
});

describe('StorageMeter', () => {
  it('shows what is used of the limits and how many assets are held', async () => {
    serve(usage());
    render(<StorageMeter />);
    expect(await screen.findByText('已用 1.5 MB / 共 5 GB')).toBeTruthy();
    expect(screen.getByText('资产 12 / 1000 个')).toBeTruthy();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('1');
    expect(screen.getByRole('group').className).toContain('storage-meter--ok');
  });

  it('turns to danger when the library is nearly full and reads again after an asset changes', async () => {
    const fetchMock = serve(usage({ share: 0.75, level: 'warning' }), usage({ share: 0.93, level: 'danger' }));
    render(<StorageMeter />);
    await waitFor(() => expect(screen.getByRole('group').className).toContain('storage-meter--warning'));
    window.dispatchEvent(new CustomEvent(ASSETS_CHANGED_EVENT, { detail: { reason: 'image' } }));
    await waitFor(() => expect(screen.getByRole('group').className).toContain('storage-meter--danger'));
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('93');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('stays out of the page when the usage cannot be read', async () => {
    const fetchMock = serve('fail');
    const { container } = render(<StorageMeter />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container.querySelector('.storage-meter')).toBeNull();
  });
});
