// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { contactPlan, planResponse } from '../spatial/spatialFixtures';
import type { StagePlan } from '../spatial/spatialTypes';
import { applyAll } from './deskOperations';
import { DirectorDesk } from './DirectorDesk';
import type { DeskViewportProps } from './three/DeskViewport';
import type { LensViewportProps } from './three/LensViewport';

const REFUSAL = '「录音笔」在林夏右手里：先解除接触再单独移动';

// The viewports are the three.js boundary: these stand-ins show where the recorder is drawn, and
// play the gizmo's part — a drag of 林夏 in progress, and a drag of the held recorder being refused.
vi.mock('./three/DeskViewport', () => ({
  default: function MockDeskViewport({ plan, locked, onPreview, onRefuse }: DeskViewportProps) {
    const pen = plan.landmarks.find(item => item.name === '录音笔');
    return (
      <div data-testid="desk-viewport" data-locked={locked.join(',')}>
        <span data-testid="desk-pen">{pen?.position.join(',')}@{pen?.elevation_m}</span>
        <button type="button" onClick={() => onPreview([{ op: 'move_actor', name: '林夏', position: [0.5, 1] }])}>drag 林夏</button>
        <button type="button" onClick={() => onRefuse?.(REFUSAL)}>drag 录音笔</button>
      </div>
    );
  },
}));

vi.mock('./three/LensViewport', () => ({
  default: function MockLensViewport({ plan }: LensViewportProps) {
    return <span data-testid="lens-pen">{plan.landmarks.find(item => item.name === '录音笔')?.position.join(',')}</span>;
  },
}));

vi.mock('./elementLibraryApi', () => ({
  listModelElements: vi.fn(() => Promise.resolve([])),
  importModelElement: vi.fn(),
  modelRefusal: vi.fn(() => ''),
}));

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

describe('DirectorDesk contacts', () => {
  const fetchMock = vi.fn();
  let stage: StagePlan;
  const patches = () => fetchMock.mock.calls
    .filter(call => (call[1] as RequestInit | undefined)?.method === 'PATCH')
    .map(call => JSON.parse(String((call[1] as RequestInit).body)) as { operations: Array<Record<string, unknown>> });

  beforeEach(() => {
    stage = contactPlan();
    window.localStorage.clear();
    window.innerHeight = 900;
    fetchMock.mockReset();
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes('/director-desk/') || String(input).includes('/repairs')) return json({ captures: [], applied: {}, repairs: [], operations: [], revision: stage.revision });
      if (init?.method === 'PATCH') {
        const { operations } = JSON.parse(String(init.body)) as { operations: Array<{ op: string }> };
        stage = { ...applyAll(stage, operations), revision: stage.revision + 1 };
      }
      return json(planResponse({}, stage));
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('draws the held prop in the hand in every view, and it follows the holder through a drag even when locked', async () => {
    render(<DirectorDesk taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    await screen.findByTestId('desk-viewport');
    expect(screen.getByTestId('desk-pen').textContent).toBe('-1.12,0.22@0.779');
    expect(screen.getByTestId('lens-pen').textContent).toBe('-1.12,0.22');

    const outline = screen.getByRole('complementary', { name: '场景大纲' });
    expect(within(outline).getByText('立方体 · 在林夏右手里')).toBeTruthy();
    await userEvent.click(within(outline).getByRole('button', { name: '锁定 录音笔' }));
    expect(screen.getByTestId('desk-viewport').dataset.locked).toBe('landmark:录音笔');

    await userEvent.click(screen.getByRole('button', { name: 'drag 林夏' }));
    expect(screen.getByTestId('desk-pen').textContent).toBe('0.68,1.22@0.779');
    expect(screen.getByTestId('lens-pen').textContent).toBe('0.68,1.22');
    expect(patches()).toHaveLength(0);
  });

  it('says why a held prop will not be dragged on its own', async () => {
    render(<DirectorDesk taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    await screen.findByTestId('desk-viewport');
    await userEvent.click(screen.getByRole('button', { name: 'drag 录音笔' }));
    expect(screen.getByText(REFUSAL).closest('[role="alert"]')).toBeTruthy();
    expect(patches()).toHaveLength(0);
  });

  it('changes the hand from the inspector through one PATCH, and undoes it', async () => {
    render(<DirectorDesk taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    await screen.findByTestId('desk-viewport');
    await userEvent.click(within(screen.getByRole('complementary', { name: '场景大纲' })).getByRole('button', { name: /^录音笔/ }));
    await userEvent.selectOptions(within(screen.getByRole('region', { name: '接触' })).getByLabelText('哪只手'), 'left');
    await waitFor(() => expect(patches()).toHaveLength(1));
    expect(patches()[0].operations).toEqual([{ op: 'set_contact', kind: 'hold', actor: '林夏', target: '录音笔', hand: 'left', shot_ids: [] }]);
    await waitFor(() => expect(screen.getByTestId('desk-pen').textContent).toBe('-1.12,-0.22@0.779'));

    await screen.findByText(/已保存 · 第 4 版/);
    await userEvent.click(screen.getByRole('button', { name: '撤销' }));
    await waitFor(() => expect(patches()).toHaveLength(2));
    // Off the target, the stored place the whole-scene hold baked put back, then the right hand again.
    expect(patches()[1].operations).toEqual([
      { op: 'remove_contact', target: '录音笔' },
      { op: 'transform_landmark', name: '录音笔', position: [0, -0.9], elevation_m: 0, yaw_deg: 0 },
      { op: 'set_contact', kind: 'hold', actor: '林夏', target: '录音笔', support: '', hand: 'right', shot_ids: [] },
    ]);
    await waitFor(() => expect(screen.getByTestId('desk-pen').textContent).toBe('-1.12,0.22@0.779'));
  });
});
