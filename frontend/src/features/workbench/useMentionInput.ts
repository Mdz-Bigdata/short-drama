import {
  useCallback, useId, useLayoutEffect, useMemo, useRef, useState,
  type KeyboardEvent, type RefObject, type SyntheticEvent,
} from 'react';

import {
  activeMentionQuery, insertMention, rankMentionCandidates,
  type MentionCandidate,
} from './mentionAutocomplete';
import type { MentionMenuProps } from './MentionMenu';

type Field = HTMLInputElement | HTMLTextAreaElement;

export interface UseMentionInputOptions<E extends Field> {
  value: string;
  onChange: (value: string) => void;
  candidates: MentionCandidate[];
  inputRef: RefObject<E | null>;
  /** 菜单里最多列几项，默认 8。 */
  limit?: number;
  disabled?: boolean;
}

/** 铺到输入框上的属性：可访问性标注 + 跟踪光标和焦点的事件。宿主已有的 onFocus/onBlur 要自己串起来。 */
export interface MentionInputProps {
  role?: 'combobox';
  'aria-expanded'?: boolean;
  'aria-controls'?: string;
  'aria-autocomplete'?: 'list';
  'aria-activedescendant'?: string;
  onInput: (event: SyntheticEvent<Field>) => void;
  onSelect: (event: SyntheticEvent<Field>) => void;
  onClick: (event: SyntheticEvent<Field>) => void;
  onKeyUp: (event: SyntheticEvent<Field>) => void;
  onFocus: (event: SyntheticEvent<Field>) => void;
  onBlur: () => void;
}

export interface MentionInputState {
  open: boolean;
  items: MentionCandidate[];
  activeIndex: number;
  inputProps: MentionInputProps;
  menuProps: MentionMenuProps;
  /** 在宿主的 onKeyDown 最前面调；返回 true 表示这个键菜单用掉了，宿主别再处理(比如别把 Enter 当发送)。 */
  onKeyDown: (event: KeyboardEvent<Field>) => boolean;
  select: (candidate: MentionCandidate) => void;
  close: () => void;
}

/**
 * 「@」补全的状态机：光标前是 @名字 就开菜单，↑↓ 选、Enter/Tab 插入、Esc 收起、鼠标点选；
 * 输入法正在选字时不抢键。选中后写成 @[名字]，光标落在后面。
 */
export function useMentionInput<E extends Field>({
  value, onChange, candidates, inputRef, limit = 8, disabled = false,
}: UseMentionInputOptions<E>): MentionInputState {
  const listboxId = useId();
  const [caret, setCaret] = useState<number | null>(null);
  const [focused, setFocused] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [dismissedValue, setDismissedValue] = useState<string | null>(null);
  const pendingCaret = useRef<number | null>(null);

  const enabled = !disabled && candidates.length > 0;
  const query = useMemo(
    () => (enabled && focused && caret !== null ? activeMentionQuery(value, caret) : null),
    [enabled, focused, caret, value],
  );
  const items = useMemo(
    () => (query ? rankMentionCandidates(candidates, query.query, limit) : []),
    [candidates, query, limit],
  );
  const open = query !== null && dismissedValue !== value;
  const active = open && items.length ? Math.min(activeIndex, items.length - 1) : -1;
  const optionId = useCallback((index: number) => `${listboxId}-option-${index}`, [listboxId]);

  // 插入之后把光标放回 @[名字] 后面(值由宿主改，等它渲染完再放)。
  useLayoutEffect(() => {
    const target = pendingCaret.current;
    const field = inputRef.current;
    if (target === null || !field) return;
    pendingCaret.current = null;
    field.focus();
    field.setSelectionRange(target, target);
  }, [value, inputRef]);

  const track = (event: SyntheticEvent<Field>) => {
    const field = event.currentTarget;
    setCaret(field.selectionStart ?? field.value.length);
  };

  const close = () => {
    setDismissedValue(value);
    setActiveIndex(0);
  };

  const select = (candidate: MentionCandidate) => {
    if (!query) return;
    const next = insertMention(value, query, candidate.name);
    pendingCaret.current = next.caret;
    setCaret(next.caret);
    setActiveIndex(0);
    setDismissedValue(null);
    onChange(next.text);
  };

  const onKeyDown = (event: KeyboardEvent<Field>): boolean => {
    if (!open) return false;
    // 输入法选字时的方向键和回车属于输入法；也别让宿主把它当发送。
    if (event.nativeEvent.isComposing || event.keyCode === 229) return true;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (items.length) {
        const current = Math.max(active, 0);
        setActiveIndex(event.key === 'ArrowDown'
          ? (current + 1) % items.length
          : (current <= 0 ? items.length - 1 : current - 1));
      }
      return true;
    }
    if (event.key === 'Enter' || event.key === 'Tab') {
      if (!items.length || event.shiftKey) return false;
      event.preventDefault();
      select(items[Math.max(active, 0)]);
      return true;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
      return true;
    }
    return false;
  };

  const inputProps: MentionInputProps = {
    ...(enabled ? {
      role: 'combobox' as const,
      'aria-expanded': open,
      'aria-controls': open ? listboxId : undefined,
      'aria-autocomplete': 'list' as const,
      'aria-activedescendant': active >= 0 ? optionId(active) : undefined,
    } : {}),
    onInput: event => { track(event); setActiveIndex(0); setDismissedValue(null); },
    onSelect: track,
    onClick: track,
    onKeyUp: track,
    onFocus: event => { setFocused(true); track(event); },
    onBlur: () => setFocused(false),
  };

  const menuProps: MentionMenuProps = {
    id: listboxId,
    open,
    items,
    activeIndex: active,
    optionId,
    onPick: select,
    onHover: setActiveIndex,
  };

  return { open, items, activeIndex: active, inputProps, menuProps, onKeyDown, select, close };
}
