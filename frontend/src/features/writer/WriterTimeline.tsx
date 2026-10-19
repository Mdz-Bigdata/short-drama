import { Clock3 } from 'lucide-react';

import { stripMarkdown, summarizeSceneEvent } from './textSummary';
import type { WriterScene, WriterTimelineEvent } from './types';
import { t } from '../../i18n';

const ROW_SIZE = 10;

/** Timeline titles may be short LLM labels or whole raw scene bodies. */
function eventTitle(value: unknown, limit = 26) {
  const plain = stripMarkdown(value);
  if (!plain) return '';
  return plain.length <= limit ? plain : summarizeSceneEvent(plain, limit);
}

function chunks<T>(items: T[], size: number) {
  return Array.from({ length: Math.ceil(items.length / size) }, (_, index) => items.slice(index * size, (index + 1) * size));
}

/** The story's beats laid along the scenes in script order: a dark major node where a story event begins, small nodes between. */
export function WriterTimeline({
  scenes,
  timeline,
}: {
  scenes: WriterScene[];
  timeline: WriterTimelineEvent[];
}) {
  const source = scenes.length > 0
    ? scenes
    : timeline.map((event, index) => ({ scene_id: String(index + 1), content: event.title, duration: event.phase }));

  if (source.length === 0) return <div className="writer-empty">{t('剧本结构化完成后，场景节奏轴将在这里生成。')}</div>;

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
    <div className="writer-axis" aria-label={t('按场景展开的剧本节奏时间轴')}>
      <div className="writer-axis__legend"><span><i />{t('关键节点')}</span><span><i />{t('常规场景')}</span></div>
      <div className="writer-axis__viewport">
        {chunks(beats, ROW_SIZE).map((row, rowIndex) => (
          <div className="writer-axis__row" key={`row-${rowIndex}`} style={{ '--axis-columns': row.length } as React.CSSProperties}>
            {row.map(({ scene, index, event, major }) => (
              <article className={`writer-axis__beat ${major ? 'is-major' : ''} ${index % 2 === 0 ? 'is-top' : 'is-bottom'}`} key={`${scene.scene_id}-${index}`}>
                <div className="writer-axis__content">
                  <span>{major ? event?.phase || '关键节点' : scene.duration || '场景'}</span>
                  <strong>
                    {(major ? eventTitle(event?.title, 18) : '') || summarizeSceneEvent(scene.content, 18) || `场景 ${index + 1}`}
                  </strong>
                  <small>{scene.scene_id || `S${index + 1}`}</small>
                </div>
                <span className="writer-axis__marker" aria-hidden="true" />
                <span className="writer-axis__number">{index + 1}</span>
              </article>
            ))}
          </div>
        ))}
      </div>
      <p className="writer-axis__hint"><Clock3 aria-hidden="true" /> {t('场景按剧本顺序排列，深色大节点代表主线节拍切换。')}</p>
    </div>
  );
}
