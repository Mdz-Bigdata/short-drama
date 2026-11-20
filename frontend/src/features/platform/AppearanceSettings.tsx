import { useEffect, useState } from 'react';
import { ImageUp, LoaderCircle, Palette, Trash2 } from 'lucide-react';

import { apiRequest, apiUrl } from '../../api/client';
import { t } from '../../i18n';
import type { AppearanceText, LogoFrame, PublicAppearance } from '../../appearance/appearance';
import './AppearanceSettings.css';

interface SlotRule {
  id: 'logo' | 'favicon';
  label: string;
  max_bytes: number;
  max_side: number;
}

export interface AppearanceEditView extends PublicAppearance {
  fields: { id: AppearanceText; label: string; max: number }[];
  logo_frames: LogoFrame[];
  slots: SlotRule[];
  formats: string[];
}

const FIELD_LABELS: Record<AppearanceText, string> = {
  brand_name: '品牌名', login_tagline: '登录页副标题', lobby_tagline: '大厅品牌标签', assistant_name: '助手名',
};
const FIELD_HINTS: Record<AppearanceText, string> = {
  brand_name: '留空用内置名称 Novara', login_tagline: '留空用内置副标题', lobby_tagline: '留空用内置标签', assistant_name: '留空用「品牌名 AI」',
};
const FRAME_LABELS: Record<LogoFrame, string> = { rounded: '圆角', square: '方形', circle: '圆形', none: '不加外框' };
const SLOT_LABELS: Record<SlotRule['id'], string> = { logo: 'Logo', favicon: '网页图标' };

function sizeText(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`;
}

function textOf(view: AppearanceEditView): Record<AppearanceText, string> {
  return Object.fromEntries(view.fields.map(field => [field.id, view[field.id] ?? ''])) as Record<AppearanceText, string>;
}

/** The deployment's brand: names, taglines, the logo and its frame, and the page icon. Administrators only. */
export function AppearanceSettings() {
  const [view, setView] = useState<AppearanceEditView | null>(null);
  const [text, setText] = useState<Record<AppearanceText, string> | null>(null);
  const [frame, setFrame] = useState<LogoFrame>('rounded');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const accept = (data: AppearanceEditView, keepText = false) => {
    setView(data);
    if (!keepText) {
      setText(textOf(data));
      setFrame(data.logo_frame);
    }
  };

  useEffect(() => {
    let active = true;
    apiRequest<AppearanceEditView>('/api/platform/appearance')
      .then(data => { if (active && Array.isArray(data?.fields)) accept(data); })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : t('品牌外观加载失败')); });
    return () => { active = false; };
  }, []);

  const run = async (key: string, action: () => Promise<AppearanceEditView>, keepText = false) => {
    setBusy(key);
    setError('');
    setNotice('');
    try {
      accept(await action(), keepText);
      setNotice(t('已保存；新打开的页面会用新的外观。'));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('品牌外观没有保存'));
    } finally {
      setBusy('');
    }
  };

  const saveText = () => run('text', () => apiRequest<AppearanceEditView>('/api/platform/appearance', {
    method: 'PUT', body: JSON.stringify({ text, logo_frame: frame }),
  }));

  const upload = (slot: SlotRule['id'], file: File | undefined) => {
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    void run(`upload:${slot}`, () => apiRequest<AppearanceEditView>(`/api/platform/appearance/assets/${slot}`, { method: 'POST', body: form }), true);
  };

  const remove = (slot: SlotRule['id']) => run(
    `remove:${slot}`, () => apiRequest<AppearanceEditView>(`/api/platform/appearance/assets/${slot}`, { method: 'DELETE' }), true,
  );

  if (!view || !text) {
    return error ? <div className="inline-error" role="alert">{error}</div> : null;
  }

  const changed = view.fields.some(field => (text[field.id] ?? '').trim() !== (view[field.id] ?? '')) || frame !== view.logo_frame;
  const tooLong = view.fields.some(field => (text[field.id] ?? '').trim().length > field.max);

  return (
    <section className="appearance-settings" aria-labelledby="appearance-settings-title">
      <h4 id="appearance-settings-title"><Palette size={16} aria-hidden="true" /> {t('品牌外观')}</h4>
      <p className="appearance-settings__lead">{t('登录页、大厅和助手显示的名称、Logo 与网页图标。没填的项用内置的说法，并随界面语言翻译。')}</p>
      {error && <div className="inline-error" role="alert">{error}</div>}
      {notice && <div className="command-result" role="status">{notice}</div>}
      <div className="appearance-settings__grid">
        <div className="appearance-settings__fields">
          {view.fields.map(field => (
            <label key={field.id}>
              {t(FIELD_LABELS[field.id])}
              <input
                value={text[field.id]} maxLength={field.max * 2} placeholder={t(FIELD_HINTS[field.id])}
                onChange={event => setText(current => ({ ...current!, [field.id]: event.target.value }))}
              />
            </label>
          ))}
          <label>
            {t('Logo 外框')}
            <select value={frame} onChange={event => setFrame(event.target.value as LogoFrame)}>
              {view.logo_frames.map(item => <option key={item} value={item}>{t(FRAME_LABELS[item])}</option>)}
            </select>
          </label>
          <button type="button" onClick={() => void saveText()} disabled={!changed || tooLong || busy !== ''}>
            {busy === 'text' && <LoaderCircle className="spin" size={14} />}
            {t('保存文字与外框')}
          </button>
        </div>
        <div className="appearance-settings__slots">
          {view.slots.map(slot => {
            const url = view.assets[slot.id];
            return (
              <div className="appearance-settings__slot" key={slot.id}>
                <div className={`appearance-settings__preview appearance-settings__preview--${slot.id === 'logo' ? frame : 'square'}`}>
                  {url ? <img src={apiUrl(url)} alt={t(SLOT_LABELS[slot.id])} /> : <span>{t('内置')}</span>}
                </div>
                <div>
                  <strong>{t(SLOT_LABELS[slot.id])}</strong>
                  <small>{t('{0}，不超过 {1}，边长不超过 {2} 像素', [view.formats.join(' / '), sizeText(slot.max_bytes), slot.max_side])}</small>
                  <div className="appearance-settings__slot-actions">
                    <label className={`appearance-settings__upload ${busy !== '' ? 'is-disabled' : ''}`}>
                      {busy === `upload:${slot.id}` ? <LoaderCircle className="spin" size={14} /> : <ImageUp size={14} />}
                      {url ? t('更换') : t('上传')}
                      <input
                        type="file" accept="image/png,image/jpeg,image/webp" disabled={busy !== ''}
                        aria-label={t('上传{0}', [t(SLOT_LABELS[slot.id])])}
                        onChange={event => { upload(slot.id, event.target.files?.[0]); event.target.value = ''; }}
                      />
                    </label>
                    {url && (
                      <button type="button" onClick={() => void remove(slot.id)} disabled={busy !== ''} aria-label={t('移除{0}', [t(SLOT_LABELS[slot.id])])}>
                        <Trash2 size={14} /> {t('恢复内置')}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
