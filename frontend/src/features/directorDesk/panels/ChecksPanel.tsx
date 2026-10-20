import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, CircleCheck, ShieldCheck, TriangleAlert, Wrench } from 'lucide-react';

import { fetchSpatialRepairs } from '../../spatial/spatialApi';
import type { SpatialRepair, SpatialRepairsResponse, StagePlan } from '../../spatial/spatialTypes';
import type { EditRequest } from '../deskTypes';

interface Props {
  taskId: string;
  sceneId: string;
  plan: StagePlan;
  shotId: number | null;
  editable: boolean;
  /** An edit is on its way to the server: the checks on screen are about to be replaced. */
  saving: boolean;
  onCommit: (request: EditRequest) => void;
  onSelectShot: (shotId: number) => void;
}

// Edits land in bursts (a drag, its undo, a re-frame); only the revision that settles is worth asking about.
const DEBOUNCE_MS = 300;
const SEVERITY_LABELS = { error: '错误', warning: '提示' } as const;

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function ChecksPanel({ taskId, sceneId, plan, shotId, editable, saving, onCommit, onSelectShot }: Props) {
  const [open, setOpen] = useState(true);
  const [repairs, setRepairs] = useState<SpatialRepairsResponse | null>(null);
  const [notice, setNotice] = useState('');
  const [attempt, setAttempt] = useState(0);
  const failing = plan.checks.filter(check => !check.passed);
  const anyFailing = failing.length > 0;
  const revision = plan.revision;

  useEffect(() => {
    // A clean plan has nothing to repair: the server is not asked, and the last answer is left to go stale.
    if (!anyFailing) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      fetchSpatialRepairs(taskId, sceneId, controller.signal)
        .then(data => {
          if (controller.signal.aborted) return;
          if (!Array.isArray(data.repairs)) throw new Error('修正建议的格式不对。');
          setRepairs(data);
          setNotice('');
        })
        .catch(error => { if (!controller.signal.aborted) setNotice(messageOf(error, '修正建议读取失败。')); });
    }, DEBOUNCE_MS);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [anyFailing, attempt, revision, sceneId, taskId]);

  // Operations worked out on another revision would land on a plan they were not meant for.
  const current = anyFailing && repairs && repairs.revision === revision ? repairs : null;
  const canCommit = editable && !saving && current !== null;
  const automatic = current?.automatic ?? 0;
  const fix = (repair: SpatialRepair) => onCommit({ label: `修正：${repair.label}`, operations: repair.operations, barrier: true });
  const fixAll = () => { if (current?.operations.length) onCommit({ label: '一键修正', operations: current.operations, barrier: true }); };

  return (
    <section className="desk-checks-panel" aria-label="检查与修正">
      <h2>
        <button type="button" className="desk-checks-panel__toggle" aria-expanded={open} onClick={() => setOpen(value => !value)}>
          {open ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}
          <ShieldCheck aria-hidden="true" /> 检查与修正
          {anyFailing
            ? <em className="desk-badge is-failing" aria-label={`${failing.length} 项未通过`}>{failing.length} 项未通过</em>
            : <em className="desk-badge is-passed">全部通过</em>}
        </button>
        {anyFailing && (
          <button
            type="button" className="desk-button is-primary" disabled={!canCommit || automatic === 0}
            title={!editable ? '当前不能编辑' : saving ? '正在保存，稍后再试' : !current ? '正在整理修正建议' : automatic === 0 ? '没有可以自动修正的项' : '把所有可自动修正的项一次改好，可撤销'}
            onClick={fixAll}
          >
            <Wrench aria-hidden="true" /> 一键修正 ({automatic})
          </button>
        )}
      </h2>
      {open && (
        <div className="desk-checks-panel__body">
          {notice && (
            <p className="desk-checks-panel__notice" role="alert">
              {notice} <button type="button" className="desk-chip" onClick={() => setAttempt(value => value + 1)}>重试</button>
            </p>
          )}
          {anyFailing && !current && !notice && <p className="desk-checks-panel__note" role="status">正在整理修正建议…</p>}
          {plan.checks.length === 0 && <p className="desk-inspector__empty">本场还没有校验结果。</p>}
          <ul className="desk-checks">
            {plan.checks.map(check => {
              const repair = check.passed ? undefined : current?.repairs.find(item => item.code === check.code);
              return (
                <li key={check.code} className={check.passed ? 'is-passed' : `is-${check.severity}`}>
                  {check.passed ? <CircleCheck aria-hidden="true" /> : <TriangleAlert aria-hidden="true" />}
                  <div className="desk-checks__body">
                    <span><strong>{check.passed ? '通过' : SEVERITY_LABELS[check.severity]}</strong> {check.detail}</span>
                    {check.shot_ids.length > 0 && (
                      <span className="desk-checks__shots" role="group" aria-label="涉及镜头">
                        {check.shot_ids.map(id => (
                          <button key={id} type="button" className="desk-chip" aria-pressed={id === shotId} aria-label={`切换到第 ${id} 镜`} onClick={() => onSelectShot(id)}>第 {id} 镜</button>
                        ))}
                      </span>
                    )}
                    {repair && (repair.automatic ? (
                      <span className="desk-checks__repair">
                        <button type="button" className="desk-button" disabled={!canCommit} title={repair.detail} onClick={() => fix(repair)}><Wrench aria-hidden="true" /> 修正</button>
                        <small>{repair.label}{repair.detail ? ` · ${repair.detail}` : ''}</small>
                      </span>
                    ) : (
                      <small className="desk-checks__manual" role="note">{repair.label}：{repair.manual}</small>
                    ))}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}
