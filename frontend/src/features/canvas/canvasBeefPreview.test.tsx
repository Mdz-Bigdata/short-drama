// @vitest-environment jsdom
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { MediaPreview } from './CanvasNodeCard';

afterEach(cleanup);

describe('MediaPreview with a preview copy', () => {
  it('plays the H.264 copy of an upload and the original otherwise', () => {
    const { container, rerender } = render(<MediaPreview output={{ medium: 'video', url: '/media/canvas_up_a.mp4', preview_url: '/media/canvas_up_a.preview.mp4' }} />);
    expect(container.querySelector('video')!.getAttribute('src')).toContain('/media/canvas_up_a.preview.mp4');
    rerender(<MediaPreview output={{ medium: 'video', url: '/media/canvas_up_b.mp4' }} />);
    expect(container.querySelector('video')!.getAttribute('src')).toContain('/media/canvas_up_b.mp4');
  });
});
