// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { HistoryStrip } from './CanvasPanels';
import { deleteRun, fetchNodeHistory, restoreRun } from './canvasApi';
import type { NodeHistory, NodeRun } from './canvasTypes';

vi.mock('./canvasApi', () => ({
  fetchNodeHistory: vi.fn(),
  restoreRun: vi.fn(),
  deleteRun: vi.fn(),
  listVersions: vi.fn(),
}));

function run(id: string, minute: number, extra: Partial<NodeRun> = {}): NodeRun {
  return {
    id, node_id: 'n1', batch_id: 'b', medium: 'image', status: 'done', model: `model-${id}`, request: {},
    output: { medium: 'image', url: `/media/${id}.png` }, error: null, created_at: `2026-11-01T10:0${minute}:00Z`, ...extra,
  };
}

const history: NodeHistory = {
  node_id: 'n1',
  active_run_id: 'r1',
  runs: [run('r1', 1), run('r2', 2), run('r3', 3), run('r4', 4, { status: 'failed', output: null, error: '超时' })],
};

beforeEach(() => {
  vi.mocked(fetchNodeHistory).mockResolvedValue(history);
  vi.mocked(restoreRun).mockResolvedValue({ ...history, active_run_id: 'r3' });
  vi.mocked(deleteRun).mockResolvedValue({ ...history, runs: history.runs.slice(1) });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function setup() {
  const onChanged = vi.fn();
  render(<HistoryStrip projectId="p" canvasId="c" nodeId="n1" onChanged={onChanged} />);
  await screen.findByRole('button', { name: '对比' });
  return { onChanged };
}

const picks = () => screen.queryAllByRole('button', { name: /选来对比|对比 [AB]/ });
const pressed = () => picks().filter(button => button.getAttribute('aria-pressed') === 'true').map(button => button.querySelector('.ccd-badge')?.textContent);
/** Each pickable run's slot, in list order ('' when not picked). */
const slots = () => picks().map(button => button.querySelector('.ccd-badge')?.textContent ?? '');

describe('HistoryStrip', () => {
  it('still restores and deletes outside compare mode', async () => {
    const { onChanged } = await setup();
    expect(picks()).toHaveLength(0);
    fireEvent.click(screen.getAllByRole('button', { name: '恢复' })[0]);
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(restoreRun).toHaveBeenCalledWith('p', 'c', 'n1', 'r2');
    fireEvent.click(screen.getAllByRole('button', { name: '删除这次生成' })[0]);
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(2));
    expect(deleteRun).toHaveBeenCalledWith('p', 'c', 'n1', 'r1');
  });

  it('picks A then B, and a third pick replaces the older one', async () => {
    await setup();
    fireEvent.click(screen.getByRole('button', { name: '对比' }));
    // Only finished runs with a result can be picked.
    expect(picks()).toHaveLength(3);
    const compare = screen.getByRole('button', { name: '并排对比' }) as HTMLButtonElement;
    expect(compare.disabled).toBe(true);
    const [first, second, third] = picks();
    fireEvent.click(first);
    fireEvent.click(second);
    expect(pressed()).toEqual(['A', 'B']);
    expect(compare.disabled).toBe(false);
    expect(slots()).toEqual(['A', 'B', '']);
    fireEvent.click(third);
    // A was the older pick, so the third run takes its slot and B stays.
    expect(slots()).toEqual(['', 'B', 'A']);
    // Now B is the older one.
    fireEvent.click(first);
    expect(slots()).toEqual(['B', '', 'A']);
    // Clicking a picked run unpicks it.
    fireEvent.click(picks()[2]);
    expect(slots()).toEqual(['B', '', '']);
    expect(compare.disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: '对比' }));
    expect(picks()).toHaveLength(0);
  });

  it('opens the dialog on the two picks and restores the chosen one through the history API', async () => {
    const { onChanged } = await setup();
    fireEvent.click(screen.getByRole('button', { name: '对比' }));
    const [first, , third] = picks();
    fireEvent.click(first);
    fireEvent.click(third);
    fireEvent.click(screen.getByRole('button', { name: '并排对比' }));
    const dialog = screen.getByRole('dialog', { name: '对比生成结果' });
    expect(within(dialog).getByText('当前')).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: '用 B 这一版' }));
    expect(restoreRun).toHaveBeenCalledWith('p', 'c', 'n1', 'r3');
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(picks()).toHaveLength(0);
  });

  it('closes the dialog with Esc and keeps the picks', async () => {
    await setup();
    fireEvent.click(screen.getByRole('button', { name: '对比' }));
    fireEvent.click(picks()[0]);
    fireEvent.click(picks()[1]);
    fireEvent.click(screen.getByRole('button', { name: '并排对比' }));
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(pressed()).toEqual(['A', 'B']);
  });
});
