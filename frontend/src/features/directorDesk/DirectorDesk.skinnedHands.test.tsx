// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { contactPlan, planResponse } from '../spatial/spatialFixtures';
import type { StageActor, StagePlan } from '../spatial/spatialTypes';
import { DirectorDesk } from './DirectorDesk';
import type { DeskViewportProps } from './three/DeskViewport';
import type { LensViewportProps } from './three/LensViewport';

// What a skinned figure holds goes where the model says its hand is. The model and the locator are
// stand-ins here (humanoidHands.test.ts reads the real file); this is about the desk asking for
// them when it should, using the answer in every view, and giving the model back.

vi.mock('./three/DeskViewport', () => ({
  default: function MockDeskViewport({ plan }: DeskViewportProps) {
    const pen = plan.landmarks.find(item => item.name === '录音笔');
    return <span data-testid="desk-pen">{pen?.position.join(',')}@{pen?.elevation_m}</span>;
  },
}));

vi.mock('./three/LensViewport', () => ({
  default: function MockLensViewport({ plan }: LensViewportProps) {
    return <span data-testid="lens-pen">{plan.landmarks.find(item => item.name === '录音笔')?.position.join(',')}</span>;
  },
}));

const model = vi.hoisted(() => ({ acquire: vi.fn(), release: vi.fn(), asked: [] as string[] }));
vi.mock('./three/figures/humanoidSource', () => ({ acquire: model.acquire, release: model.release }));
vi.mock('./lib/humanoidHands', () => ({
  // The hand swings out to the figure's side as its clip runs on: 1 m at the start, 2 m by the end.
  humanoidHandLocator: () => (actor: StageActor, hand: string) => {
    if (actor.figure !== 'humanoid') return null;
    model.asked.push(`${actor.name}/${hand}/${actor.pose?.clip ?? ''}`);
    return [actor.position[0] + 1 + (actor.pose?.clip_phase ?? 0), 1.3, actor.position[1]];
  },
}));

vi.mock('./elementLibraryApi', () => ({
  listModelElements: vi.fn(() => Promise.resolve([])),
  importModelElement: vi.fn(),
  modelRefusal: vi.fn(() => ''),
}));

function json(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }));
}

describe('DirectorDesk: what a skinned figure holds', () => {
  let stage: StagePlan;

  const serve = () => vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    if (String(input).includes('/director-desk/') || String(input).includes('/repairs')) return json({ captures: [], applied: {}, repairs: [], operations: [], revision: stage.revision });
    return json(planResponse({}, stage));
  }));

  beforeEach(() => {
    window.localStorage.clear();
    window.innerHeight = 900;
    model.asked.length = 0;
    model.acquire.mockReset().mockResolvedValue({ scene: {}, clips: [], height: 1.8, floor: 0 });
    model.release.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('draws the held prop in the model’s hand, in the director view and through the lens, and gives the model back on the way out', async () => {
    const base = contactPlan();
    stage = { ...base, actors: base.actors.map(actor => (actor.name === '林夏' ? { ...actor, figure: 'humanoid' as const } : actor)) };
    serve();
    const { unmount } = render(<DirectorDesk taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    // 林夏 stands at (-1.3, 0): the stand-in hand is 1 m to the side at 1.3 m, and the pen is 0.04 m tall.
    await waitFor(() => expect(screen.getByTestId('desk-pen').textContent).toBe('-0.3,0@1.28'));
    expect(screen.getByTestId('lens-pen').textContent).toBe('-0.3,0');
    expect(model.acquire).toHaveBeenCalledTimes(1);
    // Nobody has given her a motion: the locator is handed the actor as she stands, and reads her posture's clip itself.
    expect(model.asked[0]).toBe('林夏/right/');
    expect(model.release).not.toHaveBeenCalled();
    unmount();
    expect(model.release).toHaveBeenCalledTimes(1);
  });

  it('does not fetch the model for a figure with no skin, and keeps the formula hand when the model cannot be had', async () => {
    stage = contactPlan();
    serve();
    const first = render(<DirectorDesk taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByTestId('desk-pen').textContent).toBe('-1.12,0.22@0.779'));
    expect(model.acquire).not.toHaveBeenCalled();
    first.unmount();

    const base = contactPlan();
    stage = { ...base, actors: base.actors.map(actor => (actor.name === '林夏' ? { ...actor, figure: 'humanoid' as const } : actor)) };
    model.acquire.mockRejectedValue(new Error('offline'));
    serve();
    render(<DirectorDesk taskId="t1" sceneId="E1S01" onClose={() => {}} />);
    await waitFor(() => expect(model.release).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId('desk-pen').textContent).toBe('-1.12,0.22@0.779');
  });
});
