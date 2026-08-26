// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

import ElementModelViewport from './ElementModelViewport';
import { disposeModelResources } from './disposeModelResources';


beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
  vi.restoreAllMocks();
});


describe('ElementModelViewport', () => {
  it('disposes unique Three.js GPU resources when a loaded model leaves the stage', () => {
    const geometry = { dispose: vi.fn() };
    const texture = { isTexture: true, dispose: vi.fn() };
    const material = { map: texture, normalMap: texture, dispose: vi.fn() };
    const root = {
      traverse: (visit: (object: unknown) => void) => {
        visit({ geometry, material: [material, material] });
      },
    };

    disposeModelResources(root as never);

    expect(texture.dispose).toHaveBeenCalledTimes(1);
    expect(material.dispose).toHaveBeenCalledTimes(1);
    expect(geometry.dispose).toHaveBeenCalledTimes(1);
  });

  it('disposes a parsed scene that finishes after the viewer was abandoned', async () => {
    Object.defineProperty(window, 'WebGL2RenderingContext', { configurable: true, value: class WebGL2RenderingContext {} });
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as WebGL2RenderingContext);
    const geometry = { dispose: vi.fn() };
    const material = { dispose: vi.fn() };
    const root = {
      traverse: (visit: (object: unknown) => void) => visit({ geometry, material }),
    };
    let resolveParse!: (value: unknown) => void;
    const parseResult = new Promise(resolve => { resolveParse = resolve; });
    vi.spyOn(GLTFLoader.prototype, 'parseAsync').mockReturnValue(parseResult as never);
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(24),
    } as Response);

    const view = render(<ElementModelViewport name="加载中模型" contentUrl="/api/elements/1/model/content?v=1" />);
    await waitFor(() => expect(GLTFLoader.prototype.parseAsync).toHaveBeenCalled());
    view.unmount();

    await act(async () => {
      resolveParse({ scene: root });
      await parseResult;
    });
    expect(geometry.dispose).toHaveBeenCalledTimes(1);
    expect(material.dispose).toHaveBeenCalledTimes(1);
  });

  it('uses the poster fallback without downloading the GLB when WebGL2 is unavailable', async () => {
    Object.defineProperty(window, 'WebGL2RenderingContext', { configurable: true, value: undefined });
    const fetchMock = vi.spyOn(globalThis, 'fetch');

    render(<ElementModelViewport name="旧车站" contentUrl="/api/elements/1/model/content?v=1" />);

    expect(await screen.findByText(/当前浏览器或设备不支持 WebGL 2/)).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: '重试加载' })).toBeNull();
  });

  it('loads protected model content with credentials and surfaces API errors', async () => {
    Object.defineProperty(window, 'WebGL2RenderingContext', { configurable: true, value: class WebGL2RenderingContext {} });
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as WebGL2RenderingContext);
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: '3D 模型版本已更新' }),
    } as Response);

    render(<ElementModelViewport name="旧车站" contentUrl="/api/elements/1/model/content?v=1" />);

    expect(await screen.findByText('3D 模型版本已更新')).toBeTruthy();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/elements/1/model/content?v=1',
      expect.objectContaining({ credentials: 'include' }),
    ));
  });
});
