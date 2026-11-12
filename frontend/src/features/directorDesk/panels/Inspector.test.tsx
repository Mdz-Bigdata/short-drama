// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PLAN } from '../../spatial/spatialFixtures';
import type { StagePlan } from '../../spatial/spatialTypes';
import type { EditRequest, SelectionRef } from '../deskTypes';
import { Inspector } from './Inspector';

vi.mock('../elementLibraryApi', () => ({
  listModelElements: vi.fn(() => Promise.resolve([])),
  importModelElement: vi.fn(),
  modelRefusal: vi.fn(() => ''),
}));

const STAGE: StagePlan = {
  ...PLAN,
  landmarks: [...PLAN.landmarks, { id: 'mark-02', name: '方桌', kind: 'prop', position: [1, -1], size: [1, 1, 0.75] }],
};

describe('Inspector', () => {
  const onCommit = vi.fn<(request: EditRequest) => void>();
  const onSelect = vi.fn();
  const show = (plan: StagePlan, selection: SelectionRef[]) => (
    <Inspector plan={plan} shot={plan.shots[0]} selection={selection} editable error="" taskId="t1" onCommit={onCommit} onSelect={onSelect} />
  );

  afterEach(() => {
    cleanup();
    onCommit.mockReset();
    onSelect.mockReset();
  });

  it('drops the note about a taken name when another piece is picked', async () => {
    const { rerender } = render(show(STAGE, [{ kind: 'landmark', name: '录音笔' }]));
    const name = screen.getByLabelText('名称') as HTMLInputElement;
    await userEvent.clear(name);
    await userEvent.type(name, '方桌{Enter}');
    expect(screen.getByText('场上已经有「方桌」')).toBeTruthy();
    expect(onCommit).not.toHaveBeenCalled();
    // The taken name stays where it was typed, so one character can be changed.
    expect(name.value).toBe('方桌');

    rerender(show(STAGE, [{ kind: 'landmark', name: '方桌' }]));
    expect(screen.queryByText('场上已经有「方桌」')).toBeNull();
    expect((screen.getByLabelText('名称') as HTMLInputElement).value).toBe('方桌');
  });

  it('renames on Enter and keeps focus in the name, which now shows the new one', async () => {
    const { rerender } = render(show(STAGE, [{ kind: 'landmark', name: '录音笔' }]));
    const name = screen.getByLabelText('名称') as HTMLInputElement;
    await userEvent.clear(name);
    await userEvent.type(name, '笔{Enter}');
    expect(onCommit.mock.calls[0][0].operations.map(item => item.op)).toEqual(['remove_landmark', 'add_landmark']);
    expect(onSelect).toHaveBeenCalledWith({ kind: 'landmark', name: '笔' }, false);

    const renamed: StagePlan = { ...STAGE, landmarks: STAGE.landmarks.map(item => (item.name === '录音笔' ? { ...item, id: 'pending-笔', name: '笔' } : item)) };
    rerender(show(renamed, [{ kind: 'landmark', name: '笔' }]));
    expect(screen.getByLabelText('名称')).toBe(name);
    expect(document.activeElement).toBe(name);
    expect(name.value).toBe('笔');
    fireEvent.blur(name);
    expect(onCommit).toHaveBeenCalledTimes(1);
  });
});
