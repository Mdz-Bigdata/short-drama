// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import AssetImageViewer from './AssetImageViewer';

const asset = { kind: 'prop' as const, name: '青铜剑', description: '剑身有铭文', imageUrl: '/files/sword.png' };

function openViewer() {
  render(<AssetImageViewer asset={asset} onClose={() => {}} />);
  const dialog = screen.getByRole('dialog', { name: '青铜剑 · 拍摄道具全景细节' });
  const stage = within(dialog).getByRole('button', { name: '点击拍摄道具全景图局部放大' });
  vi.spyOn(stage, 'getBoundingClientRect').mockReturnValue({
    x: 0, y: 0, left: 0, top: 0, right: 1000, bottom: 500, width: 1000, height: 500,
    toJSON: () => ({}),
  });
  const image = within(stage).getByRole('img', { name: '青铜剑 拍摄道具全景图' });
  const zoom = () => Number.parseFloat(image.style.transform.replace('scale(', ''));
  const wheel = (init: WheelEventInit) => {
    const event = new WheelEvent('wheel', { bubbles: true, cancelable: true, ...init });
    fireEvent(stage, event);
    return event;
  };
  return { dialog, stage, image, zoom, wheel };
}

describe('AssetImageViewer', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('zooms a little per wheel notch and keeps the page behind from zooming', () => {
    const { dialog, image, zoom, wheel } = openViewer();

    const notch = wheel({ deltaY: -100, clientX: 250, clientY: 375 });
    expect(notch.defaultPrevented).toBe(true);
    expect(zoom()).toBeGreaterThan(1);
    expect(zoom()).toBeLessThan(1.5);
    expect(image.style.transformOrigin).toBe('25% 75%');
    expect(within(dialog).getByText('观察位置 X 25% · Y 75%')).toBeTruthy();

    // 触控板的一小步也算数，不会被取整吃掉。
    const before = zoom();
    wheel({ deltaY: -6, clientX: 250, clientY: 375 });
    expect(zoom()).toBeGreaterThan(before);
    expect(zoom() - before).toBeLessThan(0.1);

    // 捏合(带 ctrl 的滚轮)同样被拦下，浏览器不会缩放整页。
    const pinch = wheel({ deltaY: 30, ctrlKey: true, clientX: 250, clientY: 375 });
    expect(pinch.defaultPrevented).toBe(true);
    expect(zoom()).toBeLessThan(before);
  });

  it('zooms on a slow trackpad scroll made of very small steps', () => {
    const { dialog, zoom, wheel } = openViewer();

    for (let step = 0; step < 200; step += 1) wheel({ deltaY: -1, clientX: 250, clientY: 375 });
    // 200 个位移 1 的事件合起来约 1.35 倍。
    expect(zoom()).toBeCloseTo(Math.exp(0.3), 3);
    expect(within(dialog).getByRole('status', { name: '当前缩放比例' }).textContent).toBe('1.3×');

    for (let step = 0; step < 400; step += 1) wheel({ deltaY: 1, clientX: 250, clientY: 375 });
    expect(zoom()).toBe(1);
  });

  it('zooms into the detail under the cursor when the picture is already enlarged', () => {
    const { dialog, stage, image } = openViewer();

    fireEvent.click(stage, { clientX: 250, clientY: 375 });
    fireEvent.click(stage, { clientX: 250, clientY: 375 });
    expect(image.style.transform).toBe('scale(2)');
    expect(image.style.transformOrigin).toBe('25% 75%');

    // 放大两倍、中心在 (25%, 75%) 时，舞台 (80%, 40%) 处显示的是原图的 (52.5%, 57.5%)。
    fireEvent.click(stage, { clientX: 800, clientY: 200 });
    expect(image.style.transform).toBe('scale(2.5)');
    expect(within(dialog).getByText('观察位置 X 53% · Y 58%')).toBeTruthy();
    const [originX, originY] = image.style.transformOrigin.split(' ').map(Number.parseFloat);
    // 那一点放大后仍在指针底下。
    expect(originX + (52.5 - originX) * 2.5).toBeCloseTo(80, 1);
    expect(originY + (57.5 - originY) * 2.5).toBeCloseTo(40, 1);
  });

  it('enlarges around the current centre when the stage is pressed from the keyboard', () => {
    const { stage, image } = openViewer();

    fireEvent.click(stage, { clientX: 250, clientY: 375 });
    fireEvent.click(stage);
    expect(image.style.transform).toBe('scale(2)');
    expect(image.style.transformOrigin).toBe('25% 75%');
  });

  it('moves to the clicked detail once the zoom is at its limit', () => {
    const { dialog, stage, image } = openViewer();

    for (let step = 0; step < 6; step += 1) fireEvent.click(stage, { clientX: 500, clientY: 250 });
    expect(image.style.transform).toBe('scale(4)');
    expect(within(dialog).getByRole<HTMLButtonElement>('button', { name: '放大' }).disabled).toBe(true);

    fireEvent.click(stage, { clientX: 900, clientY: 250 });
    expect(image.style.transform).toBe('scale(4)');
    expect(image.style.transformOrigin).toBe('60% 50%');
  });
});
