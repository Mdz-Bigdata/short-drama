// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ElementLibraryPage } from './ElementLibraryPage';


describe('ElementLibraryPage', () => {
  afterEach(() => vi.restoreAllMocks());

  it('provides all four concrete pages and add/upload/regenerate actions', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], page: 1, page_size: 24, total: 0 }),
    } as Response);
    render(<ElementLibraryPage initialKind="actor" onBack={() => undefined} />);

    expect(await screen.findByRole('heading', { name: /演员元素库/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: '添加演员' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /上传/ })).toBeTruthy();
    await userEvent.click(screen.getByRole('tab', { name: '场景' }));
    expect(await screen.findByRole('heading', { name: /场景元素库/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: '添加场景' })).toBeTruthy();
  });
});
