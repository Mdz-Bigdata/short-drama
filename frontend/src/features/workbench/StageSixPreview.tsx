import { Music, Mic, Waves, Disc3 } from 'lucide-react';
import { mediaUrlOf, spokenText } from './stageSix';
import { t } from '../../i18n';
import './StageSixPreview.css';

interface DialogueDirection {
  shot_id?: number | string;
  speaker?: string;
  verbatim_text?: string;
  emotion?: string;
}

export interface StageSixAsset {
  audio_url?: string | null;
  bgm_url?: string | null;
  sfx_url?: string | null;
  shot_voices?: string[] | null;
  dialogue_directions?: DialogueDirection[] | null;
  voice_profile?: string | null;
  episode?: number | null;
}

export function StageSixPreview({ asset, ttsModel }: { asset: StageSixAsset | null | undefined; ttsModel?: string }) {
  const voices = asset?.shot_voices ?? [];
  const directions = asset?.dialogue_directions ?? [];
  const tracks = voices.map((voice, index) => {
    const direction = directions[index] ?? {};
    return {
      key: `${index}-${voice}`,
      shot: direction.shot_id ?? index + 1,
      speaker: direction.speaker ?? '',
      text: spokenText(direction.verbatim_text ?? ''),
      emotion: direction.emotion ?? '',
      url: mediaUrlOf(voice),
    };
  });
  const beds = [
    asset?.audio_url ? { key: 'mix', icon: <Disc3 size={16} />, label: t('混音成品'), url: asset.audio_url } : null,
    asset?.bgm_url ? { key: 'bgm', icon: <Music size={16} />, label: t('背景音乐'), url: asset.bgm_url } : null,
    asset?.sfx_url ? { key: 'sfx', icon: <Waves size={16} />, label: t('环境音效'), url: asset.sfx_url } : null,
  ].filter((bed): bed is NonNullable<typeof bed> => bed !== null);

  return (
    <div className="stage-six">
      <header className="stage-six__head">
        <span className="stage-six__icon"><Music size={20} /></span>
        <div>
          <h4>{t('音轨合成')}</h4>
          <p>
            {asset?.voice_profile || t('角色专属配音')}
            {ttsModel ? ` · ${ttsModel}` : ''}
            {asset?.episode ? ` · ${t('第')}${asset.episode}${t('集')}` : ''}
          </p>
        </div>
        <div className="stage-six__chips">
          <span><Mic size={12} /> {t('配音')} {tracks.length}</span>
          {asset?.bgm_url && <span><Music size={12} /> BGM</span>}
          {asset?.sfx_url && <span><Waves size={12} /> SFX</span>}
        </div>
      </header>

      {beds.length > 0 && (
        <div className="stage-six__beds">
          {beds.map(bed => (
            <div className="stage-six__bed" key={bed.key}>
              <span className="stage-six__bed-label">{bed.icon} {bed.label}</span>
              <audio src={bed.url} controls preload="none" />
            </div>
          ))}
        </div>
      )}

      {tracks.length > 0 ? (
        <ol className="stage-six__tracks" aria-label={t('逐镜配音')}>
          {tracks.map(track => (
            <li key={track.key}>
              <span className="stage-six__shot">{t('镜')} {track.shot}</span>
              <div className="stage-six__line">
                {track.speaker && <strong>{track.speaker}</strong>}
                <span>{track.text || t('（无台词）')}</span>
                {track.emotion && <em>{track.emotion}</em>}
              </div>
              <audio src={track.url} controls preload="none" />
            </li>
          ))}
        </ol>
      ) : (
        <p className="stage-six__empty">{t('本集还没有配音音轨。')}</p>
      )}
    </div>
  );
}
