import { describe, expect, it, vi } from 'vitest';

import { createCompareQueue, isCompareCancelled } from './compareQueue';

interface Cam { id: string }

/** A renderer the test releases one picture at a time. */
function slowRenderer() {
  const waiting: Array<{ id: string; resolve: (thumb: string) => void }> = [];
  const renderOne = vi.fn((camera: Cam) => new Promise<string>(resolve => { waiting.push({ id: camera.id, resolve }); }));
  const release = () => {
    const next = waiting.shift();
    if (!next) throw new Error('nothing is drawing');
    next.resolve(`img:${next.id}`);
  };
  return { renderOne, release, waiting };
}

const cams = (...ids: string[]): Cam[] => ids.map(id => ({ id }));
const settle = () => new Promise(resolve => { setTimeout(resolve, 0); });
const immediately = () => Promise.resolve();

describe('createCompareQueue', () => {
  it('draws the cameras one after another, in order, and reports each as it is made', async () => {
    const { renderOne, release, waiting } = slowRenderer();
    const queue = createCompareQueue(renderOne, immediately);
    const each = vi.fn();
    const run = queue.run(cams('a', 'b', 'c'), each);
    expect(queue.busy()).toBe(true);

    await settle();
    expect(waiting.map(item => item.id)).toEqual(['a']);   // b waits for a; nothing draws in parallel
    release();
    await settle();
    expect(each).toHaveBeenCalledWith('a', 'img:a');
    expect(waiting.map(item => item.id)).toEqual(['b']);
    release();
    await settle();
    release();
    expect(await run).toEqual({ a: 'img:a', b: 'img:b', c: 'img:c' });
    expect(renderOne.mock.calls.map(call => call[0].id)).toEqual(['a', 'b', 'c']);
    expect(queue.busy()).toBe(false);
  });

  it('lets a newer run overtake the one still drawing, without ever drawing two at once', async () => {
    const { renderOne, release, waiting } = slowRenderer();
    const queue = createCompareQueue(renderOne, immediately);
    const first = queue.run(cams('a', 'b'));
    await settle();
    const second = queue.run(cams('x', 'y'));
    await settle();
    // The second run waits for the picture already on the canvas before it poses anything.
    expect(waiting.map(item => item.id)).toEqual(['a']);
    release();
    await expect(first).rejects.toSatisfy(isCompareCancelled);
    await settle();
    expect(waiting.map(item => item.id)).toEqual(['x']);
    release();
    await settle();
    release();
    expect(await second).toEqual({ x: 'img:x', y: 'img:y' });
    expect(renderOne.mock.calls.map(call => call[0].id)).toEqual(['a', 'x', 'y']);
  });

  it('cancels outright, and a run cancelled before it started never touches the renderer', async () => {
    const { renderOne, release } = slowRenderer();
    const queue = createCompareQueue(renderOne, immediately);
    const first = queue.run(cams('a', 'b'));
    await settle();   // a is on the canvas
    const second = queue.run(cams('c'));
    queue.cancel();
    release();
    await expect(first).rejects.toSatisfy(isCompareCancelled);
    await expect(second).rejects.toSatisfy(isCompareCancelled);
    expect(renderOne.mock.calls.map(call => call[0].id)).toEqual(['a']);
    expect(queue.busy()).toBe(false);
  });

  it('breathes between thumbnails but not after the last one', async () => {
    const breathe = vi.fn(() => Promise.resolve());
    const queue = createCompareQueue((camera: Cam) => `img:${camera.id}`, breathe);
    expect(await queue.run(cams('a', 'b', 'c'))).toEqual({ a: 'img:a', b: 'img:b', c: 'img:c' });
    expect(breathe).toHaveBeenCalledTimes(2);
    expect(await queue.run([])).toEqual({});
  });

  it('hands a renderer failure to the caller and is ready for the next run', async () => {
    let fail = true;
    const queue = createCompareQueue((camera: Cam) => {
      if (fail) throw new Error('context lost');
      return `img:${camera.id}`;
    }, immediately);
    await expect(queue.run(cams('a'))).rejects.toThrow('context lost');
    fail = false;
    expect(await queue.run(cams('a'))).toEqual({ a: 'img:a' });
  });
});
