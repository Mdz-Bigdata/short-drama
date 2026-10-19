// The thumbnails of a camera comparison come off one small canvas, one lens at a time: pose the
// camera, draw, read the picture back, next. This is the order-keeping around that loop, kept
// apart from WebGL so it can be tested without a context. Only one run draws at a time, and a
// newer request supersedes whatever is still drawing: the comparison always shows the latest plan.

export class CompareCancelledError extends Error {
  constructor() {
    super('机位对比已被更新的请求取代。');
    this.name = 'CompareCancelledError';
  }
}

export function isCompareCancelled(error: unknown): boolean {
  return error instanceof CompareCancelledError;
}

export interface CompareQueue<Camera extends { id: string }, Thumb> {
  /**
   * Draw every camera in order. Resolves with the thumbnails keyed by camera id; `onEach` hears each
   * one as it is made, so a grid can fill in instead of waiting. Rejects with `CompareCancelledError`
   * when a later `run` or `cancel` overtakes it.
   */
  run: (cameras: Camera[], onEach?: (id: string, thumb: Thumb) => void) => Promise<Record<string, Thumb>>;
  cancel: () => void;
  busy: () => boolean;
}

/** Lets the page paint and the input queue drain between two thumbnails. */
const nextTask = () => new Promise<void>(resolve => { setTimeout(resolve, 0); });

export function createCompareQueue<Camera extends { id: string }, Thumb>(
  renderOne: (camera: Camera) => Thumb | Promise<Thumb>,
  breathe: () => Promise<void> = nextTask,
): CompareQueue<Camera, Thumb> {
  let active: { cancelled: boolean } | null = null;
  // Every run queues behind the one before it, so a cancelled run that is mid-draw finishes that
  // one picture before the next run touches the canvas: two runs never pose the same camera at once.
  let tail: Promise<unknown> = Promise.resolve();

  return {
    run(cameras, onEach) {
      if (active) active.cancelled = true;
      const token = { cancelled: false };
      active = token;
      const work = tail.then(async () => {
        try {
          const made: Record<string, Thumb> = {};
          for (let index = 0; index < cameras.length; index += 1) {
            if (token.cancelled) throw new CompareCancelledError();
            const camera = cameras[index];
            const thumb = await renderOne(camera);
            // A picture drawn after the cancel is of a plan nobody asked about any more.
            if (token.cancelled) throw new CompareCancelledError();
            made[camera.id] = thumb;
            onEach?.(camera.id, thumb);
            if (index < cameras.length - 1) await breathe();
          }
          return made;
        } finally {
          // Settled before the caller hears of it, so `busy()` is already false in their `then`.
          if (active === token) active = null;
        }
      });
      tail = work.then(() => undefined, () => undefined);
      return work;
    },
    cancel() {
      if (active) active.cancelled = true;
    },
    busy: () => active !== null,
  };
}
