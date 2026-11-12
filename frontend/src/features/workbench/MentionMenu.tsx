import { useLayoutEffect, useRef } from 'react';

import { apiUrl } from '../../api/client';
import { t } from '../../i18n';
import type { MentionCandidate } from './mentionAutocomplete';
import { MENTION_KIND_LABELS, mentionKindClass } from './promptMentions';
import './MentionMenu.css';

export interface MentionMenuProps {
  id: string;
  open: boolean;
  items: MentionCandidate[];
  activeIndex: number;
  optionId: (index: number) => string;
  onPick: (candidate: MentionCandidate) => void;
  onHover: (index: number) => void;
  /** 默认在输入框下方；贴着页面底部的输入框(聊天框)用 above。 */
  placement?: 'below' | 'above';
  className?: string;
}

function mentionKindLabel(kind: string): string {
  const label = MENTION_KIND_LABELS[kind];
  return label ? t(label) : t('其他资产');
}

/**
 * 「@」补全菜单：缩略图(没有就按类型着色的圆点)、名字、类型。
 * 放在输入框外层一个 position: relative 的容器里；键盘由 useMentionInput 处理，焦点始终留在输入框。
 */
export function MentionMenu({ id, open, items, activeIndex, optionId, onPick, onHover, placement = 'below', className }: MentionMenuProps) {
  const listRef = useRef<HTMLUListElement>(null);

  // 只滚菜单自己，别带着页面或聊天记录一起滚。
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

  if (!open) return null;
  return (
    <div className={`mention-menu is-${placement}${className ? ` ${className}` : ''}`}>
      <ul ref={listRef} id={id} role="listbox" aria-label={t('引用人物、场景或道具')} className="mention-menu__list">
        {items.map((item, index) => (
          <li
            key={`${item.kind}:${item.name}`}
            id={optionId(index)}
            role="option"
            aria-selected={index === activeIndex}
            title={item.description || undefined}
            className="mention-menu__option"
            onMouseDown={event => event.preventDefault()}
            onMouseEnter={() => onHover(index)}
            onClick={() => onPick(item)}
          >
            {item.thumbUrl
              ? <img className="mention-menu__thumb" src={apiUrl(item.thumbUrl)} alt="" loading="lazy" />
              : <span className={`mention-menu__dot ${mentionKindClass(item.kind)}`} aria-hidden="true" />}
            <span className="mention-menu__name">{item.name}</span>
            <small className="mention-menu__kind">{mentionKindLabel(item.kind)}</small>
          </li>
        ))}
        {items.length === 0 && <li className="mention-menu__empty" role="presentation">{t('没有匹配的人物、场景或道具')}</li>}
      </ul>
      <div className="mention-menu__footnote">{t('↑↓ 选择 · Enter 插入 · Esc 收起')}</div>
    </div>
  );
}
