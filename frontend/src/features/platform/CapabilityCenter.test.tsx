// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CapabilityCenter } from './CapabilityCenter';


const response = {
  total: 1,
  items: [{
    source_id: 'minimax-h3-skills',
    source_url: 'https://example.test/minimax',
    enabled_count: 1,
    abilities: [{
      id: 'multi-reference-video',
      label: 'multi-reference video',
      command: '/minimax-h3-skills.multi-reference-video',
      entrypoint: '/api/production/video/minimax-h3',
      enabled: true,
    }],
  }],
};


describe('CapabilityCenter', () => {
  afterEach(() => vi.restoreAllMocks());

  it('expands every ability, exposes slash command, and lets an admin toggle it', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => response,
    } as Response);
    render(<CapabilityCenter role="admin" />);

    await userEvent.click(await screen.findByRole('button', { name: /minimax-h3-skills/i }));
    expect(screen.getByText('/minimax-h3-skills.multi-reference-video')).toBeTruthy();
    await userEvent.click(screen.getByRole('switch', { name: /multi-reference video/i }));
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/platform/capabilities/minimax-h3-skills/multi-reference-video'),
      expect.objectContaining({ method: 'PATCH' }),
    );
  });
});
