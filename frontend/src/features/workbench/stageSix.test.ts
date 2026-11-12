import { describe, expect, it } from 'vitest';

import { mediaUrlOf, spokenText } from './stageSix';

describe('stage six helpers', () => {
  it('shows only the spoken words of a dialogue cell', () => {
    expect(spokenText('苏问剑：{爹！}（音色偏低、沙哑；起音猛、尾音发颤）')).toBe('爹！');
    expect(spokenText('沈无咎：剑不是我拿的（气声；喉头发紧')).toBe('剑不是我拿的');
    expect(spokenText('无')).toBe('');
  });

  it('serves a stored voice file from the media folder and keeps absolute links', () => {
    expect(mediaUrlOf('/Users/x/backend/generated_media/eleven_voice_a.mp3')).toBe('http://localhost:8000/media/eleven_voice_a.mp3');
    expect(mediaUrlOf('https://cdn.test/mix.mp3')).toBe('https://cdn.test/mix.mp3');
  });
});
