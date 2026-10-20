import { useCallback, useEffect, useRef, useState } from 'react';
import { ImagePlus, Palette, RotateCcw, Sparkles } from 'lucide-react';

import { apiRequest } from '../../api/client';
import './StyleReferencePanel.css';
import { t } from '../../i18n';

interface ProfileColour { name: string; hex: string; role: string }

export interface StyleProfile {
  name: string;
  medium: 'live_action' | 'anime_2d' | 'anime_3d' | 'mixed';
  summary: string;
  lighting: string;
  palette: ProfileColour[];
  contrast: string;
  temperature: string;
  saturation: string;
  camera_body: string;
  lens: string;
  grain: string;
  texture: string;
  composition: string;
  era: string;
  mood: string;
  lock: string[];
  positives: string[];
  negatives: string[];
  style_caption: string;
}

export interface StyleReferenceResponse {
  task_id: string;
  reference: null | { profile: StyleProfile; model: string; filename: string; analyzed_at: string; applied: boolean; base_pack: string };
  current_pack: { id: string; name: string; custom: boolean };
  previous_pack?: string | null;
  stages_with_old_look?: number[];
}

/** Only a well-formed answer is shown; anything else leaves the panel as it was. */
function isStyleReference(value: unknown): value is StyleReferenceResponse {
  const candidate = value as Partial<StyleReferenceResponse> | null;
  return Boolean(candidate && candidate.current_pack && typeof candidate.current_pack.name === 'string');
}

const MEDIUM_LABELS: Record<StyleProfile['medium'], string> = {
  live_action: '真人实拍', anime_2d: '二维动画', anime_3d: '三维动画', mixed: '混合媒介',
};

export function StyleReferencePanel({ taskId }: { taskId: string }) {
  const [data, setData] = useState<StyleReferenceResponse | null>(null);
  const [hint, setHint] = useState('');
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const fileInput = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    try {
      const answer = await apiRequest<unknown>(`/api/drama/${encodeURIComponent(taskId)}/style/reference`);
      setData(isStyleReference(answer) ? answer : null);
    } catch {
      setData(null);
    }
  }, [taskId]);

  useEffect(() => {
    const handle = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(handle);
  }, [load]);

  const analyse = async (file: File) => {
    setBusy('analyse');
    setNotice('');
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('hint', hint.trim());
      const answer = await apiRequest<unknown>(`/api/drama/${encodeURIComponent(taskId)}/style/reference`, { method: 'POST', body: form });
      if (!isStyleReference(answer)) throw new Error(t('风格分析返回格式不对'));
      setData(answer);
      setNotice(t('已读出这张图的风格；确认无误后点「设为本片风格」。'));
    } catch (caught) {
      setNotice(caught instanceof Error ? caught.message : '风格分析失败');
    } finally {
      setBusy('');
    }
  };

  const act = async (action: 'apply' | 'revert') => {
    setBusy(action);
    setNotice('');
    try {
      const answer = await apiRequest<unknown>(`/api/drama/${encodeURIComponent(taskId)}/style/reference/${action}`, { method: 'POST', body: JSON.stringify({}) });
      if (!isStyleReference(answer)) throw new Error(t('返回格式不对'));
      const result = answer;
      setData(result);
      const stale = result.stages_with_old_look ?? [];
      setNotice(action === 'apply'
        ? `已设为本片风格锁。${stale.length ? `第 ${stale.join('、')} 阶段已生成的画面仍是旧风格，重跑后才会换上新风格。` : '之后生成的画面都按它编译。'}`
        : `已恢复为「${result.current_pack.name}」。`);
    } catch (caught) {
      setNotice(caught instanceof Error ? caught.message : '操作失败');
    } finally {
      setBusy('');
    }
  };

  const profile = data?.reference?.profile;
  return (
    <section className="style-reference" aria-label={t('风格参考图')}>
      <header>
        <Palette aria-hidden="true" />
        <strong>{t('风格参考图')}</strong>
        <span>当前风格锁：{data?.current_pack?.name ?? '—'}{data?.current_pack?.custom ? '（来自参考图）' : ''}</span>
      </header>
      <p className="style-reference__hint">{t('上传一张想要的画面（电影截图、动画帧、插画），由支持看图的模型拆出光线、色板、镜头与质感，确认后成为本片的风格锁。')}</p>
      <div className="style-reference__row">
        <input aria-label={t('风格补充说明')} value={hint} onChange={event => setHint(event.target.value)} placeholder={t('补充说明（可选），如：整体再冷一点')} />
        <input ref={fileInput} type="file" hidden accept="image/png,image/jpeg,image/webp" aria-label={t('选择风格参考图')} onChange={event => { const file = event.target.files?.[0]; if (file) void analyse(file); event.target.value = ''; }} />
        <button type="button" disabled={busy !== ''} onClick={() => fileInput.current?.click()}>
          <ImagePlus aria-hidden="true" /> {busy === 'analyse' ? t('分析中…') : t('上传并分析')}
        </button>
      </div>
      {notice && <p className="style-reference__notice" role="status">{notice}</p>}

      {profile && (
        <div className="style-reference__result" aria-label={t('分析结果')}>
          <h4>{profile.name}<small>{MEDIUM_LABELS[profile.medium]} · 由 {data?.reference?.model} 分析</small></h4>
          <p>{profile.summary}</p>
          <ul className="style-reference__swatches" aria-label={t('色板')}>
            {profile.palette.map(colour => (
              <li key={colour.hex + colour.name}>
                <span className="style-reference__swatch" style={{ background: colour.hex }} aria-hidden="true" />
                <strong>{colour.name}</strong><code>{colour.hex}</code>{colour.role && <small>{colour.role}</small>}
              </li>
            ))}
          </ul>
          <dl>
            <div><dt>{t('光线')}</dt><dd>{profile.lighting}</dd></div>
            <div><dt>{t('反差 / 色温 / 饱和')}</dt><dd>{profile.contrast} / {profile.temperature} / {profile.saturation}</dd></div>
            <div><dt>{t('镜头')}</dt><dd>{[profile.camera_body, profile.lens, profile.grain].filter(Boolean).join(' · ') || '—'}</dd></div>
            <div><dt>{t('质感 / 构图')}</dt><dd>{[profile.texture, profile.composition].filter(Boolean).join(' · ') || '—'}</dd></div>
            <div><dt>{t('情绪')}</dt><dd>{[profile.mood, profile.era].filter(Boolean).join(' · ') || '—'}</dd></div>
          </dl>
          <h5>{t('锁定短语（每一张图都会复现）')}</h5>
          <ul>{profile.lock.map(line => <li key={line}>{line}</li>)}</ul>
          {profile.negatives.length > 0 && <p className="style-reference__negatives">避免：{profile.negatives.join('、')}</p>}
          <div className="style-reference__actions">
            {!data?.reference?.applied && (
              <button type="button" className="is-primary" disabled={busy !== ''} onClick={() => { void act('apply'); }}>
                <Sparkles aria-hidden="true" /> {t('设为本片风格')}
              </button>
            )}
            {data?.current_pack.custom && (
              <button type="button" disabled={busy !== ''} onClick={() => { void act('revert'); }}>
                <RotateCcw aria-hidden="true" /> {t('恢复原风格')}
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
