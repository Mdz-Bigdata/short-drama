import { useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';
import { ArrowRight, Command, Send } from 'lucide-react';
import { filterChatCommands, type ChatCommand } from './chatCommands';
import { NOVARA_AGENT_NAME } from './agentBrand';
import './ChatComposer.css';
import { t } from '../../i18n';

interface ChatComposerProps {
  value: string;
  busy: boolean;
  onChange: (value: string) => void;
  onSend: (message: string) => void;
}

export function ChatComposer({ value, busy, onChange, onSend }: ChatComposerProps) {
  const menuId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [focused, setFocused] = useState(false);
  const [dismissedValue, setDismissedValue] = useState<string | null>(null);
  const [activeIndex, setActiveIndex] = useState(-1);
  const slash = value.trimStart().startsWith('/');
  const commands = filterChatCommands(value);
  const open = slash && focused && dismissedValue !== value;
  const selected = open && activeIndex >= 0 ? commands[activeIndex] : undefined;
  const exact = slash ? commands.find(item => item.command === value.trim().toLowerCase()) : undefined;

  // Scroll only the command list; never move the chat viewport or page.
  useLayoutEffect(() => {
    const list = listRef.current;
    const option = list?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (!list || !option) return;
    const top = option.offsetTop;
    if (top < list.scrollTop) list.scrollTop = top;
    else if (top + option.offsetHeight > list.scrollTop + list.clientHeight) {
      list.scrollTop = top + option.offsetHeight - list.clientHeight;
    }
  }, [activeIndex, open]);

  const executeCommand = (item: ChatCommand) => {
    if (busy) return;
    setDismissedValue(value);
    setActiveIndex(-1);
    onSend(item.command);
    inputRef.current?.focus();
  };

  const submit = () => {
    if (busy || !value.trim()) return;
    if (slash) {
      const target = selected ?? exact ?? (commands.length === 1 ? commands[0] : undefined);
      if (target) executeCommand(target);
      else { setDismissedValue(null); inputRef.current?.focus(); }
      return;
    }
    onSend(value);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.nativeEvent.isComposing) return;
    if (open && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      event.preventDefault();
      if (commands.length) setActiveIndex(index => event.key === 'ArrowDown'
        ? (index + 1) % commands.length
        : (index <= 0 ? commands.length - 1 : index - 1));
    } else if (event.key === 'Escape' && open) {
      event.preventDefault();
      setDismissedValue(value);
      setActiveIndex(-1);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      // Escape dismisses the menu without turning a bare slash into a command.
      if (slash && !open && !exact) return;
      submit();
    }
  };

  return (
    <div className="chat-composer">
      {open && (
        <div className="chat-command-menu">
          <div className="chat-command-menu__heading"><Command size={15} aria-hidden="true" /><span>{t('快捷命令')}</span><small>{t('↑↓ 选择 · Enter 执行')}</small></div>
          <div id={menuId} ref={listRef} role="listbox" aria-label={t('快捷命令')} className="chat-command-menu__list">
            {commands.map((item, index) => (
              <button id={`${menuId}-${index}`} key={item.command} type="button" role="option" tabIndex={-1}
                aria-selected={activeIndex === index} disabled={busy} className="chat-command-option"
                onMouseDown={event => event.preventDefault()} onMouseEnter={() => setActiveIndex(index)}
                onClick={() => executeCommand(item)}>
                <span className="chat-command-option__copy"><strong>{t(item.label)}</strong><small>{t(item.description)}</small></span>
                <code>{item.command}</code><ArrowRight size={13} aria-hidden="true" />
              </button>
            ))}
            {commands.length === 0 && <p className="chat-command-menu__empty">{t('没有匹配的命令。输入 / 查看全部命令。')}</p>}
          </div>
          <div className="chat-command-menu__footnote">{busy ? t('正在发送上一条指令，请稍候…') : t('点击或按 Enter 执行，Esc 收起')}</div>
        </div>
      )}
      <div className="chat-composer__row">
        <input ref={inputRef} type="text" role={slash ? 'combobox' : undefined}
          placeholder={t('输入 / 查看命令，或直接说出需求…')}
          aria-label={`发送给 ${NOVARA_AGENT_NAME} 的消息`} aria-expanded={slash ? open : undefined}
          aria-controls={open ? menuId : undefined} aria-autocomplete={slash ? 'list' : undefined}
          aria-activedescendant={selected ? `${menuId}-${activeIndex}` : undefined}
          value={value} onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
          onChange={event => { setActiveIndex(-1); setDismissedValue(null); onChange(event.target.value); }}
          onKeyDown={onKeyDown} />
        <button type="button" onMouseDown={event => event.preventDefault()} onClick={submit} className="cyber-btn chat-composer__send" aria-label={t('发送消息')}
          disabled={busy || !value.trim() || (slash && !selected && !exact && commands.length !== 1)}>
          <Send size={16} aria-hidden="true" />
        </button>
      </div>
      <small className="chat-composer__hint">{t('/ 快捷命令 · Enter 发送')}</small>
    </div>
  );
}
