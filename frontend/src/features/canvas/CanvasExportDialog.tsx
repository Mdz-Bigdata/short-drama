import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, FileJson, Loader2, Package } from 'lucide-react';

import { t } from '../../i18n';
import { downloadBundle, saveBlob } from './canvasBundleApi';

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function sizeOf(bytes: number) {
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/**
 * Two ways out: the canvas alone (a JSON whose media stay links to this server), or the canvas with its media
 * packed in one zip that opens on another project or server. The packing follows NovaNova Studio's ZIP export (MIT).
 */
export function CanvasExportDialog({ projectId, canvasId, title, prepare, onExportJson, onClose }: {
  projectId: string;
  canvasId: string;
  title: string;
  /** Saves what is unsaved first, so the server packs what the person sees; rejects when the canvas cannot be saved. */
  prepare: () => Promise<unknown>;
  onExportJson: () => void;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const [done, setDone] = useState<{ fileName: string; size: number } | null>(null);

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

  const pack = async () => {
    if (busy) return;
    setBusy(true);
    setProblem('');
    try {
      await prepare();
      const result = await downloadBundle(projectId, canvasId, `${title || t('画布')}.novara-canvas.zip`);
      saveBlob(result.blob, result.fileName);
      setDone({ fileName: result.fileName, size: result.blob.size });
    } catch (error) {
      setProblem(messageOf(error, t('打包失败')));
    } finally {
      setBusy(false);
    }
  };

  const heading = t('导出画布');
  return (
    <div className="cn-dialog-backdrop">
      <div ref={panel} className="cn-dialog" role="dialog" aria-modal="true" aria-label={heading} tabIndex={-1}>
        <h2>{heading}</h2>
        <ul className="cn-dialog__rows">
          <li>
            <strong><FileJson aria-hidden="true" /> {t('只导出画布（.json）')}</strong>
            <small>{t('文件小；图片、视频和声音保留为本服务器上的链接，换了服务器或文件被删后会显示为空。')}</small>
          </li>
          <li>
            <strong><Package aria-hidden="true" /> {t('连同素材打包（.zip）')}</strong>
            <small>{t('画布和它用到的本服务器媒体文件打成一个包，可以导入到别的项目或服务器。元素库的私有图片不打包，外站链接原样保留。')}</small>
          </li>
        </ul>
        {done && (
          <p className="cn-dialog__cost"><CheckCircle2 aria-hidden="true" /> {t('已下载 {0}（{1}）', [done.fileName, sizeOf(done.size)])}</p>
        )}
        {problem && <p className="cn-error" role="alert">{problem}</p>}
        <footer className="cn-dialog__foot">
          <button type="button" className="cn-button" onClick={onClose}>{done ? t('完成') : t('取消')}</button>
          <button type="button" className="cn-button" onClick={() => { onExportJson(); onClose(); }}>{t('导出 .json')}</button>
          <button type="button" className="cn-button is-primary" disabled={busy} onClick={() => { void pack(); }}>
            {busy && <Loader2 className="cn-spin" aria-hidden="true" />} {t('打包 .zip')}
          </button>
        </footer>
      </div>
    </div>
  );
}
