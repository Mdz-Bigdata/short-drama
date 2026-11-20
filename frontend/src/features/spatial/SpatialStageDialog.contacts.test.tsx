// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SpatialStageDialog } from './SpatialStageDialog';
import { contactPlan, planResponse } from './spatialFixtures';
import type { StagePlan } from './spatialTypes';

vi.mock('./three/SpatialStageViewport', () => ({
  default: ({ plan }: { plan: StagePlan }) => <div data-testid="viewport">{plan.landmarks.find(item => item.name === '录音笔')?.position.join(',')}</div>,
}));

describe('SpatialStageDialog with contacts', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockImplementation(() => Promise.resolve(new Response(JSON.stringify(planResponse({}, contactPlan())), { status: 200, headers: { 'Content-Type': 'application/json' } })));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('draws a held prop in the hand and will not move it on its own', async () => {
    render(<SpatialStageDialog taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    const floor = await screen.findByRole('img', { name: 'E1S01 空间调度俯视图' });
    vi.spyOn(floor, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 720, height: 540, right: 720, bottom: 540, x: 0, y: 0, toJSON: () => ({}) });
    const pen = [...floor.querySelectorAll('.spatial-floor__landmark')].find(item => item.textContent === '录音笔') as SVGGElement;
    fireEvent.pointerDown(pen, { clientX: 100, clientY: 100, pointerId: 1 });
    fireEvent.pointerMove(floor, { clientX: 140, clientY: 260, pointerId: 1 });
    fireEvent.pointerUp(floor, { clientX: 140, clientY: 260, pointerId: 1 });
    expect(await screen.findByText('「录音笔」在林夏右手里：先解除接触再单独移动')).toBeTruthy();
    expect(fetchMock.mock.calls.some(call => (call[1] as RequestInit | undefined)?.method === 'PATCH')).toBe(false);

    await userEvent.click(screen.getByRole('tab', { name: /导演视角/ }));
    expect((await screen.findByTestId('viewport')).textContent).toBe('-1.12,0.22');
  });
});
