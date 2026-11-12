// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { DeliveryChecklist } from './DeliveryChecklist';

afterEach(cleanup);

describe('DeliveryChecklist', () => {
  it('names the shot, the rule and why, and says so when nothing needs fixing', () => {
    const { rerender } = render(<DeliveryChecklist issues={[
      { shot_uid: 100401, scene_id: 'E1S04', shot_id: 1, rule: 'dialogue', detail: '台词约需 12 秒，这一镜只有 8 秒' },
      { shot_uid: null, scene_id: '', shot_id: null, rule: 'few_sizes', detail: '整条成片只用了中景' },
    ]} />);
    const items = screen.getAllByRole('listitem').map(item => item.textContent);
    expect(items[0]).toContain('E1S04 第1镜');
    expect(items[0]).toContain('台词放不下');
    expect(items[1]).toContain('整条成片');
    rerender(<DeliveryChecklist issues={[]} />);
    expect(screen.getByRole('status').textContent).toContain('没发现要改的镜头');
  });
});
