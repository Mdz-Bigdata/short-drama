// Adapted from open-ai-canvas (MIT, © 2026 ddcat and Open AI Canvas contributors), web/src/lib/canvas/tool-registry/definitions/selection-toolbar-tools.tsx.
import {
  AlignHorizontalJustifyCenter, AlignHorizontalJustifyEnd, AlignHorizontalJustifyStart, AlignHorizontalSpaceBetween,
  AlignVerticalJustifyCenter, AlignVerticalJustifyEnd, AlignVerticalJustifyStart, AlignVerticalSpaceBetween,
  Columns3, Copy, Expand, Grid3x3, Group, Rows3, Trash2, Ungroup, Workflow, type LucideIcon,
} from 'lucide-react';
import type { CSSProperties } from 'react';

import { t } from '../../i18n';
import type { AlignKind, ArrangeKind, DistributeAxis } from './canvasLayout';
import type { Rect } from './canvasTypes';
import './CanvasSelectionToolbar.css';

export interface CanvasSelectionToolbarProps {
  /** The selection's bounding box in screen coordinates (relative to the toolbar's positioned parent). */
  rect: Rect;
  count: number;
  onAlign: (kind: AlignKind) => void;
  onDistribute: (axis: DistributeAxis) => void;
  onArrange: (kind: ArrangeKind) => void;
  onGroup: () => void;
  /** Shown only when given: the selection holds a group. */
  onUngroup?: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
}

/** Room the toolbar needs above the selection; with less it sits below instead. */
export const TOOLBAR_CLEARANCE = 56;
const OFFSET = 10;

interface Tool {
  id: string;
  label: string;
  icon: LucideIcon;
  run: () => void;
  disabled?: boolean;
  danger?: boolean;
}

function ToolButton({ tool }: { tool: Tool }) {
  const Icon = tool.icon;
  return (
    <button
      type="button"
      className={`cst-button${tool.danger ? ' is-danger' : ''}`}
      aria-label={tool.label}
      data-tip={tool.label}
      data-tool={tool.id}
      disabled={tool.disabled}
      onClick={tool.run}
    >
      <Icon size={15} aria-hidden="true" />
    </button>
  );
}

/** Floating actions over a multi-selection: align, distribute, arrange, group, duplicate, delete. */
export function CanvasSelectionToolbar({ rect, count, onAlign, onDistribute, onArrange, onGroup, onUngroup, onDuplicate, onDelete }: CanvasSelectionToolbarProps) {
  const below = rect.y < TOOLBAR_CLEARANCE;
  const style: CSSProperties = {
    left: rect.x + rect.width / 2,
    top: below ? rect.y + rect.height + OFFSET : rect.y - OFFSET,
  };
  const few = count < 2;
  const sections: Tool[][] = [
    [
      { id: 'align-left', label: t('左对齐'), icon: AlignHorizontalJustifyStart, run: () => onAlign('left'), disabled: few },
      { id: 'align-hcenter', label: t('水平居中'), icon: AlignHorizontalJustifyCenter, run: () => onAlign('hcenter'), disabled: few },
      { id: 'align-right', label: t('右对齐'), icon: AlignHorizontalJustifyEnd, run: () => onAlign('right'), disabled: few },
      { id: 'align-top', label: t('顶对齐'), icon: AlignVerticalJustifyStart, run: () => onAlign('top'), disabled: few },
      { id: 'align-vcenter', label: t('垂直居中'), icon: AlignVerticalJustifyCenter, run: () => onAlign('vcenter'), disabled: few },
      { id: 'align-bottom', label: t('底对齐'), icon: AlignVerticalJustifyEnd, run: () => onAlign('bottom'), disabled: few },
    ],
    [
      { id: 'distribute-horizontal', label: t('水平等距'), icon: AlignHorizontalSpaceBetween, run: () => onDistribute('horizontal'), disabled: count < 3 },
      { id: 'distribute-vertical', label: t('垂直等距'), icon: AlignVerticalSpaceBetween, run: () => onDistribute('vertical'), disabled: count < 3 },
    ],
    [
      { id: 'arrange-row', label: t('横向排列'), icon: Columns3, run: () => onArrange('row'), disabled: few },
      { id: 'arrange-column', label: t('纵向排列'), icon: Rows3, run: () => onArrange('column'), disabled: few },
      { id: 'arrange-grid', label: t('宫格排列'), icon: Grid3x3, run: () => onArrange('grid'), disabled: few },
      { id: 'arrange-edges', label: t('按连线整理'), icon: Workflow, run: () => onArrange('edges'), disabled: few },
      { id: 'arrange-spread', label: t('散开重叠'), icon: Expand, run: () => onArrange('spread'), disabled: few },
    ],
    [
      { id: 'group', label: t('成组'), icon: Group, run: onGroup, disabled: few },
      ...(onUngroup ? [{ id: 'ungroup', label: t('解组'), icon: Ungroup, run: onUngroup }] : []),
      { id: 'duplicate', label: t('就地复制'), icon: Copy, run: onDuplicate },
      { id: 'delete', label: t('删除所选'), icon: Trash2, run: onDelete, danger: true },
    ],
  ];
  return (
    <div
      className={`cst-toolbar${below ? ' is-below' : ''}`}
      role="toolbar"
      aria-label={t('选区工具栏')}
      style={style}
      // The canvas below must not read a press here as the start of a marquee or a deselect.
      onPointerDown={event => event.stopPropagation()}
      onDoubleClick={event => event.stopPropagation()}
      onContextMenu={event => event.preventDefault()}
    >
      <span className="cst-count">{t('已选 {0} 个', [count])}</span>
      {sections.map((tools, index) => (
        <div className="cst-section" key={index}>
          {tools.map(tool => <ToolButton key={tool.id} tool={tool} />)}
        </div>
      ))}
    </div>
  );
}
