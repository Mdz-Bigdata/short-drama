import { Clock3 } from 'lucide-react';

import type { WriterScene, WriterTimelineEvent } from './types';

const ROW_SIZE = 10;

function compact(value?: string, limit = 16) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function chunks<T>(items: T[], size: number) {
  return Array.from({ length: Math.ceil(items.length / size) }, (_, index) => items.slice(index * size, (index + 1) * size));
}

export function WriterTimeline({
  mode,
  scenes,
  timeline,
}: {
  mode: 'axis' | 'line';
  scenes: WriterScene[];
  timeline: WriterTimelineEvent[];
}) {
  if (mode === 'line') {
    const events: WriterTimelineEvent[] = timeline.length > 0
      ? timeline
      : scenes.map((scene, index) => ({ phase: scene.scene_id || `场景 ${index + 1}`, title: compact(scene.content, 22), desc: scene.duration }));

    if (events.length === 0) return <div className="writer-empty">剧本结构化完成后，关键事件时间线将在这里生成。</div>;

    return (
      <ol className="writer-event-line" aria-label="剧情关键事件时间线">
        {events.map((event, index) => (
          <li key={`${event.phase}-${event.title}-${index}`}>
            <div className="writer-event-line__rail"><span>{String(index + 1).padStart(2, '0')}</span></div>
            <article>
              <div><span>{event.phase || '剧情节点'}</span><time>节点 {index + 1}</time></div>
              <h3>{event.title || `事件 ${index + 1}`}</h3>
              {event.desc && <p>{event.desc}</p>}
              {Array.isArray(event.points) && event.points.length > 0 && (
                <ul>{event.points.map((point, pointIndex) => <li key={`${point}-${pointIndex}`}>{point}</li>)}</ul>
              )}
            </article>
          </li>
        ))}
      </ol>
    );
  }

  const source = scenes.length > 0
    ? scenes
    : timeline.map((event, index) => ({ scene_id: String(index + 1), content: event.title, duration: event.phase }));

  if (source.length === 0) return <div className="writer-empty">剧本结构化完成后，场景节奏轴将在这里生成。</div>;

  const beats = source.map((scene, index) => {
    const phaseIndex = timeline.length > 0 ? Math.min(Math.floor(index * timeline.length / source.length), timeline.length - 1) : -1;
    const previousPhaseIndex = timeline.length > 0 && index > 0 ? Math.min(Math.floor((index - 1) * timeline.length / source.length), timeline.length - 1) : -2;
    const event = phaseIndex >= 0 ? timeline[phaseIndex] : undefined;
    return {
      scene,
      index,
      event,
      major: index === 0 || phaseIndex !== previousPhaseIndex,
    };
  });

  return (
    <div className="writer-axis" aria-label="按场景展开的剧本节奏时间轴">
      <div className="writer-axis__legend"><span><i />关键节点</span><span><i />常规场景</span></div>
      <div className="writer-axis__viewport">
        {chunks(beats, ROW_SIZE).map((row, rowIndex) => (
          <div className="writer-axis__row" key={`row-${rowIndex}`} style={{ '--axis-columns': row.length } as React.CSSProperties}>
            {row.map(({ scene, index, event, major }) => (
              <article className={`writer-axis__beat ${major ? 'is-major' : ''} ${index % 2 === 0 ? 'is-top' : 'is-bottom'}`} key={`${scene.scene_id}-${index}`}>
                <div className="writer-axis__content">
                  <span>{major ? event?.phase || '关键节点' : scene.duration || '场景'}</span>
                  <strong>{major ? event?.title || compact(scene.content) : compact(scene.content)}</strong>
                  <small>{scene.scene_id || `S${index + 1}`}</small>
                </div>
                <span className="writer-axis__marker" aria-hidden="true" />
                <span className="writer-axis__number">{index + 1}</span>
              </article>
            ))}
          </div>
        ))}
      </div>
      <p className="writer-axis__hint"><Clock3 aria-hidden="true" /> 场景按剧本顺序排列，深色大节点代表主线节拍切换。</p>
    </div>
  );
}
