import { afterEach, describe, expect, it, vi } from 'vitest';

import { normalizeCapture, uploadCapture, uploadRefusal, type CaptureUpload } from './directorDeskApi';

const base = { shotId: 1, cameraId: 'cam-01', width: 720, height: 1280, planRevision: 3, showsLimbs: false, monochrome: false, labelled: false };
const clip = (patch: Partial<CaptureUpload> = {}): CaptureUpload => ({ ...base, kind: 'clip', blob: new Blob(['x'], { type: 'video/mp4' }), durationS: 5, fps: 24, ...patch });

describe('uploadRefusal', () => {
  it('lets through what the server accepts', () => {
    expect(uploadRefusal(clip())).toBe('');
    expect(uploadRefusal(clip({ blob: new Blob(['x'], { type: 'video/webm;codecs=vp9' }), durationS: 30, fps: 30 }))).toBe('');
    expect(uploadRefusal({ ...base, blob: new Blob(['x'], { type: 'image/png' }) })).toBe('');
  });

  it('refuses the rest in the server’s words', () => {
    expect(uploadRefusal(clip({ durationS: 30.5 }))).toContain('0 到 30 秒');
    expect(uploadRefusal(clip({ durationS: 0 }))).toContain('0 到 30 秒');
    expect(uploadRefusal(clip({ fps: 60 }))).toContain('24 / 25 / 30');
    expect(uploadRefusal(clip({ fps: undefined }))).toContain('24 / 25 / 30');
    expect(uploadRefusal(clip({ blob: new Blob(['x'], { type: 'video/quicktime' }) }))).toContain('MP4、WebM');
    expect(uploadRefusal(clip({ blob: new Blob([], { type: 'video/mp4' }) }))).toContain('空的');
    expect(uploadRefusal(clip({ blob: { size: 60 * 1024 * 1024 + 1, type: 'video/mp4' } as Blob }))).toContain('60 MB');
    expect(uploadRefusal({ ...base, blob: { size: 10 * 1024 * 1024 + 1, type: 'image/png' } as Blob })).toContain('10 MB');
    expect(uploadRefusal({ ...base, blob: new Blob(['x'], { type: 'image/gif' }) })).toContain('PNG、JPEG、WebP');
  });
});

describe('uploadCapture', () => {
  const fetchMock = vi.fn();
  afterEach(() => vi.unstubAllGlobals());

  const answer = (body: unknown) => () => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  const sent = () => fetchMock.mock.calls[0][1].body as FormData;

  it('carries the depth flag on a still and a clip, false unless asked', async () => {
    fetchMock.mockReset().mockImplementation(answer({ capture: { id: 'c1', depth: true } }));
    vi.stubGlobal('fetch', fetchMock);
    const made = await uploadCapture('t1', 'E1S01', { ...base, blob: new Blob(['x'], { type: 'image/png' }), depth: true });
    expect(sent().get('depth')).toBe('true');
    expect(made.depth).toBe(true);

    fetchMock.mockClear();
    await uploadCapture('t1', 'E1S01', clip());
    expect(sent().get('depth')).toBe('false');
  });

  it('never sends the field on a backdrop, which the server would refuse', async () => {
    fetchMock.mockReset().mockImplementation(answer({ id: 'b1', kind: 'backdrop' }));
    vi.stubGlobal('fetch', fetchMock);
    await uploadCapture('t1', 'E1S01', { ...base, kind: 'backdrop', blob: new Blob(['x'], { type: 'image/png' }), depth: true });
    expect(sent().has('depth')).toBe(false);
  });
});

describe('normalizeCapture', () => {
  it('reads depth and defaults it to false for records from before there were depth pictures', () => {
    expect(normalizeCapture({ id: 'c1', depth: true }).depth).toBe(true);
    expect(normalizeCapture({ id: 'c2', depth: false }).depth).toBe(false);
    expect(normalizeCapture({ id: 'c3' }).depth).toBe(false);
    expect(normalizeCapture({ id: 'c4', depth: true, warning: '深度画面：近亮远暗的灰度图' })).toMatchObject({ depth: true, warning: '深度画面：近亮远暗的灰度图' });
  });
});
