import { useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';

import { moveBlock, trimBlock, type Block } from '../lib/timelineClips';

export interface LaneBlock extends Block {
  label: string;
}

type Grip = 'move' | 'start' | 'end';

interface Props {
  blocks: LaneBlock[];
  tone: 'action' | 'follow' | 'cut';
  /** Names the lane to assistive tech: 「林晚」动作, 跟拍. */
  label: string;
  pickedId: string;
  durationS: number;
  fps: number;
  time: number;
  disabled: boolean;
  onPick: (id: string) => void;
  /** Called once, when a drag is let go. */
  onChange: (blocks: LaneBlock[]) => void;
  onScrub: (event: ReactPointerEvent<HTMLElement>) => void;
}

/** One block track: slide a block by its body, trim it by either end. A drag draws locally and is written when let go. */
export function ClipLane({ blocks, tone, label, pickedId, durationS, fps, time, disabled, onPick, onChange, onScrub }: Props) {
  const [dragged, setDragged] = useState<LaneBlock[] | null>(null);
  const held = useRef<{ id: string; grip: Grip; lane: HTMLElement; startX: number; start: number; moved: boolean } | null>(null);
  const shown = dragged ?? blocks;
  const percent = (value: number) => `${(Math.min(value, durationS) / durationS) * 100}%`;

  const grab = (block: LaneBlock, grip: Grip) => (event: ReactPointerEvent<HTMLElement>) => {
    event.stopPropagation();
    onPick(block.id);
    const lane = event.currentTarget.closest<HTMLElement>('.desk-timeline__lane');
    if (!lane || disabled) return;
    held.current = { id: block.id, grip, lane, startX: event.clientX, start: block.start, moved: false };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const drag = (event: ReactPointerEvent<HTMLElement>) => {
    const grabbed = held.current;
    if (!grabbed) return;
    if (!grabbed.moved && Math.abs(event.clientX - grabbed.startX) < 3) return;
    grabbed.moved = true;
    const box = grabbed.lane.getBoundingClientRect();
    if (box.width <= 0) return;
    const at = (Math.min(1, Math.max(0, (event.clientX - box.left) / box.width))) * durationS;
    setDragged(grabbed.grip === 'move'
      ? moveBlock(blocks, grabbed.id, grabbed.start + ((event.clientX - grabbed.startX) / box.width) * durationS, fps, durationS)
      : trimBlock(blocks, grabbed.id, grabbed.grip, at, fps, durationS));
  };

  const drop = () => {
    const moved = held.current?.moved;
    held.current = null;
    if (moved && dragged) onChange(dragged);
    setDragged(null);
  };

  return (
    <div className="desk-timeline__lane is-blocks" aria-label={`${label}轨`} onPointerDown={onScrub} onPointerMove={event => { if (!held.current) onScrub(event); }}>
      {shown.map(block => (
        <div
          key={block.id} className={`desk-timeline__block is-${tone} ${block.id === pickedId ? 'is-picked' : ''}`}
          style={{ left: percent(block.start), width: `${((Math.min(block.end, durationS) - block.start) / durationS) * 100}%` }}
          role="button" tabIndex={0} aria-label={`${label}片段 ${block.label} ${block.start.toFixed(2)} 到 ${block.end.toFixed(2)} 秒`} aria-pressed={block.id === pickedId}
          onPointerDown={grab(block, 'move')} onPointerMove={drag} onPointerUp={drop} onPointerCancel={drop}
          onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onPick(block.id); } }}
        >
          <i className="desk-timeline__grip is-start" aria-hidden="true" onPointerDown={grab(block, 'start')} onPointerMove={drag} onPointerUp={drop} onPointerCancel={drop} />
          <span>{block.label}</span>
          <i className="desk-timeline__grip is-end" aria-hidden="true" onPointerDown={grab(block, 'end')} onPointerMove={drag} onPointerUp={drop} onPointerCancel={drop} />
        </div>
      ))}
      <b className="desk-timeline__playhead" style={{ left: percent(time) }} />
    </div>
  );
}
