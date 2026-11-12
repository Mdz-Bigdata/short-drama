import { Send, Wand2 } from 'lucide-react';
import { useState, type KeyboardEvent } from 'react';
import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import type { FaceSculptValue } from './CharacterFaceSculpt';
import './FaceSculptInstruct.css';

/**
 * 用一句话捏脸：把「鼻梁再高一点，眼睛改成丹凤眼」交给服务端翻成控件改动。
 *
 * 这里只提议、不保存(apply=false)：拿回来的整份 sculpt 交给外层面板当作未保存的改动，
 * 预览、脏标记、保存按钮都走面板原来的那一套；服务端没认出来的半句话原样列出来，
 * 用户自己补控件。
 */

/** 服务端预览的最小形状；CharacterFaceSculpt 没导出它的 Preview，这里只声明用得到的字段。 */
export interface FaceInstructPreview {
  description: string;
  face_text: string;
  layers: Record<string, string>;
  issues: { code: string; message: string }[];
  expressions: Record<string, string>;
  sheet_stale: boolean;
  stale_note: string;
}

export interface FaceInstructMeta {
  reply: string;
  unknown: string[];
  preview: FaceInstructPreview;
}

interface InstructResponse {
  reply: string;
  patch: Record<string, unknown>;
  unknown: string[];
  sculpt: FaceSculptValue;
  preview: FaceInstructPreview;
  saved: boolean;
  current: unknown;
}

export function FaceSculptInstruct({ taskId, characterName, busy = false, onProposed }: {
  taskId: string;
  characterName: string;
  /** 外层正在保存或读取时先别发：改动会和正在落盘的那份打架。 */
  busy?: boolean;
  /** 服务端翻好的整份捏脸值和它的说明；外层把 next 放进未保存的改动。 */
  onProposed: (next: FaceSculptValue, meta: FaceInstructMeta) => void;
}) {
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [reply, setReply] = useState('');
  const [unknown, setUnknown] = useState<string[]>([]);
  const [error, setError] = useState('');
  const disabled = busy || sending;

  const send = async () => {
    const message = text.trim();
    if (!message || disabled) return;
    setSending(true);
    setError('');
    try {
      const path = `/api/drama/${encodeURIComponent(taskId)}/characters/${encodeURIComponent(characterName)}/face-sculpt/instruct`;
      const data = await apiRequest<InstructResponse>(path, { method: 'POST', body: JSON.stringify({ message, apply: false }) });
      const missed = Array.isArray(data.unknown) ? data.unknown.filter(item => typeof item === 'string' && item) : [];
      setReply(data.reply || '');
      setUnknown(missed);
      setText('');
      onProposed(data.sculpt, { reply: data.reply || '', unknown: missed, preview: data.preview });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('没捏成，请再说一遍'));
    } finally {
      setSending(false);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    // 中文输入法选字时的回车不算发送。
    if (event.key !== 'Enter' || event.nativeEvent.isComposing || event.shiftKey) return;
    event.preventDefault();
    void send();
  };

  return (
    <div className="face-instruct">
      <div className="face-instruct__row">
        <Wand2 size={14} aria-hidden="true" className="face-instruct__icon" />
        <input
          type="text"
          className="face-instruct__input"
          value={text}
          disabled={disabled}
          aria-label={t('用一句话捏')}
          placeholder={t('用一句话捏（如：鼻梁再高一点，眼睛改成丹凤眼）')}
          onChange={event => setText(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <button type="button" className="face-instruct__send" disabled={disabled || !text.trim()} aria-label={t('发送')} onClick={() => { void send(); }}>
          <Send size={14} aria-hidden="true" />
          <span>{sending ? t('捏中…') : t('捏')}</span>
        </button>
      </div>
      {error && <p className="face-instruct__error" role="alert">{error}</p>}
      {!error && reply && <p className="face-instruct__reply" role="status">{reply}</p>}
      {!error && unknown.length > 0 && (
        <p className="face-instruct__unknown">{t('没认出来：{items}', { items: unknown.join('；') })}</p>
      )}
    </div>
  );
}
