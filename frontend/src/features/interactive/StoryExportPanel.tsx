import { Download, FileArchive, FileCode } from 'lucide-react';
import { useEffect, useState } from 'react';

import { t } from '../../i18n';
import { downloadExport, fetchExportPreview } from './interactiveApi';
import { issueText } from './issueText';
import type { ExportPreview } from './storyTypes';

const megabytes = (bytes: number) => `${(bytes / (1024 * 1024)).toFixed(1)} MB`;

export function StoryExportPanel({ taskId, title, dirty, revision }: { taskId: string; title: string; dirty: boolean; revision: number }) {
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<'html' | 'zip' | null>(null);
  const [done, setDone] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    fetchExportPreview(taskId, controller.signal)
      .then(setPreview)
      .catch((failure: unknown) => {
        if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : t('导出信息加载失败'));
      });
    return () => controller.abort();
  }, [taskId, revision]);

  const download = async (format: 'html' | 'zip') => {
    setBusy(format);
    setError('');
    setDone('');
    try {
      await downloadExport(taskId, format, (title || 'interactive-story').replace(/[\\/:*?"<>|]+/g, '_').slice(0, 60));
      setDone(format === 'html' ? t('已开始下载 HTML 播放器。') : t('已开始下载离线 ZIP 包。'));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : t('导出失败'));
    } finally {
      setBusy(null);
    }
  };

  const STATUS: Record<string, string> = {
    local: t('本机文件'), remote: t('服务商链接，导出时下载'), expired: t('链接已过期，只能显示文字卡'), missing: t('文件不存在，只能显示文字卡'),
  };
  const ready = Boolean(preview?.ready);
  return (
    <div className="istory-report">
      {dirty && <p className="istory-warning" role="status">{t('有未保存的修改：导出的是上次保存的版本，请先保存。')}</p>}
      {error && <p className="istory-error" role="alert">{error}</p>}
      {done && <p className="istory-hint" role="status">{done}</p>}
      {preview && !preview.ready && (
        <section className="istory-section">
          <h3>{t('还不能导出')}</h3>
          {!preview.errors.length && <p className="istory-hint">{t('请先保存故事。')}</p>}
          <ul className="istory-issues">
            {preview.errors.map((issue, index) => <li className="is-error" key={index}><span>{issueText(issue)}</span></li>)}
          </ul>
        </section>
      )}
      <div className="istory-export-cards">
        <article className="istory-card">
          <h3><FileCode aria-hidden="true" /> {t('单文件 HTML 播放器')}</h3>
          <p>{t('一个文件就能播放，不发任何网络请求。图片和较小的视频直接写进文件（合计不超过 {0}），放不下的片段显示文字卡。', [preview ? megabytes(preview.inline_limit_bytes) : '64 MB'])}</p>
          <button type="button" className="primary-action" disabled={!ready || busy !== null} onClick={() => { void download('html'); }}>
            <Download aria-hidden="true" /> {busy === 'html' ? t('正在生成…') : t('下载 HTML')}
          </button>
        </article>
        <article className="istory-card">
          <h3><FileArchive aria-hidden="true" /> {t('离线 ZIP 包')}</h3>
          <p>{t('播放器加上全部视频，解压后打开 index.html 即可，适合发给别人或离线观看。')}</p>
          <button type="button" className="primary-action" disabled={!ready || busy !== null} onClick={() => { void download('zip'); }}>
            <Download aria-hidden="true" /> {busy === 'zip' ? t('正在打包…') : t('下载 ZIP')}
          </button>
        </article>
      </div>
      <p className="istory-hint">{t('两种格式都支持分支播放、限时选择、在本机保存探索进度，并能从已解锁的片段重看。')}</p>
      {preview && preview.media.length > 0 && (
        <section className="istory-section">
          <h3>{t('媒体')}（{preview.media.length}）</h3>
          <div className="istory-table-wrap">
            <table className="istory-table">
              <thead><tr><th>{t('片段')}</th><th>{t('类型')}</th><th>{t('状态')}</th><th>{t('大小')}</th></tr></thead>
              <tbody>
                {preview.media.map(row => (
                  <tr key={row.segment_id}>
                    <td>{row.title}</td>
                    <td>{row.kind === 'video' ? t('视频') : t('图片')}</td>
                    <td>{STATUS[row.status]}</td>
                    <td className="istory-num">{row.size ? megabytes(row.size) : '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
