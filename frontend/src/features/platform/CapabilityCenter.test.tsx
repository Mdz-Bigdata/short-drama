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
    reviewed_commit: '6da473b48daf91e5aebfb56451f8a0b116348df5',
    reviewed_at: '2026-08-15',
    license_observation: 'API interoperability only.',
    code_treatment: 'api-interoperability',
    attribution: 'MiniMax-AI/MiniMax-H3',
    enabled_count: 1,
    abilities: [{
      id: 'multi-reference-video',
      label: 'multi-reference video',
      command: '/minimax-h3-skills.multi-reference-video',
      entrypoint: '/api/production/video/minimax-h3',
      implementation_status: 'provider-dependent',
      evidence: 'backend/tests/test_provider_clients.py',
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
    expect(screen.getByText(/审计 2026-08-15 · 6da473b/)).toBeTruthy();
    expect(screen.getByText(/API interoperability only/)).toBeTruthy();
    await userEvent.click(screen.getByRole('switch', { name: /multi-reference video/i }));
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/platform/capabilities/minimax-h3-skills/multi-reference-video'),
      expect.objectContaining({ method: 'PATCH' }),
    );
  });
});
