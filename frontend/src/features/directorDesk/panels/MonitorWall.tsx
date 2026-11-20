import { lazy, Suspense, useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { MonitorPlay, PanelLeftClose } from 'lucide-react';

import { parseAspect } from '../../spatial/floorPlanGeometry';
import type { StagePlan } from '../../spatial/spatialTypes';
import type { ResolveOptions } from '../lib/contacts';
import { monitorsOf, type Monitor, type MonitorRole } from '../lib/monitors';

// three.js stays out of the desk's first load; the wall's canvas comes with the wall.
const MonitorRenderer = lazy(() => import('../three/MonitorRenderer'));

interface Props {
  /** The plan as stored (with the drag in progress): each monitor samples its own shot from it. */
  plan: StagePlan;
  shotId: number | null;
  /** The playhead in the current shot. */
  now: number;
  playing: boolean;
  hidden: string[];
  contactOptions?: ResolveOptions;
  /** The lens the stage is looking through right now. */
  activeLensId: string;
  /** 成片预演: only the shots, as the cut plays them. */
  previewing: boolean;
  onPickShot: (shotId: number) => void;
  onPickLens: (cameraId: string) => void;
  onClose: () => void;
}

// An edit or a scrub redraws the wall once it settles, not on every step of it.
const SETTLE_MS = 300;
const ROLE_LABELS: Record<MonitorRole, string> = { shot: '', cut: '切镜', candidate: '候选', filming: '主机位' };

export function MonitorWall({ plan, shotId, now, playing, hidden, contactOptions, activeLensId, previewing, onPickShot, onPickLens, onClose }: Props) {
  const pick = useCallback(
    () => monitorsOf(plan, shotId, now, hidden, contactOptions).filter(monitor => !previewing || monitor.role === 'shot'),
    [contactOptions, hidden, now, plan, previewing, shotId],
  );
  const [monitors, setMonitors] = useState<Monitor[]>(pick);
  const [drawn, setDrawn] = useState<Record<string, { signature: string; url: string }>>({});
  const [notice, setNotice] = useState('');

  // While it plays, the stage itself is the live picture; the wall catches up when it stops.
  useEffect(() => {
    if (playing) return undefined;
    const timer = window.setTimeout(() => setMonitors(pick()), SETTLE_MS);
    return () => window.clearTimeout(timer);
  }, [pick, playing]);

  const onDrawn = useCallback((key: string, signature: string, url: string) => {
    setDrawn(current => ({ ...current, [key]: { signature, url } }));
  }, []);
  // One at a time, top to bottom: the first monitor whose picture is not of what it sees now.
  const pending = notice ? null : monitors.find(monitor => drawn[monitor.key]?.signature !== monitor.signature) ?? null;

  const activeKey = monitors.find(monitor => monitor.shotId === shotId && monitor.cameraId === activeLensId)?.key
    ?? (shotId !== null ? `shot:${shotId}` : '');
  const list = useRef<HTMLOListElement>(null);
  useEffect(() => {
    const item = [...(list.current?.querySelectorAll<HTMLElement>('[data-monitor]') ?? [])].find(node => node.dataset.monitor === activeKey);
    item?.scrollIntoView?.({ block: 'nearest' });
  }, [activeKey]);

  const aspect = parseAspect(plan.aspect_ratio);
  return (
    <section className="desk-monitors" aria-label="监视器" style={{ '--desk-aspect': String(aspect) } as CSSProperties}>
      <div className="desk-monitors__head">
        <h2><MonitorPlay aria-hidden="true" /> 监视器</h2>
        <button type="button" className="desk-icon" aria-label="收起监视器" title="收起监视器" onClick={onClose}><PanelLeftClose aria-hidden="true" /></button>
      </div>
      {notice && <p className="desk-monitors__notice" role="status">{notice}</p>}
      {monitors.length === 0 && <p className="desk-monitors__empty">本场还没有机位。</p>}
      <ol ref={list} className="desk-monitors__list" aria-label="本场监视器">
        {monitors.map(monitor => {
          const active = monitor.key === activeKey;
          const picture = drawn[monitor.key]?.url;
          const role = ROLE_LABELS[monitor.role];
          return (
            <li key={monitor.key} data-monitor={monitor.key} className={`desk-monitors__item ${monitor.role === 'shot' ? '' : 'is-lens'}`}>
              <button
                type="button" aria-pressed={active} className={active ? 'is-active' : ''} aria-label={`${monitor.title}，${role ? `${role}，` : ''}${monitor.detail}`}
                title={monitor.role === 'shot' ? `切到${monitor.title}` : `从 ${monitor.title} 看`}
                onClick={() => (monitor.role === 'shot' ? onPickShot(monitor.shotId) : onPickLens(monitor.cameraId))}
              >
                <span className="desk-monitors__thumb">
                  {picture ? <img src={picture} alt="" /> : <span>{notice ? '无画面' : '生成中…'}</span>}
                </span>
                <span className="desk-monitors__caption">
                  <strong>{monitor.title}</strong>
                  <small>{role && <em>{role}</em>}{monitor.detail}</small>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      <Suspense fallback={null}>
        <MonitorRenderer monitor={pending} hidden={hidden} aspect={aspect} onDrawn={onDrawn} onUnavailable={setNotice} />
      </Suspense>
    </section>
  );
}
