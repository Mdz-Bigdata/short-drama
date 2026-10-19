import { useCallback, useEffect, useState } from 'react';
import { Clapperboard, Undo2 } from 'lucide-react';

import { isApplied, listCaptures, unapplyCapture, type DeskCapture, type DeskCaptureList } from '../directorDesk/directorDeskApi';
import { t } from '../../i18n';

interface Props {
  taskId: string;
  sceneId: string;
  shotId: number;
  /** Bumped when the desk closes, so what it applied shows up without a page reload. */
  reloadToken: number;
  onOpenDesk: () => void;
}

const EMPTY: DeskCaptureList = { captures: [], applied: {} };

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

/**
 * What the 3D director desk has handed this shot, shown where the shot is worked on.
 *
 * The desk writes a still into `sequence_images` and a blockout clip into `reference_videos`; this
 * is the same record read back, so a picture taken before the blocking moved says so and can be
 * taken out again without opening the desk.
 */
export function ShotDeskPanel({ taskId, sceneId, shotId, reloadToken, onOpenDesk }: Props) {
  const [list, setList] = useState<DeskCaptureList>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  const refresh = useCallback((signal?: AbortSignal) => (
    listCaptures(taskId, sceneId, signal)
      .then(setList)
      // A scene with no desk record at all is the normal case, not a failure worth shouting about.
      .catch(() => { if (!signal?.aborted) setList(EMPTY); })
  ), [sceneId, taskId]);

  // A notice belongs to the shot it was produced for; moving to another shot is not that shot's news.
  const key = `${sceneId}:${shotId}`;
  const [shown, setShown] = useState(key);
  if (shown !== key) {
    setShown(key);
    setNotice('');
  }

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh, reloadToken]);

  const applied = list.captures.filter(capture => capture.shotId === shotId && isApplied(list, capture));
  const remove = (capture: DeskCapture) => {
    if (busy) return;
    setBusy(true);
    setNotice('');
    void unapplyCapture(taskId, sceneId, capture.id)
      .then(next => { setList(next); setNotice(t('已从第 {0} 镜取消应用。', [shotId])); })
      .catch(error => setNotice(messageOf(error, '取消应用失败。')))
      .finally(() => setBusy(false));
  };

  return (
    <section className="shot-workspace__desk" aria-label={`镜头 ${shotId} 的 3D 导演台参考`}>
      <div className="shot-workspace__desk-head">
        <strong><Clapperboard size={13} aria-hidden="true" /> {t('3D 导演台')}</strong>
        <button type="button" className="secondary-action" onClick={onOpenDesk} aria-haspopup="dialog">
          打开第 {shotId} 镜的 3D 导演台
        </button>
      </div>
      {applied.length === 0 ? (
        <p className="shot-workspace__hint">{t('本镜还没有导演台参考。打开导演台摆好站位与机位，截一张静帧或导出一段白模视频，再「应用至分镜」。')}</p>
      ) : (
        <ul className="shot-workspace__desk-list">
          {applied.map(capture => (
            <li key={capture.id} className={capture.stale ? 'is-stale' : ''}>
              <span className="shot-workspace__desk-thumb">
                {capture.kind === 'clip'
                  ? <video src={capture.url} muted loop playsInline preload="metadata" aria-label={`第 ${shotId} 镜白模视频`} />
                  : <img src={capture.url} alt={`第 ${shotId} 镜导演台静帧`} loading="lazy" />}
              </span>
              <span className="shot-workspace__desk-meta">
                <strong>{capture.kind === 'clip' ? `白模视频 · ${capture.durationS} 秒 · ${capture.fps} fps` : '导演台静帧'}</strong>
                <small>第 {capture.planRevision} 版 · {capture.width}×{capture.height}</small>
                <span className="shot-workspace__desk-badges">
                  {capture.stale && <em className="is-stale" title={t('截取之后站位已修改，第 5 阶段不会使用它')}>{t('过期')}</em>}
                  {capture.showsLimbs && <em>{t('带四肢')}</em>}
                </span>
              </span>
              <button type="button" className="secondary-action" disabled={busy} onClick={() => remove(capture)}>
                <Undo2 size={13} aria-hidden="true" /> {t('取消应用')}
              </button>
            </li>
          ))}
        </ul>
      )}
      {notice && <p className="shot-workspace__hint is-success" role="status">{notice}</p>}
    </section>
  );
}
