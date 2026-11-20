import { useState } from 'react';
import { MessagesSquare, Sparkles, X } from 'lucide-react';

import { ApiError } from '../../../api/client';
import type { SelectionRef } from '../deskTypes';
import { chatWithDirector } from '../directorApi';

interface Props {
  taskId: string;
  sceneId: string;
  /** The revision the request is based on; the server refuses one that is out of date. */
  revision: number;
  selection: SelectionRef[];
  /** Read-only, a save in flight or an export running: nothing can be asked for right now. */
  locked: boolean;
  /** The model changed the stage: read it again. */
  onPlanChanged: () => void;
  /** Take one thing out of the selection (its chip was closed). */
  onDeselect: (ref: SelectionRef) => void;
  /** Open the whole conversation, with its undo steps, in the side panel. */
  onOpenLog: () => void;
}

const MAX_CHIPS = 4;

/**
 * The AI director's one-line entry, floating over the stage: what is picked rides along as chips,
 * and the request applies to those things only. It talks to the same conversation as the 「AI 导演」
 * tab, which keeps the log and the undo steps.
 */
export function StagePrompt({ taskId, sceneId, revision, selection, locked, onPlanChanged, onDeselect, onOpenLog }: Props) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<{ text: string; failed: boolean } | null>(null);
  // Only what the model knows by name can be pointed at: figures and set pieces. A lens or a crowd is said in words.
  const named = selection.flatMap(ref => ('name' in ref ? [ref] : []));
  const names = named.map(ref => ref.name);
  const ready = !locked && !busy && text.trim() !== '';

  const send = async () => {
    if (!ready) return;
    setBusy(true);
    setAnswer(null);
    try {
      const result = await chatWithDirector(taskId, sceneId, revision, text.trim(), { names });
      setText('');
      setAnswer({ text: result.message.text || (result.changed ? '已按要求调整。' : '没有需要改动的地方。'), failed: Boolean(result.message.errors?.length) });
      if (result.changed) onPlanChanged();
    } catch (error) {
      setAnswer({ text: error instanceof ApiError && error.message ? error.message : '调整失败，请稍后重试。', failed: true });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="desk-prompt" aria-label="对 AI 导演说">
      {answer && (
        <p className={`desk-prompt__answer ${answer.failed ? 'is-failed' : ''}`} role={answer.failed ? 'alert' : 'status'}>
          <span>{answer.text}</span>
          <button type="button" className="desk-icon" aria-label="关闭回复" title="关闭" onClick={() => setAnswer(null)}><X aria-hidden="true" /></button>
        </p>
      )}
      <div className="desk-prompt__bar">
        {named.slice(0, MAX_CHIPS).map(ref => (
          <span key={`${ref.kind}:${ref.name}`} className="desk-prompt__chip" title={`只改「${ref.name}」`}>
            <span>{ref.name}</span>
            <button type="button" aria-label={`不再指定 ${ref.name}`} title="取消选中" onClick={() => onDeselect(ref)}><X aria-hidden="true" /></button>
          </span>
        ))}
        {named.length > MAX_CHIPS && <span className="desk-prompt__chip is-more">+{named.length - MAX_CHIPS}</span>}
        <input
          type="text" aria-label="想怎么改" maxLength={2000} value={text} disabled={locked || busy}
          placeholder={busy ? '模型调整中…' : names.length ? '说说要怎么改选中的对象' : '用一句话调整站位、走位或机位；先点选对象可以只改它'}
          onChange={event => setText(event.target.value)}
          onKeyDown={event => {
            // Typing here is never a desk shortcut, and Escape leaves the field rather than the desk.
            event.stopPropagation();
            if (event.key === 'Enter' && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); }
            if (event.key === 'Escape') event.currentTarget.blur();
          }}
        />
        <button type="button" className="desk-icon" aria-label="打开完整对话" title="在右侧「AI 导演」里看完整对话和撤销" onClick={onOpenLog}><MessagesSquare aria-hidden="true" /></button>
        <button type="button" className="desk-prompt__send" aria-label="发送" title="发送（回车）" disabled={!ready} onClick={() => { void send(); }}><Sparkles aria-hidden="true" /></button>
      </div>
    </section>
  );
}
