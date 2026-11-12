// @vitest-environment jsdom
import { useState } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { StagePlan } from '../../spatial/spatialTypes';
import type { EditRequest } from '../deskTypes';
import { CameraPanel } from './CameraPanel';

const ALT = { ...PLAN.cameras[0], id: 'alt-01-01', label: '过肩', lens_mm: 50 };
const ALT2 = { ...PLAN.cameras[0], id: 'alt-01-02', label: '俯拍', lens_mm: 35 };
const WITH_CANDIDATES: StagePlan = {
  ...PLAN,
  cameras: [...PLAN.cameras, ALT, ALT2],
  shots: [{ ...PLAN.shots[0], alt_camera_ids: ['alt-01-01', 'alt-01-02'] }, ...PLAN.shots.slice(1)],
};
const GUIDES = { aspect: '', frame: true, thirds: false, safe: false, cross: false };

// Applies each edit the way the desk does after the server answers, so the pressed button really goes away.
function Harness({ refuse = false, onCommit }: { refuse?: boolean; onCommit?: (request: EditRequest) => void }) {
  const [plan, setPlan] = useState(WITH_CANDIDATES);
  const shot = plan.shots[0];
  const commit = (request: EditRequest) => {
    onCommit?.(request);
    if (refuse) return;
    const [operation] = request.operations;
    if (operation.op === 'remove_camera') {
      setPlan(current => ({ ...current, shots: current.shots.map((item, index) => index ? item : { ...item, alt_camera_ids: item.alt_camera_ids?.filter(id => id !== operation.camera_id) }) }));
    } else if (operation.op === 'use_camera') {
      setPlan(current => ({ ...current, shots: current.shots.map((item, index) => index ? item : {
        ...item, camera_id: String(operation.camera_id), alt_camera_ids: [item.camera_id, ...(item.alt_camera_ids || []).filter(id => id !== operation.camera_id)],
      }) }));
    }
  };
  return (
    <CameraPanel
      plan={plan} shot={shot} lens={plan.cameras.find(camera => camera.id === shot.camera_id)} guides={GUIDES} editable canUseView backdrop={null}
      onCommit={commit} onPreview={vi.fn()} onLook={vi.fn()} onAddFromView={vi.fn()} onAddPreset={vi.fn()} onGuides={vi.fn()}
    />
  );
}

afterEach(cleanup);

describe('CameraPanel focus', () => {
  it('puts focus on the lens that took a deleted candidate\'s row, not on the page', async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole('button', { name: '删除 过肩' }));
    expect(screen.queryByRole('button', { name: '删除 过肩' })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '查看 俯拍' }));
  });

  it('falls back to the last row when the last candidate is deleted', async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole('button', { name: '删除 俯拍' }));
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '查看 过肩' }));
  });

  it('follows a promoted candidate to its new row', async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole('button', { name: '将 过肩 设为主机位' }));
    expect(screen.queryByRole('button', { name: '将 过肩 设为主机位' })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '查看 过肩' }));
  });

  it('leaves focus alone when the edit is refused', async () => {
    const commits: EditRequest[] = [];
    render(<Harness refuse onCommit={request => commits.push(request)} />);
    const remove = screen.getByRole('button', { name: '删除 过肩' });
    await userEvent.click(remove);
    expect(commits).toHaveLength(1);
    expect(document.activeElement).toBe(remove);
  });
});
