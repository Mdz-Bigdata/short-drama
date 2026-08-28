import { Box, Landmark, Shirt, Sparkles, UsersRound, type LucideIcon } from 'lucide-react';
import type { KeyboardEvent } from 'react';

import type { ElementKind } from '../elements/elementTypes';
import { characterAssetTabLabels } from './assetTabLabels';


interface AssetTabDefinition {
  kind: ElementKind;
  label: string;
  icon: LucideIcon;
}

const characterAssetTabs: AssetTabDefinition[] = [
  { kind: 'actor', label: characterAssetTabLabels.actor, icon: UsersRound },
  { kind: 'scene', label: characterAssetTabLabels.scene, icon: Landmark },
  { kind: 'prop', label: characterAssetTabLabels.prop, icon: Box },
  { kind: 'costume', label: characterAssetTabLabels.costume, icon: Shirt },
  { kind: 'effect', label: characterAssetTabLabels.effect, icon: Sparkles },
];

export function CharacterAssetTabs({
  activeKind,
  counts,
  onSelect,
}: {
  activeKind: ElementKind;
  counts: Partial<Record<ElementKind, number>>;
  onSelect: (kind: ElementKind) => void;
}) {
  const moveFocus = (event: KeyboardEvent<HTMLButtonElement>, currentKind: ElementKind) => {
    const currentIndex = characterAssetTabs.findIndex(item => item.kind === currentKind);
    let nextIndex: number;
    if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % characterAssetTabs.length;
    else if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + characterAssetTabs.length) % characterAssetTabs.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = characterAssetTabs.length - 1;
    else return;
    event.preventDefault();
    const next = characterAssetTabs[nextIndex];
    onSelect(next.kind);
    const tabs = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    tabs?.[nextIndex]?.focus();
  };

  return (
    <nav className="character-asset-tabs" role="tablist" aria-label="角色资产类型">
      {characterAssetTabs.map(({ kind, label, icon: Icon }) => {
        const selected = kind === activeKind;
        const count = counts[kind];
        return (
          <button
            key={kind}
            id={`character-asset-tab-${kind}`}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={`character-asset-panel-${kind}`}
            tabIndex={selected ? 0 : -1}
            className={selected ? 'is-active' : ''}
            onClick={() => onSelect(kind)}
            onKeyDown={event => moveFocus(event, kind)}
          >
            <Icon size={17} aria-hidden="true" />
            <span>{label}</span>
            <small aria-label={typeof count === 'number' ? `${count} 个资产` : '尚未同步'}>
              {typeof count === 'number' ? String(count).padStart(2, '0') : '--'}
            </small>
          </button>
        );
      })}
    </nav>
  );
}
