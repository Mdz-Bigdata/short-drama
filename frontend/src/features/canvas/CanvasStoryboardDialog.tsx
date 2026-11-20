import { useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, Loader2 } from 'lucide-react';

import { t } from '../../i18n';
import { fetchStoryboardScenes, layStoryboard } from './canvasApi';
import type { StoryboardLayout, StoryboardScene } from './canvasTypes';

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

/**
 * Lay the project's storyboard out on this canvas: pick scenes, see what it would add, apply.
 *
 * Every shot becomes a first frame feeding a video node bound to that shot, a scene per group
 * (`backend/app/core/canvas_storyboard.py`). Laying out costs nothing; running the nodes is the
 * usual quoted step. The capability follows NovaNova Studio's storyboard-to-canvas flow (MIT).
 */
export function CanvasStoryboardDialog({ projectId, canvasId, clientId, prepare, onApplied, onClose }: {
  projectId: string;
  canvasId: string;
  /** The asking window: it reloads the result itself, so it is not also told the canvas changed elsewhere. */
  clientId?: string;
  /** Saves what is unsaved and answers the version to lay out on; rejects when the canvas cannot be saved. */
  prepare: () => Promise<number>;
  onApplied: (nodeIds: string[]) => void | Promise<void>;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const [scenes, setScenes] = useState<StoryboardScene[] | null>(null);
  const [limit, setLimit] = useState(0);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const [done, setDone] = useState<StoryboardLayout | null>(null);

  useEffect(() => {
    panel.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onClose]);

  useEffect(() => {
    const abort = new AbortController();
    fetchStoryboardScenes(projectId, canvasId, abort.signal)
      .then(data => {
        setScenes(data.scenes);
        setLimit(data.max_shots);
        setPicked(new Set(data.scenes.filter(scene => scene.new > 0).map(scene => scene.scene_id)));
      })
      .catch(error => { if (!abort.signal.aborted) setProblem(messageOf(error, t('读取分镜失败'))); });
    return () => abort.abort();
  }, [canvasId, projectId]);

  const count = useMemo(
    () => (scenes ?? []).filter(scene => picked.has(scene.scene_id)).reduce((sum, scene) => sum + scene.new, 0),
    [picked, scenes],
  );
  const over = limit > 0 && count > limit;

  const toggle = (sceneId: string) => setPicked(current => {
    const next = new Set(current);
    if (next.has(sceneId)) next.delete(sceneId); else next.add(sceneId);
    return next;
  });

  const apply = async () => {
    if (busy || !count || over) return;
    setBusy(true);
    setProblem('');
    try {
      const version = await prepare();
      const result = await layStoryboard(projectId, canvasId, { sceneIds: [...picked], expectedVersion: version, clientId });
      setDone(result);
      await onApplied(result.node_ids ?? []);
    } catch (error) {
      setProblem(messageOf(error, t('铺分镜失败')));
    } finally {
      setBusy(false);
    }
  };

  const title = t('把分镜铺到画布');
  return (
    <div className="cn-dialog-backdrop">
      <div ref={panel} className="cn-dialog" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
        <h2>{title}</h2>
        {!scenes && !problem && <p className="cn-hint">{t('读取中…')}</p>}
        {scenes && !done && (
          <>
            <p className="cn-hint">{t('每个镜头变成一对节点：首帧 → 视频，视频节点绑定到这一镜，提交时写回它。铺上去不花钱，运行时照常报价。')}</p>
            {scenes.length === 0 && <p className="cn-hint">{t('项目还没有分镜。')}</p>}
            <ul className="cn-dialog__rows">
              {scenes.map(scene => (
                <li key={scene.scene_id} className={scene.new ? '' : 'is-skipped'}>
                  <label>
                    <input type="checkbox" checked={picked.has(scene.scene_id)} disabled={!scene.new} onChange={() => toggle(scene.scene_id)} />{' '}
                    <strong style={{ display: 'inline' }}>{scene.scene_id}</strong>
                  </label>
                  <small>{scene.new === scene.shots ? t('{0} 个镜头', [scene.shots]) : scene.new ? t('{0} 个镜头，其中 {1} 个还没铺', [scene.shots, scene.new]) : t('{0} 个镜头，都已在画布上', [scene.shots])}</small>
                </li>
              ))}
            </ul>
            <p className="cn-dialog__cost">{t('将铺 {0} 个镜头', [count])}</p>
            {over && <p className="cn-error" role="alert">{t('一次最多铺 {0} 个镜头，少选几场。', [limit])}</p>}
          </>
        )}
        {done && (
          <p className="cn-dialog__cost">
            <CheckCircle2 aria-hidden="true" /> {t('已铺 {0} 个镜头：{1} 个首帧待生成，新增 {2} 张定妆图', [done.shots, done.frames_to_draw, done.cast])}
          </p>
        )}
        {problem && <p className="cn-error" role="alert">{problem}</p>}
        <footer className="cn-dialog__foot">
          <button type="button" className="cn-button" onClick={onClose}>{done ? t('完成') : t('取消')}</button>
          {!done && (
            <button type="button" className="cn-button is-primary" disabled={busy || !count || over} onClick={() => { void apply(); }}>
              {busy && <Loader2 className="cn-spin" aria-hidden="true" />} {t('铺到画布')}
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
