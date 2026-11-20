import { t } from '../../i18n';
import { downloadMedia, safeFileStem } from './canvasNodeActions';
import type { CanvasNode, NodeOutput } from './canvasTypes';

/** What 抠像序列帧 made: how many frames of what size, and the ZIP they are in. The picture above it is the sprite sheet. */
export function SpriteFramesResult({ node, output }: { node: Pick<CanvasNode, 'payload'>; output: NodeOutput }) {
  const sprite = output.sprite;
  const zip = output.zip;
  if (!zip) return null;
  const name = `${safeFileStem(String(node.payload.label || node.payload.title || '')) || 'sprite-frames'}.zip`;
  return (
    <>
      {sprite ? (
        <p className="cn-hint" role="status">
          {t('{0} 帧 · 每帧 {1}×{2} · {3} 帧/秒', [sprite.count, sprite.frame_width, sprite.frame_height, sprite.fps])}
          {sprite.sheet ? ` · ${t('精灵图 {0} 列 × {1} 行', [sprite.sheet.columns, sprite.sheet.rows])}` : ''}
        </p>
      ) : null}
      {sprite && !sprite.sheet ? <p className="cn-hint cn-warn" role="status">{t('帧太多，没有拼成精灵图：这里显示的是第一帧，全部帧都在 ZIP 里')}</p> : null}
      <div className="cn-row">
        <button type="button" className="cn-button" onClick={() => { void downloadMedia(zip, name); }}>{t('下载 ZIP')}</button>
      </div>
    </>
  );
}
