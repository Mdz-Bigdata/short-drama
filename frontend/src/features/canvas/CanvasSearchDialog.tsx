// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/lib/canvas/canvas-node-search.ts.
import { useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import {
  AudioLines, Boxes, Clapperboard, Film, Globe2, ImageIcon, Layers, Package, Palette, Search, Sparkles, StickyNote, Upload, Waypoints, Wrench, type LucideIcon,
} from 'lucide-react';

import { t } from '../../i18n';
import { kindLabel } from './canvasLabels';
import { searchNodes, type SearchField, type SearchHit } from './canvasSearch';
import type { CanvasNode, NodeKind } from './canvasTypes';
import './CanvasSearchDialog.css';

const ICONS: Record<NodeKind, LucideIcon> = {
  artifact: Package, candidate: Sparkles, media: Upload, note: StickyNote, group: Boxes, image_gen: ImageIcon, video_gen: Film, audio_gen: AudioLines,
  video_compose: Clapperboard, style_ref: Palette, panorama: Globe2, previz: Waypoints, tool: Wrench,
};

function fieldLabel(field: SearchField) {
  switch (field) {
    case 'title': return t('标题');
    case 'prompt': return t('提示词');
    case 'text': return t('文本');
    case 'styleText': return t('风格描述');
    case 'output': return t('结果文本');
    case 'filename': return t('文件名');
  }
}

export interface CanvasSearchDialogProps {
  open: boolean;
  nodes: readonly CanvasNode[];
  /** Called with the chosen node; the dialog closes itself right after. */
  onJump: (id: string) => void;
  onClose: () => void;
}

/** ⌘F: find a node by its name or text and jump to it. */
export function CanvasSearchDialog({ open, nodes, onJump, onClose }: CanvasSearchDialogProps) {
  // Mounted only while open, so every opening starts from an empty query.
  if (!open) return null;
  return <SearchBody nodes={nodes} onJump={onJump} onClose={onClose} />;
}

function SearchBody({ nodes, onJump, onClose }: Omit<CanvasSearchDialogProps, 'open'>) {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const hits = useMemo(() => searchNodes(nodes, query), [nodes, query]);
  const list = useRef<HTMLUListElement>(null);
  const baseId = useId();
  const listId = `${baseId}-results`;
  const optionId = (index: number) => `${baseId}-option-${index}`;
  const current = hits.length ? Math.min(active, hits.length - 1) : -1;

  const choose = (hit: SearchHit | undefined) => {
    if (!hit) return;
    onJump(hit.id);
    onClose();
  };

  const move = (index: number) => {
    setActive(index);
    const option = list.current?.children[index];
    if (option instanceof HTMLElement) option.scrollIntoView?.({ block: 'nearest' });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      onClose();
    } else if (event.key === 'ArrowDown' && hits.length) {
      event.preventDefault();
      move((current + 1) % hits.length);
    } else if (event.key === 'ArrowUp' && hits.length) {
      event.preventDefault();
      move((current - 1 + hits.length) % hits.length);
    } else if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
      event.preventDefault();
      choose(hits[current]);
    }
  };

  return (
    <div className="csd-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="csd-dialog" role="dialog" aria-modal="true" aria-label={t('搜索节点')}>
        <div className="csd-field">
          <Search aria-hidden="true" />
          <input
            autoFocus
            type="text"
            role="combobox"
            aria-expanded={hits.length > 0}
            aria-controls={listId}
            aria-activedescendant={current >= 0 ? optionId(current) : undefined}
            aria-label={t('搜索节点')}
            placeholder={t('按名称、提示词或文本搜索节点')}
            value={query}
            onChange={event => {
              setQuery(event.target.value);
              setActive(0);
            }}
            onKeyDown={onKeyDown}
          />
        </div>
        {query.trim() && (
          <div className="csd-count" aria-live="polite">{hits.length ? t('{0} 个结果', [hits.length]) : t('没有匹配的节点')}</div>
        )}
        <ul className="csd-results" id={listId} role="listbox" ref={list} aria-label={t('搜索结果')}>
          {hits.map((hit, index) => {
            const Icon = ICONS[hit.kind] ?? Layers;
            const { text, start, end } = hit.snippet;
            return (
              <li
                key={hit.id}
                id={optionId(index)}
                role="option"
                aria-selected={index === current}
                className={`csd-result${index === current ? ' is-active' : ''}`}
                onMouseEnter={() => setActive(index)}
                onMouseDown={event => event.preventDefault()}
                onClick={() => choose(hit)}
              >
                <span className="csd-kind" title={kindLabel(hit.kind)}><Icon aria-hidden="true" /><span>{kindLabel(hit.kind)}</span></span>
                <span className="csd-main">
                  <span className="csd-title">{hit.title}</span>
                  <span className="csd-snippet">
                    {hit.field !== 'title' && <span className="csd-field-name">{fieldLabel(hit.field)}</span>}
                    {text.slice(0, start)}<mark>{text.slice(start, end)}</mark>{text.slice(end)}
                  </span>
                </span>
              </li>
            );
          })}
        </ul>
        <div className="csd-hint">{t('↑↓ 选择 · Enter 跳转 · Esc 关闭')}</div>
      </div>
    </div>
  );
}
