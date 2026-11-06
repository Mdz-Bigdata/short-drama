// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import PanoramaViewer from './PanoramaViewer';

describe('PanoramaViewer', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it('falls back to the flat picture where WebGL is missing', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    render(<PanoramaViewer url="http://x/p.jpg" alt="客厅" />);
    expect(screen.getByRole('img', { name: '客厅' }).getAttribute('src')).toBe('http://x/p.jpg');
  });
});
