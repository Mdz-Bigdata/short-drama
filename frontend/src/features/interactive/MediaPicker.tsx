import { ImagePlus, RefreshCw, Trash2, Upload, X } from 'lucide-react';
import { useState } from 'react';

import { apiUrl } from '../../api/client';
import { t } from '../../i18n';
import { formatCost } from '../workbench/shotVisual';
import { deleteUpload, fetchAdmission, fetchMediaLibrary, markShotForRedo, measureVideoSeconds, uploadMedia } from './interactiveApi';
import type { LibraryShot, MediaLibrary, StoryMedia } from './storyTypes';

function message(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

/** What a segment shows: picked from the project's shots and generated videos, or uploaded. */
export function MediaPicker({ taskId, value, onChange }: { taskId: string; value: StoryMedia | null; onChange: (media: StoryMedia | null) => void }) {
  const [library, setLibrary] = useState<MediaLibrary | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const load = async () => {
    setBusy(true);
    setError('');
    try {
      setLibrary(await fetchMediaLibrary(taskId));
    } catch (failure) {
      setError(message(failure, t('项目素材加载失败')));
    } finally {
      setBusy(false);
    }
  };

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && !library) void load();
  };

  const pick = (media: StoryMedia) => {
    onChange(media);
    setOpen(false);
  };

  const upload = async (file: File) => {
    setBusy(true);
    setError('');
    try {
      const record = await uploadMedia(taskId, file, await measureVideoSeconds(file));
      setLibrary(current => (current ? { ...current, uploads: [...current.uploads, record] } : current));
      pick({ kind: record.kind, url: record.url, source: 'upload', shot_uid: null, label: record.label, duration_s: record.duration_s });
    } catch (failure) {
      setError(message(failure, t('上传失败')));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm(t('确定删除这个上传文件吗？此操作不可撤销。'))) return;
    setError('');
    try {
      setLibrary(await deleteUpload(taskId, id));
    } catch (failure) {
      setError(message(failure, t('删除失败')));
    }
  };

  // There is no per-shot generate call: this marks the clip, and the paid generation is the next stage-5 run.
  const redo = async (shot: LibraryShot) => {
    setError('');
    const admission = await fetchAdmission(taskId).catch(() => null);
    const estimate = admission
      ? `\n${t('当前批次：生成 {0} 镜，预估 {1}', [admission.counts.generate, formatCost(admission.estimate.cost, admission.estimate.currency, admission.estimate.priced)])}`
      : '';
    if (!window.confirm(t('把这一镜标记为重做？\n标记本身不花钱；之后在镜头工作区重跑第 5 阶段时才会重新生成，那是一次付费生成，其余镜头沿用。') + estimate)) return;
    try {
      await markShotForRedo(taskId, shot);
      setNotice(t('已标记重做；到镜头工作区重跑第 5 阶段后，这里就能选到新视频。'));
      await load();
    } catch (failure) {
      setError(message(failure, t('标记重做失败')));
    }
  };

  return (
    <div className="istory-media">
      {value ? (
        <div className="istory-media__current">
          {value.kind === 'video' ? (
            <video
              src={apiUrl(value.url)}
              controls
              preload="metadata"
              onLoadedMetadata={event => {
                const seconds = event.currentTarget.duration;
                if (!value.duration_s && Number.isFinite(seconds) && seconds > 0) onChange({ ...value, duration_s: Math.min(7200, seconds) });
              }}
            />
          ) : <img src={apiUrl(value.url)} alt={value.label || ''} />}
          <button type="button" className="istory-link" onClick={() => onChange(null)}><X aria-hidden="true" /> {t('移除媒体')}</button>
        </div>
      ) : <p className="istory-hint">{t('没有媒体时，试玩和导出都用文字卡。')}</p>}
      <div className="istory-inline">
        <button type="button" className="secondary-action" aria-expanded={open} onClick={toggle}><ImagePlus aria-hidden="true" /> {t('从项目选择')}</button>
        <label className="secondary-action istory-upload">
          <Upload aria-hidden="true" /> {t('上传')}
          <input
            type="file"
            aria-label={t('上传图片或视频')}
            accept="image/png,image/jpeg,image/webp,video/mp4,video/webm"
            disabled={busy}
            onChange={event => {
              const file = event.target.files?.[0];
              event.target.value = '';
              if (file) void upload(file);
            }}
          />
        </label>
      </div>
      {error && <p className="istory-error" role="alert">{error}</p>}
      {notice && <p className="istory-hint" role="status">{notice}</p>}
      {open && (
        <div className="istory-library">
          {busy && !library && <p className="istory-hint">{t('正在加载…')}</p>}
          {library && !library.shots.length && !library.films.length && !library.uploads.length && <p className="istory-hint">{t('这个项目还没有镜头或视频，可以先上传。')}</p>}
          {library?.shots.map(shot => (
            <article className="istory-library__row" key={shot.shot_uid || `${shot.scene_id}-${shot.shot_id}`}>
              {shot.image_url ? <img src={apiUrl(shot.image_url)} alt="" loading="lazy" /> : <span className="istory-library__blank" />}
              <div>
                <strong>{shot.scene_id} #{shot.shot_id}</strong>
                <p>{shot.desc}</p>
                <div className="istory-inline">
                  {shot.video_url && (
                    <button type="button" className="istory-link" onClick={() => pick({ kind: 'video', url: shot.video_url!, source: 'clip', shot_uid: shot.shot_uid, label: `${shot.scene_id} #${shot.shot_id}`, duration_s: shot.duration_s })}>
                      {t('用视频')}
                    </button>
                  )}
                  {shot.candidate_urls.map((url, index) => (
                    <button key={url} type="button" className="istory-link" onClick={() => pick({ kind: 'video', url, source: 'clip', shot_uid: shot.shot_uid, label: `${shot.scene_id} #${shot.shot_id}`, duration_s: shot.duration_s })}>
                      {t('候选 {0}', [index + 1])}
                    </button>
                  ))}
                  {shot.image_url && (
                    <button type="button" className="istory-link" onClick={() => pick({ kind: 'image', url: shot.image_url!, source: 'shot', shot_uid: shot.shot_uid, label: `${shot.scene_id} #${shot.shot_id}`, duration_s: 0 })}>
                      {t('用分镜图')}
                    </button>
                  )}
                  {shot.video_url && !shot.stale && (
                    <button type="button" className="istory-link" onClick={() => { void redo(shot); }}><RefreshCw aria-hidden="true" /> {t('标记重做')}</button>
                  )}
                </div>
                {shot.stale && <small>{t('已标记重做，等待重跑第 5 阶段')}</small>}
                {!shot.video_url && <small>{t('还没有视频：到镜头工作区运行第 5 阶段生成')}</small>}
              </div>
            </article>
          ))}
          {library?.films.map(film => (
            <article className="istory-library__row" key={film.video_url}>
              <span className="istory-library__blank" />
              <div>
                <strong>{film.label || t('成片')}</strong>
                <div className="istory-inline">
                  <button type="button" className="istory-link" onClick={() => pick({ kind: 'video', url: film.video_url, source: 'episode', shot_uid: null, label: film.label, duration_s: 0 })}>{t('用视频')}</button>
                </div>
              </div>
            </article>
          ))}
          {library?.uploads.map(item => (
            <article className="istory-library__row" key={item.id}>
              {item.kind === 'image' ? <img src={apiUrl(item.url)} alt="" loading="lazy" /> : <span className="istory-library__blank" />}
              <div>
                <strong>{item.label || t('上传文件')}</strong>
                <div className="istory-inline">
                  <button type="button" className="istory-link" onClick={() => pick({ kind: item.kind, url: item.url, source: 'upload', shot_uid: null, label: item.label, duration_s: item.duration_s })}>
                    {item.kind === 'video' ? t('用视频') : t('用图片')}
                  </button>
                  <button type="button" className="istory-link" aria-label={t('删除这个上传文件')} onClick={() => { void remove(item.id); }}><Trash2 aria-hidden="true" /></button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
