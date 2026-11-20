import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';

import { t } from '../../i18n';

export interface LightboxMedia {
  medium: 'image' | 'video';
  url: string;
  title: string;
}

/** One picture or clip, large, over the canvas. Escape, the close button or the backdrop put it away. */
export function CanvasLightbox({ media, onClose }: { media: LightboxMedia; onClose: () => void }) {
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    close.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.stopPropagation();
      onClose();
    };
    // Capture: the canvas has shortcuts of its own on Escape, and this one comes first.
    window.addEventListener('keydown', key, true);
    return () => window.removeEventListener('keydown', key, true);
  }, [onClose]);
  const label = media.medium === 'video' ? t('播放：{0}', [media.title]) : t('放大查看：{0}', [media.title]);
  return (
    <div className="cn-lightbox" role="dialog" aria-modal="true" aria-label={label} onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
      <header className="cn-lightbox__bar">
        <strong>{media.title}</strong>
        <button ref={close} type="button" className="cn-icon" onClick={onClose} aria-label={t('关闭预览')} title={t('关闭预览')}><X aria-hidden="true" /></button>
      </header>
      {media.medium === 'video'
        ? <video className="cn-lightbox__media" src={media.url} controls autoPlay playsInline />
        : <img className="cn-lightbox__media" src={media.url} alt={media.title} />}
    </div>
  );
}
