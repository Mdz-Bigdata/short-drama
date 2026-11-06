// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { StageSixPreview } from './StageSixPreview';
import { mediaUrlOf, spokenText } from './stageSix';

describe('stage six preview', () => {
  it('shows only the spoken words of a dialogue cell', () => {
    expect(spokenText('苏问剑：{爹！}（音色偏低、沙哑；起音猛、尾音发颤）')).toBe('爹！');
    expect(spokenText('沈无咎：剑不是我拿的（气声；喉头发紧')).toBe('剑不是我拿的');
    expect(spokenText('无')).toBe('');
  });

  it('serves a stored voice file from the media folder and keeps absolute links', () => {
    expect(mediaUrlOf('/Users/x/backend/generated_media/eleven_voice_a.mp3')).toBe('http://localhost:8000/media/eleven_voice_a.mp3');
    expect(mediaUrlOf('https://cdn.test/mix.mp3')).toBe('https://cdn.test/mix.mp3');
  });

  it('lists every voice track beside its speaker and the music beds', () => {
    render(<StageSixPreview
      ttsModel="eleven_multilingual_v2"
      asset={{
        audio_url: null,
        bgm_url: 'http://localhost:8000/media/bgm.mp3',
        sfx_url: 'http://localhost:8000/media/sfx.mp3',
        shot_voices: ['/m/eleven_voice_s1.mp3', '/m/eleven_voice_s2.mp3'],
        dialogue_directions: [
          { shot_id: 1, speaker: '苏问剑', verbatim_text: '{爹！}（沙哑；起音猛）', emotion: '急' },
          { shot_id: 2, speaker: '裴仲玄', verbatim_text: '剑在人在。' },
        ],
        voice_profile: '逐镜情绪配音',
        episode: 3,
      }}
    />);
    const tracks = screen.getByRole('list', { name: '逐镜配音' });
    expect(tracks.querySelectorAll('li')).toHaveLength(2);
    expect(tracks.textContent).toContain('爹！');
    expect(tracks.textContent).not.toContain('沙哑');
    expect(tracks.textContent).toContain('裴仲玄');
    expect(tracks.querySelectorAll('audio')[1].getAttribute('src')).toBe('http://localhost:8000/media/eleven_voice_s2.mp3');
    expect(screen.getByText('背景音乐')).toBeTruthy();
    expect(screen.getByText('环境音效')).toBeTruthy();
    expect(screen.queryByText('混音成品')).toBeNull();
  });
});
