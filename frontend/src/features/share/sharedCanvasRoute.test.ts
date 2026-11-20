import { describe, expect, it } from 'vitest';

import { sharedCanvasToken } from './sharedCanvasRoute';

describe('sharedCanvasToken', () => {
  it('reads the token from a share link', () => {
    expect(sharedCanvasToken('/share/canvas/abcDEF0123456789')).toBe('abcDEF0123456789');
    expect(sharedCanvasToken(`/share/canvas/${'a_-'.repeat(21)}x`)).toBe(`${'a_-'.repeat(21)}x`);
  });

  it('leaves every other path to the app', () => {
    expect(sharedCanvasToken('/')).toBeNull();
    expect(sharedCanvasToken('/share/canvas/')).toBeNull();
    expect(sharedCanvasToken('/share/canvas/short')).toBeNull();
    expect(sharedCanvasToken(`/share/canvas/${'a'.repeat(65)}`)).toBeNull();
    expect(sharedCanvasToken('/share/canvas/abcDEF0123456789/')).toBeNull();
    expect(sharedCanvasToken('/share/canvas/abcDEF01234567.9')).toBeNull();
    expect(sharedCanvasToken('/x/share/canvas/abcDEF0123456789')).toBeNull();
    expect(sharedCanvasToken('/share/board/abcDEF0123456789')).toBeNull();
  });
});
