// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { VideoReferenceModeSelect } from './VideoReferenceModeSelect';


describe('VideoReferenceModeSelect', () => {
  afterEach(cleanup);

  it('offers auto routing plus the three supported generation modes', () => {
    render(<VideoReferenceModeSelect value="auto" onChange={() => undefined} />);

    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(4);
    expect(options.map(option => (option as HTMLOptionElement).value)).toEqual([
      'auto',
      'first_last_frame',
      'multi_reference',
      'multimodal',
    ]);
    expect(screen.queryByRole('option', { name: '首帧驱动' })).toBeNull();
  });

  it('shows the model families for every supported reference strategy', () => {
    render(<VideoReferenceModeSelect value="auto" onChange={() => undefined} />);

    expect(screen.getAllByText(/Seedance 2 \/ 2\.5 · MiniMax H3 · Kling/)).toHaveLength(3);
    expect(screen.getByText(/Grok · HappyHorse · Seedance 2 \/ 2\.5 · MiniMax H3 · Kling · LTX 2\.3/)).toBeTruthy();
    expect(screen.getByText(/参考图片、视频或音频/)).toBeTruthy();
  });

  it('reports the selected strategy to the parent', () => {
    const onChange = vi.fn();
    render(<VideoReferenceModeSelect value="auto" onChange={onChange} />);

    fireEvent.change(screen.getByLabelText('运镜视频参考方式'), {
      target: { value: 'multi_reference' },
    });

    expect(onChange).toHaveBeenCalledWith('multi_reference');
  });
});
