// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PoetrySourcePicker } from './PoetrySourcePicker';


function serve() {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => ({
    ok: true, status: 200,
    json: async () => ({ items: [
      { collection: 'sushi', author: '苏轼', dynasty: '北宋', count: 25 },
      { collection: 'liqingzhao', author: '李清照', dynasty: '宋', count: 18 },
    ] }),
  }) as Response);
}

describe('PoetrySourcePicker', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('adds and removes authors', async () => {
    serve();
    const onChange = vi.fn();
    render(<PoetrySourcePicker value={['苏轼']} onChange={onChange} />);
    fireEvent.click(await screen.findByLabelText(/李清照/));
    expect(onChange).toHaveBeenLastCalledWith(['苏轼', '李清照']);
    fireEvent.click(screen.getByLabelText(/苏轼/));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it('the whole library replaces single choices and locks them', async () => {
    serve();
    const onChange = vi.fn();
    const { rerender } = render(<PoetrySourcePicker value={['苏轼']} onChange={onChange} />);
    fireEvent.click(await screen.findByLabelText('整个诗词库'));
    expect(onChange).toHaveBeenLastCalledWith(['全部']);
    rerender(<PoetrySourcePicker value={['全部']} onChange={onChange} />);
    expect((screen.getByLabelText(/李清照/) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText(/李清照/) as HTMLInputElement).checked).toBe(true);
  });

  it('says so when the library cannot be read', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => ({ ok: false, status: 500, json: async () => ({ detail: '诗词库目录不存在' }) }) as Response);
    render(<PoetrySourcePicker value={[]} onChange={() => undefined} />);
    expect((await screen.findByRole('alert')).textContent).toContain('诗词库目录不存在');
  });
});
