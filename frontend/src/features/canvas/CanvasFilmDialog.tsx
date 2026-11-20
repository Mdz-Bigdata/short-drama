import { useEffect, useMemo, useRef, useState } from 'react';
import { Clapperboard, Loader2 } from 'lucide-react';

import { t } from '../../i18n';
import { buildFilm, previewFilm, type FilmBuild, type FilmPreview, type FilmRequest } from './canvasFilmApi';

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

/** How long to wait after a change of options before asking again what the film would take. */
export const FILM_PREVIEW_DELAY_MS = 250;

/**
 * One finished film from the canvas: the clips in order, a voice under each silent clip with lines, music if
 * wanted, joined by one compose node and run together with whatever is still missing. Putting the nodes in
 * place costs nothing; the run is quoted and confirmed like any other.
 */
export function CanvasFilmDialog({ projectId, canvasId, clientId, selectedClips, prepare, onBuilt, onClose }: {
  projectId: string;
  canvasId: string;
  clientId?: string;
  /** Video nodes selected on the canvas: offered as "only these". */
  selectedClips: string[];
  /** Saves what is unsaved and answers the version to build on; rejects when the canvas cannot be saved. */
  prepare: () => Promise<number>;
  /** The film's nodes are in place: load them, then run `build.run`. */
  onBuilt: (build: FilmBuild) => void | Promise<void>;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const [onlySelected, setOnlySelected] = useState(selectedClips.length > 0);
  const [voices, setVoices] = useState(true);
  const [music, setMusic] = useState(false);
  // Until the person touches it, the music box follows the film: on when the film already has music.
  const [musicTouched, setMusicTouched] = useState(false);
  const [musicPrompt, setMusicPrompt] = useState('');
  const [preview, setPreview] = useState<FilmPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');

  const request = useMemo<FilmRequest>(() => ({
    nodeIds: onlySelected ? selectedClips : [], voices, music, musicPrompt,
  }), [music, musicPrompt, onlySelected, selectedClips, voices]);

  useEffect(() => {
    panel.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.stopPropagation();
      onClose();
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onClose]);

  // Ask the server what the film would take, again whenever an option changes. The canvas is saved first,
  // so the answer is about what is on screen.
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    let live = true;
    prepare().then(() => { if (live) setSaved(true); }).catch(error => { if (live) setProblem(messageOf(error, t('画布还没保存成功，先解决保存问题。'))); });
    return () => { live = false; };
  }, [prepare]);

  useEffect(() => {
    if (!saved) return undefined;
    const abort = new AbortController();
    setLoading(true);
    const timer = setTimeout(() => {
      previewFilm(projectId, canvasId, request, abort.signal)
        .then(value => {
          setPreview(value);
          setProblem('');
          if (value.had_music && !musicTouched && !music && value.music_available) setMusic(true);
        })
        .catch(error => { if (!abort.signal.aborted) { setPreview(null); setProblem(messageOf(error, t('读取成片内容失败'))); } })
        .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    }, FILM_PREVIEW_DELAY_MS);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps -- the music default is read once per answer, not a reason to ask again
  }, [canvasId, projectId, request, saved]);

  const start = async () => {
    if (!preview || busy) return;
    setBusy(true);
    setProblem('');
    try {
      const version = await prepare();
      const built = await buildFilm(projectId, canvasId, request, version, clientId);
      await onBuilt(built);
    } catch (error) {
      setProblem(messageOf(error, t('搭建成片失败')));
      setBusy(false);
    }
  };

  const seconds = preview?.shots.reduce((sum, shot) => sum + shot.seconds, 0) ?? 0;
  const title = t('一键成片');
  return (
    <div className="cn-dialog-backdrop">
      <div ref={panel} className="cn-dialog cn-film" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
        <h2>{title}</h2>
        <p className="cn-hint">{t('把镜头按顺序接到一个「成片」节点上，和还没生成的首帧、视频、配音一起运行。搭节点不花钱，运行前照常报价、由你确认。')}</p>

        <div className="cn-film__options">
          {selectedClips.length > 0 && (
            <label className="cn-sync__pick">
              <input type="checkbox" checked={onlySelected} onChange={event => setOnlySelected(event.target.checked)} />
              {t('只用选中的 {0} 个视频节点', [selectedClips.length])}
            </label>
          )}
          <label className="cn-sync__pick">
            <input type="checkbox" checked={voices} onChange={event => setVoices(event.target.checked)} />
            {t('有台词但没声音的镜头配上配音（按项目角色分声）')}
          </label>
          <label className="cn-sync__pick">
            <input type="checkbox" checked={music} disabled={preview ? !preview.music_available : false} onChange={event => { setMusicTouched(true); setMusic(event.target.checked); }} />
            {t('加配乐')}
            {preview && !preview.music_available && <small className="cn-hint"> · {t('需要 ElevenLabs')}</small>}
          </label>
          {music && (
            <input
              className="cn-film__music" aria-label={t('配乐要求')} placeholder={t('配乐要求（留空用默认）')} maxLength={400}
              value={musicPrompt} onChange={event => setMusicPrompt(event.target.value)}
            />
          )}
        </div>

        {loading && !problem && <p className="cn-hint"><Loader2 className="cn-spin" aria-hidden="true" /> {t('清点镜头…')}</p>}
        {preview && (
          <>
            <p className="cn-dialog__cost"><Clapperboard aria-hidden="true" /> {t('{0} 个镜头，约 {1} 秒', [preview.shots.length, seconds])}</p>
            <ol className="cn-film__shots" aria-label={t('成片镜头')}>
              {preview.shots.map(shot => (
                <li key={shot.node_id}>
                  <strong>{shot.label}</strong> <small>{t('{0} 秒', [shot.seconds])}</small>
                  {shot.lines && <small className="cn-film__lines">{shot.lines}</small>}
                </li>
              ))}
            </ol>
            <p className="cn-hint" role="status">
              {t('还要生成：首帧 {0} 个、视频 {1} 个、配音 {2} 条、配乐 {3} 条，最后合成成片。', [
                preview.missing.frames, preview.missing.clips, preview.missing.voices, preview.missing.music,
              ])}
              {preview.missing.pictures ? ` ${t('另有人物定妆图 {0} 张，先画好再画首帧。', [preview.missing.pictures])}` : ''}
            </p>
            {voices && preview.voiced === 0 && preview.shots.some(shot => shot.lines) && (
              <p className="cn-hint">{t('这些镜头用的视频模型自己会出声，不另外配音；出来没声音的，再点一次一键成片就会补上配音。')}</p>
            )}
          </>
        )}
        {problem && <p className="cn-error" role="alert">{problem}</p>}
        <footer className="cn-dialog__foot">
          <button type="button" className="cn-button" onClick={onClose}>{t('取消')}</button>
          <button type="button" className="cn-button is-primary" disabled={!preview || loading || busy} onClick={() => { void start(); }}>
            {busy && <Loader2 className="cn-spin" aria-hidden="true" />} {t('搭好并估价（{0} 个节点）', [preview?.to_run ?? 0])}
          </button>
        </footer>
      </div>
    </div>
  );
}
