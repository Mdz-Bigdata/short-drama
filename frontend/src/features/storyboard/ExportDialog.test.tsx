// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiRequest } from '../../api/client';
import { ExportDialog } from './ExportDialog';

vi.mock('../../api/client', async importOriginal => ({
  ...await importOriginal<typeof import('../../api/client')>(),
  apiRequest: vi.fn(),
}));

const mocked = vi.mocked(apiRequest);

describe('ExportDialog', () => {
  beforeEach(() => {
    mocked.mockReset();
    mocked.mockResolvedValue({ text: '第 1 包', plan: { packages: [], total_seconds: 15, warnings: [] } } as never);
  });
  afterEach(cleanup);

  it('mounts on the page root, above the workspace, and closes on Escape', async () => {
    const onClose = vi.fn();
    const { container } = render(<ExportDialog taskId="t1" sceneId="E1S01" kind="packages" onClose={onClose} />);

    const dialog = screen.getByRole('dialog', { name: '提示词分包' });
    expect(await screen.findByText('第 1 包')).toBeTruthy();
    expect(container.contains(dialog)).toBe(false);
    expect(dialog.parentElement).toBe(document.body);

    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
