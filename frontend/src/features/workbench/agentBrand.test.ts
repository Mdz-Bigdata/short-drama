import { describe, expect, it } from 'vitest';

import { NOVARA_AGENT_NAME } from './agentBrand';


describe('workbench agent brand', () => {
  it('uses the Novara AI name', () => {
    expect(NOVARA_AGENT_NAME).toBe('Novara AI');
  });
});
