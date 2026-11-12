// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ShotControlTable } from './ShotControlTable';

afterEach(cleanup);

describe('ShotControlTable', () => {
  it('lists what controls each job and opens itself when something clashes or is missing', () => {
    const { container, rerender } = render(<ShotControlTable rows={[
      { aspect: 'motion', label: '动作与运镜', sources: ['导演台白模视频', '附加的参考视频'], status: 'duplicate', note: '动作同时有 2 份视频参考' },
      { aspect: 'look', label: '人物外观', sources: ['角色参考图（谢九）'], status: 'ok', note: '' },
      { aspect: 'rhythm', label: '节奏', sources: [], status: 'none', note: '' },
    ]} />);
    expect((container.querySelector('details') as HTMLDetailsElement).open).toBe(true);
    expect(screen.getByText('1 项要看')).toBeTruthy();
    expect(screen.getByRole('row', { name: /动作与运镜/ }).textContent).toContain('重复');
    expect(screen.getByRole('row', { name: /节奏/ }).textContent).toContain('—');
    rerender(<ShotControlTable rows={[{ aspect: 'look', label: '人物外观', sources: ['角色参考图（谢九）'], status: 'ok', note: '' }]} />);
    expect((container.querySelector('details') as HTMLDetailsElement).open).toBe(false);
    rerender(<ShotControlTable rows={[]} />);
    expect(container.innerHTML).toBe('');
  });
});
