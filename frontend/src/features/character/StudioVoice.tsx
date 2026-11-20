import { AudioLines, Pause, Play, Search, Sparkles } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { apiRequest, apiUrl } from '../../api/client';
import { t } from '../../i18n';
import { fetchRelinkPreview, relinkOutcome, relinkQuestion, waitForRelink, type VoiceRelinkResult } from '../elements/voiceRelink';

/**
 * 音色音调：给这个角色选一个声音。
 *
 * 「音色库」是这个账号已有的声音，试听用它们公开的样本，选用不花钱；「设计音色」照角色的音色描述
 * 试听几版(会产生费用，先问)，选一版定下。一个角色全剧一个声音、各不相同：别人在用的声音不给；
 * 这个角色说过话的话，换声音会自动重配，花钱或要改原声镜头时先问。
 */

interface LibraryVoice {
  voice_id: string;
  name?: string;
  preview_url?: string;
  labels?: Record<string, string>;
}
interface VoicePreview { generated_voice_id: string; url?: string }
interface CharacterVoice {
  name: string;
  voice_id: string;
  voice_prompt: string;
  voice_desc: string;
  take?: { url?: string | null } | null;
  rounds: { previews: VoicePreview[] }[];
}

const GENDERS: { id: string; label: string }[] = [
  { id: '', label: '全部' },
  { id: 'male', label: '男' },
  { id: 'female', label: '女' },
];

function describe(voice: LibraryVoice): string {
  const labels = voice.labels || {};
  const gender = labels.gender === 'male' ? t('男') : labels.gender === 'female' ? t('女') : '';
  return [labels.language || labels.accent, labels.age, gender].filter(Boolean).join(' · ');
}

export function StudioVoice({ taskId, characterName, onChanged }: {
  taskId: string;
  characterName: string;
  /** 声音定下之后：外层刷新角色看板。 */
  onChanged?: () => void;
}) {
  const base = `/api/drama/${encodeURIComponent(taskId)}`;
  const [tab, setTab] = useState<'library' | 'design'>('library');
  const [mine, setMine] = useState<CharacterVoice | null>(null);
  const [library, setLibrary] = useState<LibraryVoice[] | null>(null);
  const [search, setSearch] = useState('');
  const [gender, setGender] = useState('');
  const [prompt, setPrompt] = useState<string | null>(null);
  const [busy, setBusy] = useState('');
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [playing, setPlaying] = useState('');
  const audio = useRef<HTMLAudioElement | null>(null);

  const load = useCallback(async () => {
    const view = await apiRequest<{ characters: CharacterVoice[] }>(`${base}/voices`);
    setMine(view.characters.find(item => item.name === characterName) || null);
  }, [base, characterName]);

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
    apiRequest<{ voices?: LibraryVoice[] }>('/api/production/audio/voices?page_size=100')
      .then(data => { if (live) setLibrary(Array.isArray(data.voices) ? data.voices : []); })
      .catch(() => { if (live) setLibrary([]); });
    return () => { live = false; audio.current?.pause(); };
  }, [load]);

  const play = (key: string, url?: string | null) => {
    audio.current?.pause();
    if (!url || playing === key) { setPlaying(''); return; }
    const next = new Audio(apiUrl(url));
    next.onended = () => setPlaying('');
    audio.current = next;
    setPlaying(key);
    void next.play().catch(() => setPlaying(''));
  };

  /** 换声音前先看要重配多少；别人在用就不换；花钱或要改原声镜头先问。 */
  const confirmChange = async (voice: string): Promise<boolean> => {
    let preview = null;
    try {
      preview = await fetchRelinkPreview(base, characterName, voice);
    } catch (err) {
      if (!window.confirm(t('没能估算换声音要重配多少台词（{0}）。仍然要换吗？', [err instanceof Error ? err.message : '']))) return false;
    }
    if (preview?.taken_by) {
      setStatus('');
      setError(t('这个声音已经给了「{0}」，每个角色的声音要各不相同。', [preview.taken_by]));
      return false;
    }
    const question = relinkQuestion(preview);
    return !question || window.confirm(question);
  };

  const finish = async (relink: VoiceRelinkResult | null | undefined) => {
    await load().catch(() => undefined);
    onChanged?.();
    let done = relink ?? null;
    if (done && (done.status === 'queued' || done.status === 'running')) {
      setStatus(t('已定下“{0}”的声音，正在后台重配说过的台词…', [characterName]));
      done = await waitForRelink(base, characterName);
      if (!done) { setStatus(t('重配还在后台进行，稍后刷新查看。')); return; }
    }
    if (done) {
      const { ok, text } = relinkOutcome(done);
      if (ok) { setError(''); setStatus(text); } else { setStatus(''); setError(text); }
    }
  };

  const run = async (key: string, work: () => Promise<void>) => {
    setBusy(key);
    setError('');
    try {
      await work();
    } catch (err) {
      setStatus('');
      setError(err instanceof Error ? err.message : t('操作失败'));
    } finally {
      setBusy('');
    }
  };

  const chooseLibraryVoice = (voice: LibraryVoice) => run(`use:${voice.voice_id}`, async () => {
    if (!(await confirmChange(voice.voice_id))) return;
    const answer = await apiRequest<{ voiceRelink?: VoiceRelinkResult | null }>(
      `${base}/voices/characters/${encodeURIComponent(characterName)}`,
      { method: 'PUT', body: JSON.stringify({ voice_id: voice.voice_id, sample_url: voice.preview_url || '' }) },
    );
    setStatus(t('已定下“{0}”的声音，之后的配音都用它。', [characterName]));
    await finish(answer?.voiceRelink);
  });

  const audition = () => run('audition', async () => {
    if (!window.confirm(t('试听会调用音色设计服务并产生费用，确定继续？'))) return;
    await apiRequest(`${base}/characters/voice/audition`, {
      method: 'POST', body: JSON.stringify({ name: characterName, voice_prompt: prompt ?? mine?.voice_prompt ?? '' }),
    });
    await load();
    setStatus(t('已生成一轮试听。'));
  });

  const castTake = (generatedVoiceId: string) => run(`cast:${generatedVoiceId}`, async () => {
    if (!(await confirmChange(generatedVoiceId))) return;
    const answer = await apiRequest<{ voiceRelink?: VoiceRelinkResult | null }>(`${base}/characters/voice/cast`, {
      method: 'POST', body: JSON.stringify({ name: characterName, generated_voice_id: generatedVoiceId }),
    });
    setStatus(t('已定下“{0}”的声音，之后的配音都用它。', [characterName]));
    await finish(answer?.voiceRelink);
  });

  const shown = useMemo(() => (library || []).filter(voice => {
    if (gender && voice.labels?.gender !== gender) return false;
    const needle = search.trim().toLowerCase();
    return !needle || `${voice.name || ''} ${describe(voice)}`.toLowerCase().includes(needle);
  }), [gender, library, search]);
  const latest = mine?.rounds[mine.rounds.length - 1]?.previews || [];
  const current = library?.find(voice => voice.voice_id === mine?.voice_id);

  return (
    <div className="studio-voice">
      <div className="studio-tabs" role="tablist" aria-label={t('选声音的方式')}>
        <button type="button" role="tab" aria-selected={tab === 'library'} className={tab === 'library' ? 'is-active' : ''} onClick={() => setTab('library')}>
          <AudioLines size={14} aria-hidden="true" /> {t('音色库')}
        </button>
        <button type="button" role="tab" aria-selected={tab === 'design'} className={tab === 'design' ? 'is-active' : ''} onClick={() => setTab('design')}>
          <Sparkles size={14} aria-hidden="true" /> {t('设计音色')}
        </button>
      </div>
      <p className="studio-hint">
        {mine?.voice_id
          ? t('当前声音：{0}', [current?.name || (mine.take ? t('设计的声音') : mine.voice_id)])
          : t('还没定声音：配音时会从音色库里自动分一个没人用的。')}
      </p>
      {error && <p className="studio-error" role="alert">{error}</p>}
      {status && <p className="studio-status" role="status">{status}</p>}

      {tab === 'library' ? (
        <>
          <div className="studio-voice__filters">
            <label className="studio-search">
              <Search size={14} aria-hidden="true" />
              <input value={search} placeholder={t('搜索音色')} aria-label={t('搜索音色')} onChange={event => setSearch(event.target.value)} />
            </label>
            <div className="studio-groups" role="group" aria-label={t('性别')}>
              {GENDERS.map(item => (
                <button key={item.id} type="button" aria-pressed={gender === item.id} className={gender === item.id ? 'is-active' : ''} onClick={() => setGender(item.id)}>
                  {t(item.label)}
                </button>
              ))}
            </div>
          </div>
          {library === null && <p className="studio-hint">{t('正在读取音色库…')}</p>}
          {library && library.length === 0 && <p className="studio-hint">{t('音色库是空的，或还没连上配音服务；可以在「设计音色」里照角色描述试听。')}</p>}
          <ul className="studio-voice__list" aria-label={t('音色库')}>
            {shown.map(voice => {
              const chosen = voice.voice_id === mine?.voice_id;
              return (
                <li key={voice.voice_id} className={chosen ? 'is-current' : ''}>
                  <span className="studio-voice__icon" aria-hidden="true"><AudioLines size={16} /></span>
                  <span className="studio-voice__name">
                    <strong>{voice.name || voice.voice_id}</strong>
                    <small>{describe(voice)}</small>
                  </span>
                  {voice.preview_url && (
                    <button type="button" className="studio-icon-button" aria-label={t('试听 {0}', [voice.name || voice.voice_id])} onClick={() => play(voice.voice_id, voice.preview_url)}>
                      {playing === voice.voice_id ? <Pause size={14} /> : <Play size={14} />}
                    </button>
                  )}
                  <button type="button" className="studio-voice__use" disabled={chosen || Boolean(busy)} onClick={() => { void chooseLibraryVoice(voice); }}>
                    {chosen ? t('当前') : busy === `use:${voice.voice_id}` ? t('设定中…') : t('使用')}
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      ) : (
        <div className="studio-voice__design">
          <label className="studio-control__label" htmlFor="studio-voice-prompt">{t('音色描述')}</label>
          <textarea
            id="studio-voice-prompt"
            className="studio-text"
            rows={4}
            maxLength={1000}
            value={prompt ?? mine?.voice_prompt ?? ''}
            placeholder={t('如：二十出头的男声，清亮偏冷，语速稍慢，尾音收得干净')}
            onChange={event => setPrompt(event.target.value)}
          />
          <button type="button" className="studio-secondary" disabled={Boolean(busy)} onClick={() => { void audition(); }}>
            {busy === 'audition' ? t('试听生成中…') : latest.length ? t('换一批试听') : t('试听（付费）')}
          </button>
          {latest.length > 0 && (
            <ol className="studio-voice__list" aria-label={t('试听样本')}>
              {latest.map((take, index) => (
                <li key={take.generated_voice_id}>
                  <span className="studio-voice__name"><strong>{t('第 {0} 版', [index + 1])}</strong></span>
                  {take.url && (
                    <button type="button" className="studio-icon-button" aria-label={t('试听第 {0} 版', [index + 1])} onClick={() => play(take.generated_voice_id, take.url)}>
                      {playing === take.generated_voice_id ? <Pause size={14} /> : <Play size={14} />}
                    </button>
                  )}
                  <button type="button" className="studio-voice__use" disabled={Boolean(busy)} onClick={() => { void castTake(take.generated_voice_id); }}>
                    {t('选这一版')}
                  </button>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}
