import { useEffect, useMemo, useRef, useState } from 'react';
import { Boxes, Download, ImagePlus, Send, Sparkles, Trash2, Undo2, Wand2 } from 'lucide-react';

import type { GroundPoint, StagePlan } from '../../spatial/spatialTypes';
import type { EditRequest, SelectionRef } from '../deskTypes';
import {
  adoptStagePlan, chatWithDirector, clearDirectorChat, describeBlockout, fetchDirectorState, fetchModelKits, optimizeStage, planStage,
  proposeModel, revertStageStep, setPipelinePlanner, stageModelUrl,
  type ModelKit, type ModelProposal, type StageChange, type StageChatRow, type StageDirectorState, type StagePlanCandidate,
} from '../directorApi';
import type { BlockoutProposal } from '../directorDeskApi';
import { BlockoutPlan } from './BlockoutPanel';

interface Props {
  taskId: string;
  sceneId: string;
  plan: StagePlan;
  /** The shot the desk is on; none on a stage with no shots yet. */
  shotId: number | null;
  selection: SelectionRef[];
  editable: boolean;
  saving: boolean;
  dropPoint: () => GroundPoint;
  onCommit: (request: EditRequest) => void;
  /** The server changed the stage: read it again. */
  onPlanChanged: () => void;
  onSelect: (ref: SelectionRef) => void;
}

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function freeName(base: string, plan: StagePlan) {
  const taken = new Set([...plan.landmarks.map(item => item.name), ...plan.actors.map(actor => actor.name)]);
  if (!taken.has(base)) return base;
  let number = 2;
  while (taken.has(`${base} ${number}`)) number += 1;
  return `${base} ${number}`;
}

/** A candidate seen from above: the set, the people and where the first lens stands, so stagings can be told apart at a glance. */
export function StagingThumb({ plan }: { plan: StagePlan }) {
  const view = useMemo(() => {
    const people = plan.actors.filter(actor => !actor.crowd_id);
    const points = [
      ...people.map(actor => actor.position),
      ...plan.landmarks.flatMap(piece => [
        [piece.position[0] - piece.size[0] / 2, piece.position[1] - piece.size[1] / 2],
        [piece.position[0] + piece.size[0] / 2, piece.position[1] + piece.size[1] / 2],
      ]),
    ];
    const xs = points.map(point => point[0]);
    const zs = points.map(point => point[1]);
    const pad = 1;
    const left = Math.min(-2, ...xs) - pad;
    const top = Math.min(-2, ...zs) - pad;
    const width = Math.max(2, ...xs) + pad - left;
    const height = Math.max(2, ...zs) + pad - top;
    return { people, box: `${left} ${top} ${width} ${height}`, dot: Math.max(width, height) * 0.025 };
  }, [plan]);
  const firstLens = plan.cameras.find(camera => camera.id === plan.shots[0]?.camera_id);
  return (
    <svg className="desk-director__thumb" viewBox={view.box} role="img" aria-label={`俯视图：${view.people.length} 人，${plan.landmarks.length} 件布景`}>
      {plan.landmarks.map(piece => (
        <rect
          key={piece.id} x={-piece.size[0] / 2} y={-piece.size[1] / 2} width={piece.size[0]} height={piece.size[1]}
          transform={`translate(${piece.position[0]} ${piece.position[1]}) rotate(${-(piece.yaw_deg ?? 0)})`}
          className={piece.size[2] < 0.2 ? 'is-floor' : ''}
        />
      ))}
      {view.people.map(actor => (
        <circle key={actor.id} cx={actor.position[0]} cy={actor.position[1]} r={view.dot * 1.6} className={actor.role === 'principal' ? 'is-lead' : ''}>
          <title>{actor.name}</title>
        </circle>
      ))}
      {firstLens && <circle cx={firstLens.position[0]} cy={firstLens.position[2]} r={view.dot} className="is-lens" />}
    </svg>
  );
}

function ModelFront({ proposal }: { proposal: ModelProposal }) {
  const [width, , height] = proposal.size;
  return (
    <svg className="desk-director__front" viewBox={`${-width * 0.55} ${-height * 1.05} ${width * 1.1} ${height * 1.1}`} role="img" aria-label={`${proposal.name} 的正面轮廓`}>
      {proposal.parts.map((part, index) => {
        const w = part.size[0] * width;
        const h = part.size[2] * height;
        const x = part.center[0] * width;
        const y = -part.center[1] * height;
        return <rect key={index} x={x - w / 2} y={y - h / 2} width={w} height={h} className={part.tone ? `is-${part.tone}` : ''} />;
      })}
    </svg>
  );
}

function changedRefs(change: StageChange | undefined): Array<{ label: string; ref: SelectionRef }> {
  if (!change) return [];
  return [
    ...change.actors.map(name => ({ label: name, ref: { kind: 'actor', name } as SelectionRef })),
    ...[...change.pieces_added, ...change.pieces_changed].map(name => ({ label: name, ref: { kind: 'landmark', name } as SelectionRef })),
    ...change.cameras.map(id => ({ label: `机位 ${id}`, ref: { kind: 'camera', id } as SelectionRef })),
  ];
}

function ChatRow({ row, canUndo, onUndo, onSelect }: { row: StageChatRow; canUndo: boolean; onUndo: () => void; onSelect: (ref: SelectionRef) => void }) {
  const refs = changedRefs(row.changed);
  const removed = row.changed?.pieces_removed ?? [];
  return (
    <li className={`desk-director__row is-${row.role}`}>
      <p>{row.text}</p>
      {row.scope && <small>{row.scope}</small>}
      {row.compare && <small className="desk-director__compare">{row.compare}</small>}
      {refs.length > 0 && (
        <div className="desk-director__chips" aria-label="改动了什么（点一下定位）">
          {refs.slice(0, 16).map(item => (
            <button key={`${item.ref.kind}-${item.label}`} type="button" onClick={() => onSelect(item.ref)}>{item.label}</button>
          ))}
        </div>
      )}
      {removed.length > 0 && <small>移除了：{removed.join('、')}</small>}
      {!!row.errors?.length && (
        <details className="desk-director__errors"><summary>{row.errors.length} 个操作没有生效</summary><ul>{row.errors.map(item => <li key={item}>{item}</li>)}</ul></details>
      )}
      {canUndo && <button type="button" className="desk-button" onClick={onUndo}><Undo2 aria-hidden="true" /> 撤销这一步</button>}
    </li>
  );
}

function CandidateCard({ candidate, recommended, busy, onAdopt }: { candidate: StagePlanCandidate; recommended: boolean; busy: boolean; onAdopt: () => void }) {
  const { measured } = candidate;
  return (
    <li className={`desk-director__candidate ${recommended ? 'is-recommended' : ''}`}>
      <StagingThumb plan={candidate.plan} />
      <div>
        <h4>
          {candidate.title}
          {recommended && <em>推荐</em>}
          {candidate.source === 'rules' && <small>不用模型</small>}
        </h4>
        <p className="desk-director__score"><strong>{candidate.score}</strong> 分{measured.errors > 0 ? ` · ${measured.errors} 项错误` : ''}{measured.warnings > 0 ? ` · ${measured.warnings} 项警告` : ''}</p>
        {candidate.rationale && <p>{candidate.rationale}</p>}
        {measured.notes.length > 0 && <details><summary>{measured.notes.length} 个待改善</summary><ul>{measured.notes.map(note => <li key={note}>{note}</li>)}</ul></details>}
        {candidate.errors.length > 0 && <details><summary>{candidate.errors.length} 个操作没有生效</summary><ul>{candidate.errors.map(item => <li key={item}>{item}</li>)}</ul></details>}
        <button type="button" className="desk-button is-primary" disabled={busy} onClick={onAdopt}>采用这版</button>
      </div>
    </li>
  );
}

/** The stage's model-first director: plan a scene, talk it into shape, build what the set is missing. */
export function DirectorPanel({ taskId, sceneId, plan, shotId, selection, editable, saving, dropPoint, onCommit, onPlanChanged, onSelect }: Props) {
  const [state, setState] = useState<StageDirectorState | null>(null);
  const [candidates, setCandidates] = useState<StagePlanCandidate[]>([]);
  const [recommended, setRecommended] = useState('');
  const [note, setNote] = useState('');
  const [goal, setGoal] = useState('');
  const [count, setCount] = useState(3);
  const [message, setMessage] = useState('');
  const [onlySelection, setOnlySelection] = useState(false);
  const [onlyShot, setOnlyShot] = useState(false);
  const [busy, setBusy] = useState('');
  const [problem, setProblem] = useState('');
  const [kits, setKits] = useState<ModelKit[]>([]);
  const [kitGroup, setKitGroup] = useState('');
  const [modelText, setModelText] = useState('');
  const [modelFile, setModelFile] = useState<File | null>(null);
  const [proposal, setProposal] = useState<ModelProposal | null>(null);
  const [setText, setSetText] = useState('');
  const [setProposalState, setSetProposal] = useState<BlockoutProposal | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const log = useRef<HTMLOListElement>(null);
  const revision = plan.revision;
  const locked = !editable || saving || Boolean(busy);

  const load = (signal?: AbortSignal) => fetchDirectorState(taskId, sceneId, signal).then(next => {
    setState(next);
    return next;
  });

  // Candidates and the conversation live on the server, so reopening the desk finds them where they were left.
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(next => {
      setCandidates(next.candidates);
      setRecommended(next.candidates[0]?.id ?? '');
    }).catch(error => { if (!controller.signal.aborted) setProblem(messageOf(error, '导演面板读取失败。')); });
    fetchModelKits(controller.signal).then(result => {
      setKits(result.kits);
      setKitGroup(result.kits[0]?.group ?? '');
    }).catch(() => { /* the library is an extra; the rest of the panel still works */ });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per scene; the desk is keyed by it
  }, [taskId, sceneId]);

  useEffect(() => { log.current?.scrollTo?.({ top: log.current.scrollHeight }); }, [state?.chat.length]);

  // A drag or an inspector edit changes the score too.
  const firstRevision = useRef(revision);
  useEffect(() => {
    if (revision === firstRevision.current || saving) return undefined;
    const controller = new AbortController();
    load(controller.signal).catch(() => { /* the number just stays as it was until the next read */ });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a new revision is news
  }, [revision, saving]);

  const names = useMemo(() => selection.flatMap(ref => ('name' in ref ? [ref.name] : [])), [selection]);
  const scope = { names: onlySelection ? names : [], shotId: onlyShot && shotId !== null ? shotId : undefined };
  const undoable = new Set(state?.snapshots.map(item => item.id) ?? []);
  const groups = useMemo(() => [...new Set(kits.map(kit => kit.group))], [kits]);
  const selectedPiece = selection.length === 1 && selection[0].kind === 'landmark'
    ? plan.landmarks.find(item => item.name === (selection[0] as { name: string }).name) : undefined;

  const run = async (label: string, work: () => Promise<void>) => {
    if (busy) return;
    setBusy(label);
    setProblem('');
    try {
      await work();
    } catch (error) {
      setProblem(messageOf(error, `${label}失败，请稍后重试。`));
    } finally {
      setBusy('');
    }
  };

  const planIt = () => run('模型规划中', async () => {
    const result = await planStage(taskId, sceneId, revision, { count, goal: goal.trim() });
    setCandidates(result.candidates);
    setRecommended(result.recommended);
    setNote(result.note);
  });

  const adopt = (candidate: StagePlanCandidate) => run('采用方案中', async () => {
    await adoptStagePlan(taskId, sceneId, revision, candidate.id);
    setCandidates([]);
    setNote('');
    onPlanChanged();
    await load();
  });

  const send = () => run('模型调整中', async () => {
    const text = message.trim();
    const result = await chatWithDirector(taskId, sceneId, revision, text, scope);
    setMessage('');
    if (result.changed) onPlanChanged();
    await load();
  });

  const optimize = () => run('优化中', async () => {
    const result = await optimizeStage(taskId, sceneId, revision, message.trim(), scope);
    setMessage('');
    if (result.changed) onPlanChanged();
    await load();
  });

  const undo = (snapshotId: string) => run('撤销中', async () => {
    await revertStageStep(taskId, sceneId, revision, snapshotId);
    onPlanChanged();
    await load();
  });

  const clear = () => run('清空中', async () => {
    await clearDirectorChat(taskId, sceneId);
    await load();
  });

  const togglePipeline = () => run('保存中', async () => {
    const next = state?.pipeline_planner === 'rules' ? 'model' : 'rules';
    await setPipelinePlanner(taskId, next);
    setState(current => (current ? { ...current, pipeline_planner: next } : current));
  });

  const placeKit = (kit: ModelKit) => {
    const name = freeName(kit.name, plan);
    onCommit({ label: `添加 ${name}`, barrier: true, operations: [{ op: 'add_landmark', name, kit: kit.id, kind: kit.kind, position: dropPoint(), yaw_deg: 0 }] });
    onSelect({ kind: 'landmark', name });
  };

  const build = () => run('模型搭建中', async () => {
    setProposal(await proposeModel(taskId, sceneId, modelText.trim(), modelFile));
  });

  const placeProposal = () => {
    if (!proposal) return;
    const name = freeName(proposal.name, plan);
    onCommit({
      label: `添加 ${name}`, barrier: true,
      operations: [{
        op: 'add_landmark', name, kind: proposal.kind, position: dropPoint(), yaw_deg: 0, size: proposal.size, kit: proposal.kit, fitted_parts: proposal.parts,
      }],
    });
    onSelect({ kind: 'landmark', name });
    setProposal(null);
    setModelText('');
    setModelFile(null);
  };

  const buildSet = () => run('模型搭景中', async () => {
    setSetProposal(await describeBlockout(taskId, sceneId, setText.trim()));
  });

  const placeSet = () => {
    if (!setProposalState) return;
    onCommit({ label: `文字白模（${setProposalState.pieces.length} 块）`, barrier: true, operations: [{ op: 'apply_blockout', replace: true, pieces: setProposalState.pieces }] });
    setSetProposal(null);
    setSetText('');
  };

  const measured = state?.measured;
  return (
    <section className="desk-director" aria-label="AI 导演">
      <header className="desk-director__head">
        <h2><Sparkles aria-hidden="true" /> AI 导演</h2>
        {measured && <p><strong>{measured.score}</strong> 分{measured.errors > 0 ? ` · ${measured.errors} 项错误` : ''} · {plan.planner === 'model' ? '模型规划' : '规则规划'}{plan.source === 'edited' ? '，已修改' : ''}</p>}
      </header>
      {plan.planner_note && <p className="desk-captures__note">{plan.planner_note}</p>}
      {!!measured?.notes.length && (
        <details className="desk-director__issues"><summary>{measured.notes.length} 个待改善</summary><ul>{measured.notes.map(item => <li key={item}>{item}</li>)}</ul></details>
      )}
      {busy && <p className="desk-director__busy" role="status">{busy}…（模型可能要想一两分钟）</p>}
      {problem && <p className="desk-field__problem" role="alert">{problem}</p>}

      <details className="desk-director__section" open>
        <summary><Wand2 aria-hidden="true" /> 自动规划</summary>
        <p className="desk-captures__note">让模型读剧本，给出几版完整调度：布景、站位、姿势、机位和运动。每版都经过修正和评分，并和规则方案比较；采用之前舞台不变。每版调用一到两次文本模型。</p>
        <label className="desk-field is-wide">
          <span>额外要求（可选）</span>
          <textarea aria-label="规划的额外要求" rows={2} maxLength={2000} value={goal} placeholder="例如：压迫感强一点，女主始终在高处" onChange={event => setGoal(event.target.value)} />
        </label>
        <div className="desk-director__line">
          <label className="desk-field">
            <span>方案数</span>
            <select aria-label="方案数" value={count} onChange={event => setCount(Number(event.target.value))}>
              {[1, 2, 3].map(value => <option key={value} value={value}>{value} 版</option>)}
            </select>
          </label>
          <button type="button" className="desk-button is-primary" disabled={locked} onClick={() => { void planIt(); }}>
            <Sparkles aria-hidden="true" /> {candidates.length ? '重新规划' : '开始规划'}
          </button>
        </div>
        {note && <p className="desk-field__problem" role="status">{note}</p>}
        {candidates.length > 0 && (
          <ol className="desk-director__candidates" aria-label="调度方案">
            {candidates.map(candidate => (
              <CandidateCard key={candidate.id} candidate={candidate} recommended={candidate.id === recommended} busy={locked} onAdopt={() => { void adopt(candidate); }} />
            ))}
          </ol>
        )}
        <label className="desk-director__toggle">
          <input type="checkbox" checked={state?.pipeline_planner !== 'rules'} disabled={!state || Boolean(busy)} onChange={() => { void togglePipeline(); }} />
          生成分镜时也让模型先规划站位（每场多一次文本调用）
        </label>
      </details>

      <details className="desk-director__section" open>
        <summary><Send aria-hidden="true" /> 对话调整</summary>
        <ol ref={log} className="desk-director__log" aria-label="对话记录">
          {(state?.chat ?? []).map((row, index) => (
            <ChatRow
              key={index} row={row} onSelect={onSelect} canUndo={Boolean(row.snapshot_id && undoable.has(row.snapshot_id))}
              onUndo={() => { if (row.snapshot_id) void undo(row.snapshot_id); }}
            />
          ))}
          {!state?.chat.length && <li className="desk-captures__note">直接说想要什么：「女主往窗边走两步，背对男主」「第二镜换低机位，压迫感强一点」「加一张方桌把两人隔开」。</li>}
        </ol>
        <label className="desk-field is-wide">
          <span>对 AI 导演说</span>
          <textarea
            aria-label="对 AI 导演说" rows={3} maxLength={2000} value={message} placeholder="用自然语言描述要调整什么"
            onChange={event => setMessage(event.target.value)}
            onKeyDown={event => {
              event.stopPropagation();
              if (event.key === 'Enter' && (event.metaKey || event.ctrlKey) && message.trim() && !locked) void send();
            }}
          />
        </label>
        <div className="desk-director__toggles">
          <label><input type="checkbox" checked={onlySelection} disabled={!names.length} onChange={event => setOnlySelection(event.target.checked)} /> 只改选中{names.length ? `（${names.slice(0, 3).join('、')}${names.length > 3 ? '…' : ''}）` : ''}</label>
          {shotId !== null && <label><input type="checkbox" checked={onlyShot} onChange={event => setOnlyShot(event.target.checked)} /> 只改第 {shotId} 镜</label>}
        </div>
        <div className="desk-director__line">
          <button type="button" className="desk-button is-primary" disabled={locked || !message.trim()} onClick={() => { void send(); }}><Send aria-hidden="true" /> 发送</button>
          <button type="button" className="desk-button" disabled={locked} onClick={() => { void optimize(); }} title="规则先修，模型再优化；评分变低的结果不会保留"><Wand2 aria-hidden="true" /> 自动优化</button>
          {!!state?.chat.length && <button type="button" className="desk-button" disabled={Boolean(busy)} aria-label="清空对话" onClick={() => { void clear(); }}><Trash2 aria-hidden="true" /></button>}
        </div>
      </details>

      <details className="desk-director__section">
        <summary><Boxes aria-hidden="true" /> 建模</summary>
        <h3>模型库</h3>
        {kits.length > 0 && (
          <>
            <div className="desk-director__groups" role="tablist" aria-label="模型分类">
              {groups.map(group => (
                <button key={group} type="button" role="tab" aria-selected={group === kitGroup} className={group === kitGroup ? 'is-active' : ''} onClick={() => setKitGroup(group)}>{group}</button>
              ))}
            </div>
            <div className="desk-director__kits">
              {kits.filter(kit => kit.group === kitGroup).map(kit => (
                <button key={kit.id} type="button" disabled={!editable} title={`${kit.size[0]} × ${kit.size[1]} × ${kit.size[2]} 米`} onClick={() => placeKit(kit)}>{kit.name}</button>
              ))}
            </div>
          </>
        )}

        <h3>文字搭物体</h3>
        <label className="desk-field is-wide">
          <span>要搭的东西</span>
          <textarea aria-label="要搭的东西" rows={2} maxLength={2000} value={modelText} placeholder="例如：一辆唐代牛车，木轮，有顶棚" onChange={event => setModelText(event.target.value)} />
        </label>
        <input
          ref={file} type="file" accept="image/png,image/jpeg,image/webp" hidden aria-label="物体参考图"
          onChange={event => { setModelFile(event.target.files?.[0] ?? null); event.target.value = ''; }}
        />
        <div className="desk-director__line">
          <button type="button" className="desk-button" disabled={!editable} onClick={() => file.current?.click()}><ImagePlus aria-hidden="true" /> {modelFile ? modelFile.name : '参考图（可选）'}</button>
          <button type="button" className="desk-button is-primary" disabled={locked || (!modelText.trim() && !modelFile)} onClick={() => { void build(); }}>搭建</button>
        </div>
        {proposal && (
          <div className="desk-director__proposal">
            <ModelFront proposal={proposal} />
            <div>
              <h4>{proposal.name}</h4>
              <p>{proposal.parts.length} 块 · {proposal.size[0]} × {proposal.size[1]} × {proposal.size[2]} 米{proposal.kit ? ' · 模型库' : ''}</p>
              {proposal.summary && <p>{proposal.summary}</p>}
              {proposal.dropped > 0 && <p className="desk-field__problem">有 {proposal.dropped} 块字段不完整，已略去。</p>}
              <button type="button" className="desk-button is-primary" disabled={!editable} onClick={placeProposal}>放到舞台上</button>
            </div>
          </div>
        )}

        <h3>文字搭场景</h3>
        <label className="desk-field is-wide">
          <span>场景描述</span>
          <textarea aria-label="场景描述" rows={2} maxLength={2000} value={setText} placeholder="例如：古代客栈大堂，中间四张方桌，北面柜台，东侧楼梯上二楼" onChange={event => setSetText(event.target.value)} />
        </label>
        <button type="button" className="desk-button is-primary" disabled={locked || !setText.trim()} onClick={() => { void buildSet(); }}>搭场景</button>
        {setProposalState && (
          <div className="desk-blockout__proposal">
            <h3>场景草案 <small>{setProposalState.pieces.length} 块</small></h3>
            {setProposalState.summary && <p>{setProposalState.summary}</p>}
            <BlockoutPlan pieces={setProposalState.pieces} />
            {setProposalState.dropped > 0 && <p className="desk-field__problem">有 {setProposalState.dropped} 块字段不完整或超出上限，已略去。</p>}
            <button type="button" className="desk-button is-primary" disabled={!editable} onClick={placeSet}>铺到舞台上</button>
          </div>
        )}

        {selectedPiece && (
          <a className="desk-button" href={stageModelUrl(taskId, sceneId, selectedPiece.id)} download={`${selectedPiece.name}.glb`}>
            <Download aria-hidden="true" /> 导出「{selectedPiece.name}」为 GLB
          </a>
        )}
      </details>
    </section>
  );
}
