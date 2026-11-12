// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';

import { loadWebFonts } from './webFonts';


describe('loadWebFonts', () => {
  afterEach(() => {
    document.head.querySelectorAll('link[data-web-fonts]').forEach(link => link.remove());
  });

  it('attaches the brand font stylesheet from script, so it cannot block the first paint', () => {
    loadWebFonts();

    const stylesheet = document.head.querySelector<HTMLLinkElement>('link[rel="stylesheet"][data-web-fonts]');
    expect(stylesheet?.href).toContain('fonts.googleapis.com');
    expect(stylesheet?.href).toContain('Outfit');
    expect(stylesheet?.href).toContain('Noto+Sans+SC');
    expect(stylesheet?.href).toContain('display=swap');
    expect(document.head.querySelector<HTMLLinkElement>('link[rel="preconnect"][data-web-fonts]')?.href).toContain('fonts.gstatic.com');
  });

  it('attaches them once however often it is called', () => {
    loadWebFonts();
    loadWebFonts();

    expect(document.head.querySelectorAll('link[rel="stylesheet"][data-web-fonts]')).toHaveLength(1);
  });
});
