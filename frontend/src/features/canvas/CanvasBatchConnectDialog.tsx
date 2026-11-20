import { useEffect, useRef, useState } from 'react';

import { t } from '../../i18n';
import type { VideoTarget } from './canvasBatchConnect';
import './CanvasNodeActions.css';

const NEW_TARGET = '';

/**
 * Pick the video node several selected pictures and clips are wired to: one already on the board, or a new one.
 *
 * The connecting itself is `canvasBatchConnect.ts` and one document edit, so it can be undone.
 * After NovaNova Studio's canvas batch connect (MIT); the implementation is this project's own.
 */
export function CanvasBatchConnectDialog({ count, targets, onConfirm, onClose }: {
  /** How many selected nodes will be connected. */
  count: number;
  targets: readonly VideoTarget[];
  /** The chosen video node's id, or null for "make a new one". */
  onConfirm: (targetId: string | null) => void;
  onClose: () => void;
}) {
  const panel = useRef<HTMLFormElement>(null);
  const [picked, setPicked] = useState<string>(targets[0]?.id ?? NEW_TARGET);

  useEffect(() => {
    panel.current?.querySelector<HTMLInputElement>('input:checked')?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onClose]);

  const title = t('连到视频节点');
  return (
    <div className="cn-dialog-backdrop">
      <form
        ref={panel} className="cn-dialog" role="dialog" aria-modal="true" aria-label={title}
        onSubmit={event => { event.preventDefault(); onConfirm(picked === NEW_TARGET ? null : picked); }}
      >
        <h2>{title}</h2>
        <p className="cn-hint">{t('把选中的 {0} 个图片 / 视频节点连到同一个视频节点上，按从左到右、从上到下的顺序。已经连着的和连不上的会跳过。', [count])}</p>
        <ul className="cn-dialog__rows cbc-targets">
          {targets.map(target => (
            <li key={target.id}>
              <label>
                <input type="radio" name="cbc-target" value={target.id} checked={picked === target.id} onChange={() => setPicked(target.id)} />{' '}
                <strong>{target.label}</strong>
              </label>
              <small>{target.inputs ? t('已有 {0} 条输入', [target.inputs]) : t('还没有输入')}</small>
            </li>
          ))}
          <li>
            <label>
              <input type="radio" name="cbc-target" value={NEW_TARGET} checked={picked === NEW_TARGET} onChange={() => setPicked(NEW_TARGET)} />{' '}
              <strong>{t('新建视频节点')}</strong>
            </label>
            <small>{t('放在所选节点的右边')}</small>
          </li>
        </ul>
        <footer className="cn-dialog__foot">
          <button type="button" className="cn-button" onClick={onClose}>{t('取消')}</button>
          <button type="submit" className="cn-button is-primary">{t('连接')}</button>
        </footer>
      </form>
    </div>
  );
}
