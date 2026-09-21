import { describe, expect, it } from 'vitest';

import { uploadRefusal, type CaptureUpload } from './directorDeskApi';

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
