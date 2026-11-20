// @vitest-environment jsdom
import { useEffect } from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { StagePlan } from '../../spatial/spatialTypes';
import type { MonitorRendererProps } from '../three/MonitorRenderer';
import { MonitorWall } from './MonitorWall';

// The canvas is three.js; the stand-in "draws" a monitor as a string and records each one it drew.
const drawn = vi.hoisted(() => ({ keys: [] as string[] }));
vi.mock('../three/MonitorRenderer', () => ({
  default: function MockMonitorRenderer({ monitor, onDrawn }: MonitorRendererProps) {
    useEffect(() => {
      if (!monitor) return;
      drawn.keys.push(monitor.key);
      onDrawn(monitor.key, monitor.signature, `data:image/jpeg;base64,${monitor.key}`);
    }, [monitor, onDrawn]);
    return null;
  },
}));

const props = (plan: StagePlan, overrides: Partial<Parameters<typeof MonitorWall>[0]> = {}) => ({
  plan, shotId: 1, now: 0, playing: false, hidden: [], activeLensId: 'cam-01', previewing: false,
  onPickShot: vi.fn(), onPickLens: vi.fn(), onClose: vi.fn(), ...overrides,
});
// A monitor's picture is decoration of a button already named by its caption, so it has no role of its own.
const pictures = () => [...screen.getByRole('list', { name: '本场监视器' }).querySelectorAll('img')].map(img => img.getAttribute('src'));

describe('MonitorWall', () => {
  afterEach(() => {
    cleanup();
    drawn.keys = [];
  });

  it('draws every monitor once, then only the one whose picture changed', async () => {
    const view = render(<MonitorWall {...props(PLAN)} />);
    await waitFor(() => expect(pictures()).toEqual(['data:image/jpeg;base64,shot:1', 'data:image/jpeg;base64,shot:2']));
    expect(drawn.keys).toEqual(['shot:1', 'shot:2']);

    // 助手 is off stage in shot 2, so moving her changes shot 1's picture only.
    const moved = { ...PLAN, actors: PLAN.actors.map(actor => (actor.name === '助手' ? { ...actor, position: [0.5, -2] as [number, number] } : actor)) };
    view.rerender(<MonitorWall {...props(moved)} />);
    await waitFor(() => expect(drawn.keys).toEqual(['shot:1', 'shot:2', 'shot:1']));
  });

  it('marks what the stage is looking through and hands a pick back', async () => {
    const onPickShot = vi.fn();
    render(<MonitorWall {...props(PLAN, { onPickShot })} />);
    const shots = screen.getAllByRole('button', { name: /^第 \d 镜/ });
    expect(shots.map(button => button.getAttribute('aria-pressed'))).toEqual(['true', 'false']);
    await userEvent.click(shots[1]);
    expect(onPickShot).toHaveBeenCalledWith(2);
  });

  it('waits for playback to stop before it catches up', async () => {
    const view = render(<MonitorWall {...props(PLAN, { playing: true })} />);
    await waitFor(() => expect(drawn.keys).toHaveLength(2));
    const moved = { ...PLAN, landmarks: [{ ...PLAN.landmarks[0], position: [1, 1] as [number, number] }] };
    view.rerender(<MonitorWall {...props(moved, { playing: true })} />);
    await new Promise(resolve => { setTimeout(resolve, 400); });
    expect(drawn.keys).toHaveLength(2);
    view.rerender(<MonitorWall {...props(moved, { playing: false })} />);
    await waitFor(() => expect(drawn.keys).toHaveLength(4));
  });
});
