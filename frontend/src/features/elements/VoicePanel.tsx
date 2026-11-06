import { useCallback, useEffect, useState } from 'react';
import { X } from 'lucide-react';

import { apiRequest, apiUrl } from '../../api/client';
import { t } from '../../i18n';
import './VoicePanel.css';

interface VoicePreview {
  generated_voice_id: string;
  url?: string;
  duration_secs?: number;
}

interface VoiceRound {
  seed?: number | null;
  previews: VoicePreview[];
}

interface VoiceEntry {
  voice_id: string;
  voice_prompt: string;
  take?: { url?: string | null } | null;
  rounds: VoiceRound[];
}

interface CharacterVoice extends VoiceEntry {
  name: string;
  voice_desc: string;
}

interface NarratorVoice extends VoiceEntry {
  source: string;
  label: string;
}

interface VoicesView {
  characters: CharacterVoice[];
  narrator: NarratorVoice;
  narration_delivery: 'use_tts' | 'post_production';
}

interface LibraryVoice {
  voice_id: string;
  name?: string;
}

interface Props {
  taskId: string;
  onClose?: () => void;
}

const PAID_NOTICE = '试听会调用音色设计服务并产生费用，确定继续？';

function Takes({ rounds, disabled, onPick }: { rounds: VoiceRound[]; disabled: boolean; onPick: (id: string) => void }) {
  const latest = rounds[rounds.length - 1];
  if (!latest?.previews.length) return null;
  return (
    <ol className="voice-row__takes" aria-label={t('试听样本')}>
      {latest.previews.map((preview, index) => (
        <li key={preview.generated_voice_id} className="voice-row__take">
          <span>{t('第 {0} 版', [index + 1])}</span>
          {preview.url && <audio controls preload="none" src={apiUrl(preview.url)} aria-label={t('试听第 {0} 版', [index + 1])} />}
          <button type="button" className="voice-row__button" disabled={disabled} onClick={() => onPick(preview.generated_voice_id)}>
            {t('选这一版')}
          </button>
        </li>
      ))}
    </ol>
  );
}

/** Hear and keep a voice for each character, and pick who narrates. Reference-voice upload is absent: no provider path takes one. */
export function VoicePanel({ taskId, onClose }: Props) {
  const [view, setView] = useState<VoicesView | null>(null);
  const [library, setLibrary] = useState<LibraryVoice[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const base = `/api/drama/${encodeURIComponent(taskId)}`;

  const load = useCallback(async () => {
    setView(await apiRequest<VoicesView>(`${base}/voices`));
  }, [base]);

  useEffect(() => {
    let live = true;
    const first = async () => {
      try {
        await load();
      } catch (err) {
        if (live) setError(err instanceof Error ? err.message : t('声音加载失败'));
      }
    };
    void first();
    // The account's voices are a convenience; without a provider key the rest still works.
    apiRequest<{ voices?: LibraryVoice[] }>('/api/production/audio/voices?page_size=100')
      .then(data => { if (live) setLibrary(Array.isArray(data.voices) ? data.voices : []); })
      .catch(() => undefined);
    return () => { live = false; };
  }, [load]);

  const run = async (key: string, work: () => Promise<unknown>, done: string) => {
    setBusy(key);
    setError('');
    setStatus('');
    try {
      await work();
      await load();
      setStatus(done);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('操作失败'));
    } finally {
      setBusy('');
    }
  };

  const post = (path: string, body: unknown, method = 'POST') => apiRequest(`${base}${path}`, { method, body: JSON.stringify(body) });

  const auditionCharacter = (character: CharacterVoice) => {
    if (!window.confirm(t(PAID_NOTICE))) return;
    const voice_prompt = drafts[character.name] ?? character.voice_prompt;
    void run(`audition:${character.name}`, () => post('/characters/voice/audition', { name: character.name, voice_prompt }), t('已生成一轮试听。'));
  };

  const castCharacter = (name: string, generated_voice_id: string) => {
    void run(`cast:${name}`, () => post('/characters/voice/cast', { name, generated_voice_id }), t('已定下“{0}”的声音，之后的配音都用它。', [name]));
  };

  const auditionNarrator = () => {
    if (!view || !window.confirm(t(PAID_NOTICE))) return;
    const voice_prompt = drafts.__narrator ?? view.narrator.voice_prompt;
    void run('audition:narrator', () => post('/voices/narrator/audition', { voice_prompt }), t('已生成一轮试听。'));
  };

  const castNarrator = (generated_voice_id: string) => {
    void run('cast:narrator', () => post('/voices/narrator/cast', { generated_voice_id }), t('已定下旁白的声音，之后的配音都用它。'));
  };

  const chooseNarrator = (value: string) => {
    if (!value) {
      void run('choose:narrator', () => apiRequest(`${base}/voices/narrator`, { method: 'DELETE' }), t('旁白已恢复默认声音。'));
      return;
    }
    const known = library.find(voice => voice.voice_id === value)?.name
      ?? view?.characters.find(character => character.voice_id === value)?.name ?? '';
    void run('choose:narrator', () => post('/voices/narrator', { voice_id: value, label: known }, 'PUT'), t('已定下旁白的声音，之后的配音都用它。'));
  };

  const disabled = Boolean(busy);
  const castVoices = view?.characters.filter(character => character.voice_id) ?? [];
  const narratorKnown = view && (
    !view.narrator.voice_id
    || library.some(voice => voice.voice_id === view.narrator.voice_id)
    || castVoices.some(character => character.voice_id === view.narrator.voice_id)
  );

  return (
    <section className="voice-panel" aria-label={t('声音')}>
      <header className="voice-panel__head">
        <h2>{t('声音')}</h2>
        {onClose && <button type="button" className="voice-panel__icon" onClick={onClose} aria-label={t('关闭')}><X size={14} /></button>}
      </header>
      <p className="voice-panel__note">{t('定下的声音用于之后的配音；已出片的片段要重做才会换声。')}</p>
      {error && <p className="voice-panel__error" role="alert">{error}</p>}
      {status && <p className="voice-panel__status" role="status">{status}</p>}

      {view && (
        <ul className="voice-panel__list">
          <li className="voice-row voice-row--narrator">
            <div className="voice-row__title">
              <strong>{t('旁白')}</strong>
              <span className={`voice-row__badge${view.narrator.voice_id ? ' voice-row__badge--cast' : ''}`}>
                {view.narrator.voice_id ? (view.narrator.label || t('已定')) : t('默认声音')}
              </span>
              {view.narrator.take?.url && <audio controls preload="none" src={apiUrl(view.narrator.take.url)} aria-label={t('试听旁白当前声音')} />}
            </div>
            {view.narration_delivery === 'post_production' && <p className="voice-panel__note">{t('这个项目把旁白留给后期配音，这里定的声音不会用上。')}</p>}
            <label className="voice-row__label">{t('用已有声音')}
              <select value={view.narrator.voice_id} disabled={disabled} onChange={event => chooseNarrator(event.target.value)}>
                <option value="">{t('默认声音')}</option>
                {!narratorKnown && <option value={view.narrator.voice_id}>{view.narrator.label || t('当前声音')}</option>}
                {castVoices.map(character => <option key={`cast-${character.name}`} value={character.voice_id}>{character.name}</option>)}
                {library.filter(voice => !castVoices.some(character => character.voice_id === voice.voice_id)).map(voice => (
                  <option key={voice.voice_id} value={voice.voice_id}>{voice.name || voice.voice_id}</option>
                ))}
              </select>
            </label>
            <textarea
              aria-label={t('旁白音色设计提示词')}
              value={drafts.__narrator ?? view.narrator.voice_prompt}
              maxLength={1000}
              onChange={event => setDrafts(current => ({ ...current, __narrator: event.target.value }))}
            />
            <div className="voice-row__actions">
              <button type="button" className="voice-row__button" disabled={disabled} onClick={auditionNarrator}>
                {busy === 'audition:narrator' ? t('试听生成中…') : t(view.narrator.rounds.length ? '换一批试听' : '试听')}
              </button>
            </div>
            <Takes rounds={view.narrator.rounds} disabled={disabled} onPick={castNarrator} />
          </li>

          {view.characters.length === 0 && <li className="voice-panel__note">{t('还没有角色；完成第 3 阶段后可以在这里选角。')}</li>}
          {view.characters.map(character => {
            const prompt = drafts[character.name] ?? character.voice_prompt;
            return (
              <li key={character.name} className="voice-row">
                <div className="voice-row__title">
                  <strong>{character.name}</strong>
                  <span className={`voice-row__badge${character.voice_id ? ' voice-row__badge--cast' : ''}`}>
                    {character.voice_id ? t('已定') : t('未选角')}
                  </span>
                  {character.voice_desc && <span className="voice-row__badge">{character.voice_desc}</span>}
                  {character.take?.url && <audio controls preload="none" src={apiUrl(character.take.url)} aria-label={t('试听“{0}”当前声音', [character.name])} />}
                </div>
                <textarea
                  aria-label={t('“{0}”的音色设计提示词', [character.name])}
                  value={prompt}
                  maxLength={1000}
                  placeholder={t('身份、性别、年龄、音高、音色质感、语速；情绪中性，干声')}
                  onChange={event => setDrafts(current => ({ ...current, [character.name]: event.target.value }))}
                />
                <div className="voice-row__actions">
                  <button type="button" className="voice-row__button" disabled={disabled || prompt.trim().length < 20} onClick={() => auditionCharacter(character)}>
                    {busy === `audition:${character.name}` ? t('试听生成中…') : t(character.rounds.length ? '换一批试听' : '试听')}
                  </button>
                  {prompt.trim().length < 20 && <span className="voice-panel__note">{t('提示词至少 20 字')}</span>}
                </div>
                <Takes rounds={character.rounds} disabled={disabled} onPick={id => castCharacter(character.name, id)} />
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
