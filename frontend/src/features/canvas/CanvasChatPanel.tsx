import { useEffect, useRef, useState } from 'react';
import { Bot, Check, Loader2, Send, X } from 'lucide-react';

import { t } from '../../i18n';
import { chatContext, sendCanvasChat, type AssistantTurn } from './canvasChat';
import { kindLabel, nodeTitle } from './canvasLabels';
import type { CanvasNode } from './canvasTypes';

interface Message {
  id: number;
  from: 'me' | 'assistant';
  text: string;
  /** Mine: the nodes that went along. */
  attached?: string[];
  /** The assistant's: what it used, what it asks to be confirmed, and whether this is a failure to reach it. */
  turn?: AssistantTurn;
  problem?: boolean;
}

interface PanelProps {
  taskId: string;
  canvasId: string;
  /** The selected nodes: what "this node" means in the next message, unless detached. */
  selected: readonly CanvasNode[];
  hidden?: boolean;
  /** Save what is on screen first, so the assistant reads the canvas the person is looking at. */
  flush: () => Promise<boolean>;
  /** The assistant wrote the canvas: bring the new version in and show what changed. */
  onCanvasChanged: (version: number, nodeIds: string[]) => void;
  onJump: (nodeId: string) => void;
}

function messageOf(error: unknown) {
  return error instanceof Error && error.message ? error.message : t('没有连上助手，稍后再试。');
}

/**
 * The project's assistant, inside the canvas. It is the same conversation as the one in the
 * workbench sidebar; what the canvas adds is the board that is open and the nodes that are selected.
 */
export function CanvasChatPanel({ taskId, canvasId, selected, hidden = false, flush, onCanvasChanged, onJump }: PanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [attach, setAttach] = useState(true);
  const nextId = useRef(1);
  const log = useRef<HTMLDivElement>(null);
  const alive = useRef(true);
  useEffect(() => {
    // Set on every mount: in development React mounts, unmounts and mounts again, and the flag must end up true.
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  useEffect(() => {
    const element = log.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [messages, busy]);

  const attached = attach ? selected : [];
  const lastId = messages.at(-1)?.id;

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || busy) return;
    const fromDraft = text === draft;
    setBusy(true);
    if (fromDraft) setDraft('');
    setMessages(current => [...current, { id: nextId.current++, from: 'me', text: message, attached: attached.map(nodeTitle) }]);
    const answer = (entry: Omit<Message, 'id' | 'from'>) => {
      if (alive.current) setMessages(current => [...current, { id: nextId.current++, from: 'assistant', ...entry }]);
    };
    try {
      if (!await flush()) {
        answer({ text: t('画布还没保存成功，助手读到的会是旧画布。先解决保存问题再发。'), problem: true });
        if (fromDraft && alive.current) setDraft(message);
        return;
      }
      const turn = await sendCanvasChat(taskId, message, chatContext(canvasId, attached));
      answer({ text: turn.reply || t('（助手没有回话）'), turn });
      if (turn.canvas && turn.canvas.canvasId === canvasId) onCanvasChanged(turn.canvas.version, turn.canvas.nodeIds);
    } catch (error) {
      answer({ text: messageOf(error), problem: true });
      if (fromDraft && alive.current) setDraft(message);
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  return (
    <section className="cn-panel cn-chat" aria-label={t('画布助手')} hidden={hidden}>
      <div ref={log} className="cn-chat__log" role="log" aria-live="polite" aria-label={t('对话')}>
        {!messages.length && (
          <p className="cn-hint">
            {t('这里和项目侧栏的助手是同一个对话。选中节点再说话，它就知道「这个节点」指谁；它改了画布，这里会马上跟上。付费操作它会先问你。')}
          </p>
        )}
        {messages.map(message => (
          <article key={message.id} className={`cn-chat__bubble is-${message.from}${message.problem ? ' is-problem' : ''}`}>
            {message.attached && message.attached.length > 0 && (
              <small className="cn-chat__attached">{t('带上了：{0}', [message.attached.join('、')])}</small>
            )}
            <p>{message.text}</p>
            {message.turn && message.turn.calls.length > 0 && (
              <small className="cn-chat__calls">
                {t('用了：{0}', [message.turn.calls.map(call => (call.ok ? call.tool : `${call.tool} ✕`)).join('、')])}
              </small>
            )}
            {message.turn?.canvas && message.turn.canvas.nodeIds.length > 0 && (
              <button type="button" className="cn-button is-quiet cn-chat__jump" onClick={() => onJump(message.turn!.canvas!.nodeIds[0])}>
                {t('看它改的 {0} 个节点', [message.turn.canvas.nodeIds.length])}
              </button>
            )}
            {message.turn?.proposal && (
              <div className="cn-chat__proposal" role="group" aria-label={t('等您确认')}>
                <strong>{t('等您确认')}</strong>
                <span>{message.turn.proposal.message}</span>
                {message.id === lastId && (
                  <div className="cn-row">
                    <button type="button" className="cn-button is-primary" disabled={busy} onClick={() => { void send('/confirm'); }}><Check aria-hidden="true" /> {t('确认执行')}</button>
                    <button type="button" className="cn-button" disabled={busy} onClick={() => { void send('/cancel'); }}><X aria-hidden="true" /> {t('放弃')}</button>
                  </div>
                )}
              </div>
            )}
          </article>
        ))}
        {busy && <p className="cn-chat__waiting" role="status"><Loader2 className="cn-spin" aria-hidden="true" /> {t('助手在想…')}</p>}
      </div>

      <div className="cn-chat__context">
        <label className="cn-chat__attach">
          <input type="checkbox" checked={attach} onChange={event => setAttach(event.target.checked)} />
          <span>{t('带上选中的节点')}</span>
        </label>
        {attach && (selected.length > 0 ? (
          <ul className="cn-chat__chips" aria-label={t('随消息带上的节点')}>
            {selected.slice(0, 6).map(node => (
              <li key={node.id} title={kindLabel(node.kind)}><Bot aria-hidden="true" />{nodeTitle(node)}</li>
            ))}
            {selected.length > 6 && <li>{t('等 {0} 个', [selected.length])}</li>}
          </ul>
        ) : <small className="cn-hint">{t('现在没有选中节点。')}</small>)}
      </div>

      <form
        className="cn-chat__form"
        onSubmit={event => {
          event.preventDefault();
          void send(draft);
        }}
      >
        <textarea
          className="cn-chat__input" aria-label={t('对助手说')} placeholder={t('例如：把这张图换成夜景，再接一个 5 秒的视频节点')}
          value={draft} maxLength={4000} rows={3}
          onChange={event => setDraft(event.target.value)}
          onKeyDown={event => {
            // Enter sends; Shift + Enter is a new line; an Enter that only confirms an input-method candidate does neither.
            if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return;
            event.preventDefault();
            void send(draft);
          }}
        />
        <button type="submit" className="cn-button is-primary" disabled={busy || !draft.trim()} aria-label={t('发给助手')} title={t('发给助手')}>
          {busy ? <Loader2 className="cn-spin" aria-hidden="true" /> : <Send aria-hidden="true" />}
        </button>
      </form>
    </section>
  );
}
