// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { contactPlan } from '../../spatial/spatialFixtures';
import type { SpatialRepairsResponse, StagePlan } from '../../spatial/spatialTypes';
import { ChecksPanel } from './ChecksPanel';

// The check and its repair come from the server; the panel shows any code it is handed the same way.
const SETTLE = [{ op: 'set_contact', kind: 'hold', actor: '林夏', target: '录音笔', hand: 'right', shot_ids: [] }];
const PLAN: StagePlan = contactPlan({
  checks: [{ code: 'spatial_contact_kept', passed: false, severity: 'warning', detail: '第1镜的录音笔离林夏的右手有 0.6 米，没拿在手里。', shot_ids: [1] }],
});
const REPAIRS: SpatialRepairsResponse = {
  schemaVersion: 'spatial-stage.v1', taskId: 't1', sceneId: 'E1S01', revision: 3,
  repairs: [{ code: 'spatial_contact_kept', label: '贴合接触', detail: '把录音笔放回林夏右手', shotIds: [1], operations: SETTLE, manual: '', automatic: true }],
  operations: SETTLE, automatic: 1, manual: 0,
};

describe('ChecksPanel with a contact check', () => {
  const onCommit = vi.fn();

  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify(REPAIRS), { status: 200, headers: { 'Content-Type': 'application/json' } }))));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    onCommit.mockReset();
  });

  it('shows the contact warning and offers 「贴合接触」 as its repair', async () => {
    render(<ChecksPanel taskId="t1" sceneId="E1S01" plan={PLAN} shotId={1} editable saving={false} onCommit={onCommit} onSelectShot={vi.fn()} />);
    const item = screen.getByRole('listitem');
    expect(item.className).toContain('is-warning');
    expect(within(item).getByText(/录音笔离林夏的右手/)).toBeTruthy();
    await userEvent.click(await within(item).findByRole('button', { name: '修正' }));
    expect(within(item).getByText('贴合接触 · 把录音笔放回林夏右手')).toBeTruthy();
    expect(onCommit).toHaveBeenCalledWith({ label: '修正：贴合接触', operations: SETTLE, barrier: true });
  });
});
