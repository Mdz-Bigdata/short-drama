// Idea from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors): share a canvas read-only by link.
import { useEffect, useRef, useState } from 'react';
import { Copy, Link2, RefreshCw, Share2, Unlink, X } from 'lucide-react';

import { t } from '../../i18n';
import {
  SHARE_EXPIRY_CHOICES, createCanvasShare, getCanvasShare, shareExpiryDays, shareExpiryText, shareUrl, stopCanvasShare, type CanvasShare, type ShareExpiryDays,
} from './canvasShareApi';
import './CanvasShareDialog.css';

export interface CanvasShareDialogProps {
  projectId: string;
  canvasId: string;
  canvasTitle: string;
  onClose: () => void;
}

function expiryChoiceLabel(days: ShareExpiryDays) {
  switch (days) {
    case 1: return t('1 天');
    case 7: return t('7 天');
    case 30: return t('30 天');
    case null: return t('永久');
  }
}

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

/** Create, copy, rotate or stop the read-only link to one canvas. */
export function CanvasShareDialog({ projectId, canvasId, canvasTitle, onClose }: CanvasShareDialogProps) {
  const [loading, setLoading] = useState(true);
  const [share, setShare] = useState<CanvasShare | null>(null);
  const [days, setDays] = useState<ShareExpiryDays>(7);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState<'' | 'copied' | 'selected'>('');
  const input = useRef<HTMLInputElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; });

  useEffect(() => {
    const controller = new AbortController();
    getCanvasShare(projectId, canvasId, controller.signal)
      .then(current => setShare(current ?? null))
      .catch(reason => {
        if (!controller.signal.aborted) setError(messageOf(reason, t('读取分享状态失败')));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [canvasId, projectId]);

  // Escape closes the dialog, and only the dialog: the canvas underneath must not clear its selection too.
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopPropagation();
      closeRef.current();
    };
    window.addEventListener('keydown', key, true);
    return () => window.removeEventListener('keydown', key, true);
  }, []);

  useEffect(() => { dialog.current?.focus(); }, []);

  const create = async (expires: ShareExpiryDays) => {
    setBusy(true);
    setError('');
    setCopied('');
    try {
      setShare(await createCanvasShare(projectId, canvasId, expires));
    } catch (reason) {
      setError(messageOf(reason, t('创建链接失败')));
    } finally {
      setBusy(false);
    }
  };

  const rotate = () => {
    if (!share || !window.confirm(t('换一个链接后，旧链接会立即失效，已经发出去的旧链接都打不开了。确定换吗？'))) return;
    void create(shareExpiryDays(share));
  };

  const stop = async () => {
    if (!window.confirm(t('停止分享后，这个链接马上失效，拿到链接的人都打不开了。确定停止吗？'))) return;
    setBusy(true);
    setError('');
    try {
      await stopCanvasShare(projectId, canvasId);
      setShare(null);
      setCopied('');
    } catch (reason) {
      setError(messageOf(reason, t('停止分享失败')));
    } finally {
      setBusy(false);
    }
  };

  const url = share ? shareUrl(share) : '';

  const copy = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('no clipboard');
      await navigator.clipboard.writeText(url);
      setCopied('copied');
    } catch {
      // No clipboard access (insecure origin, refused permission): select the link for a manual copy.
      input.current?.focus();
      input.current?.select();
      setCopied('selected');
    }
  };

  return (
    <div className="csh-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={dialog} className="csh-dialog" role="dialog" aria-modal="true" aria-labelledby="csh-title" tabIndex={-1}>
        <header className="csh-head">
          <Share2 aria-hidden="true" />
          <div className="csh-heading">
            <h2 id="csh-title">{t('分享画布')}</h2>
            <span className="csh-subtitle" title={canvasTitle}>{canvasTitle}</span>
          </div>
          <button type="button" className="csh-close" onClick={onClose} aria-label={t('关闭')} title={t('关闭')}><X aria-hidden="true" /></button>
        </header>

        <p className="csh-note">{t('拿到链接的人不用登录就能看这张画布和其中的图片视频，不能修改。')}</p>

        {loading ? (
          <p className="csh-status" role="status">{t('正在读取分享状态…')}</p>
        ) : share ? (
          <div className="csh-body">
            <label className="csh-label" htmlFor="csh-url">{t('只读链接')}</label>
            <div className="csh-url-row">
              <input
                id="csh-url" ref={input} className="csh-url" type="text" readOnly value={url}
                onFocus={event => event.currentTarget.select()}
              />
              <button type="button" className="csh-button is-primary" onClick={() => { void copy(); }} disabled={busy}>
                <Copy aria-hidden="true" /> {t('复制链接')}
              </button>
            </div>
            {copied && (
              <p className="csh-copied" role="status">
                {copied === 'copied' ? t('已复制到剪贴板') : t('已选中链接，按 Ctrl+C（Mac 上 ⌘C）复制')}
              </p>
            )}
            <p className="csh-expiry">{shareExpiryText(share.expires_at)}</p>
            <div className="csh-actions">
              <button type="button" className="csh-button" onClick={rotate} disabled={busy}><RefreshCw aria-hidden="true" /> {t('换一个链接')}</button>
              <button type="button" className="csh-button is-danger" onClick={() => { void stop(); }} disabled={busy}><Unlink aria-hidden="true" /> {t('停止分享')}</button>
            </div>
          </div>
        ) : (
          <div className="csh-body">
            <fieldset className="csh-expiry-choices">
              <legend className="csh-label">{t('有效期')}</legend>
              {SHARE_EXPIRY_CHOICES.map(choice => (
                <label key={String(choice)} className={`csh-choice${days === choice ? ' is-active' : ''}`}>
                  <input type="radio" name="csh-expiry" checked={days === choice} onChange={() => setDays(choice)} />
                  {expiryChoiceLabel(choice)}
                </label>
              ))}
            </fieldset>
            <div className="csh-actions">
              <button type="button" className="csh-button is-primary" onClick={() => { void create(days); }} disabled={busy}>
                <Link2 aria-hidden="true" /> {t('创建只读链接')}
              </button>
            </div>
          </div>
        )}

        {error && <p className="csh-error" role="alert">{error}</p>}
      </div>
    </div>
  );
}
