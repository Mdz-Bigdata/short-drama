import { Network, Pencil, Plus, Trash2 } from 'lucide-react';
import { useId, useState, type FormEvent } from 'react';

import type { WriterRelationship, WriterRole } from './types';

interface Position { x: number; y: number }
const MAX_GRAPH_NODES = 12;
const MAX_GRAPH_EDGES = 80;
const RELATIONSHIP_PAGE_SIZE = 20;

interface RelationshipForm {
  target: WriterRelationship | null;
  from: string;
  to: string;
  relation: string;
  bidirectional: boolean;
}

function isBidirectional(edge: WriterRelationship) {
  return edge.bidirectional === true || /^同场互动(?:\s|·|$)/.test(String(edge.relation || ''));
}

function collectNames(roles: WriterRole[], relationships: WriterRelationship[], declaredLead?: string) {
  const names: string[] = [];
  const seen = new Set<string>();
  const add = (name?: string) => {
    if (!name || seen.has(name) || names.length >= 500) return;
    seen.add(name);
    names.push(name);
  };
  add(declaredLead);
  for (const edge of relationships) {
    add(edge.from);
    add(edge.to);
    if (names.length >= 500) break;
  }
  for (const role of roles) {
    add(role.name);
    if (names.length >= 500) break;
  }
  return names;
}

function edgeGeometry(
  edge: WriterRelationship,
  sameDirectionIndex: number,
  sameDirectionCount: number,
  reverseExists: boolean,
  positions: Record<string, Position>,
  lead: string,
) {
  const start = edge.from ? positions[edge.from] : undefined;
  const end = edge.to ? positions[edge.to] : undefined;
  if (!start || !end || !edge.from || !edge.to) return null;
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const distance = Math.hypot(dx, dy) || 1;
  const ux = dx / distance;
  const uy = dy / distance;
  const startRadius = edge.from === lead ? 43 : 34;
  const endRadius = edge.to === lead ? 43 : 34;
  const sx = start.x + ux * startRadius;
  const sy = start.y + uy * startRadius;
  const ex = end.x - ux * endRadius;
  const ey = end.y - uy * endRadius;
  const laneOffset = (sameDirectionIndex - (sameDirectionCount - 1) / 2) * 28;
  const curve = reverseExists
    ? 30 + laneOffset
    : sameDirectionCount > 1
      ? laneOffset
      : 0;
  const normalX = -uy;
  const normalY = ux;
  const cx = (sx + ex) / 2 + normalX * curve;
  const cy = (sy + ey) / 2 + normalY * curve;
  return {
    path: `M ${sx.toFixed(1)} ${sy.toFixed(1)} Q ${cx.toFixed(1)} ${cy.toFixed(1)} ${ex.toFixed(1)} ${ey.toFixed(1)}`,
    labelX: 0.25 * sx + 0.5 * cx + 0.25 * ex,
    labelY: 0.25 * sy + 0.5 * cy + 0.25 * ey,
  };
}

export function CharacterRelationshipGraph({
  roles,
  relationships,
  onSaveRelationships,
}: {
  roles: WriterRole[];
  relationships: WriterRelationship[];
  onSaveRelationships?: (relationships: WriterRelationship[]) => Promise<void>;
}) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const markerId = `writer-relation-arrow-${uid}`;
  const nodeGradientId = `writer-relation-node-${uid}`;
  const leadGradientId = `writer-relation-lead-${uid}`;
  const glowId = `writer-relation-glow-${uid}`;
  const namesDatalistId = `writer-relation-names-${uid}`;
  const [relationshipPage, setRelationshipPage] = useState(0);
  const [form, setForm] = useState<RelationshipForm | null>(null);
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState('');
  const declaredLead = roles.find(role => role.name && /主角|女主|男主/.test(role.position || ''))?.name;
  const allNames = collectNames(roles, relationships, declaredLead);
  if (allNames.length === 0) {
    return (
      <div className="writer-relationship-empty">
        <Network aria-hidden="true" />
        <p>识别角色后，这里会生成以主角为中心的人物关系图谱。</p>
      </div>
    );
  }

  const validRelationships = relationships.filter(edge => edge.from && edge.to && edge.from !== edge.to);
  const degrees = new Map<string, number>();
  validRelationships.forEach(edge => {
    degrees.set(String(edge.from), (degrees.get(String(edge.from)) || 0) + 1);
    degrees.set(String(edge.to), (degrees.get(String(edge.to)) || 0) + 1);
  });
  const degree = (name: string) => degrees.get(name) || 0;
  const lead = declaredLead || [...allNames].sort((a, b) => degree(b) - degree(a))[0];
  const originalOrder = new Map(allNames.map((name, index) => [name, index]));
  const rankedOthers = allNames
    .filter(name => name !== lead)
    .sort((a, b) => degree(b) - degree(a) || Number(originalOrder.get(a)) - Number(originalOrder.get(b)));
  const names = [lead, ...rankedOthers].slice(0, MAX_GRAPH_NODES);
  const graphNameSet = new Set(names);
  const eligibleGraphRelationships = validRelationships.filter(edge => graphNameSet.has(String(edge.from)) && graphNameSet.has(String(edge.to)));
  const graphRelationships = [
    ...eligibleGraphRelationships.filter(edge => edge.from === lead || edge.to === lead),
    ...eligibleGraphRelationships.filter(edge => edge.from !== lead && edge.to !== lead),
  ].slice(0, MAX_GRAPH_EDGES);
  const directionKey = (from?: string, to?: string) => JSON.stringify([from, to]);
  const directionCounts = new Map<string, number>();
  graphRelationships.forEach(edge => {
    const key = directionKey(edge.from, edge.to);
    directionCounts.set(key, (directionCounts.get(key) || 0) + 1);
  });
  const directionIndexes = new Map<string, number>();
  const graphEdgeEntries = graphRelationships.map(edge => {
    const key = directionKey(edge.from, edge.to);
    const sameDirectionIndex = directionIndexes.get(key) || 0;
    directionIndexes.set(key, sameDirectionIndex + 1);
    return {
      edge,
      sameDirectionIndex,
      sameDirectionCount: directionCounts.get(key) || 1,
      reverseExists: directionCounts.has(directionKey(edge.to, edge.from)),
    };
  });
  const hiddenNames = allNames.filter(name => !graphNameSet.has(name));
  const relationshipPageCount = Math.max(1, Math.ceil(validRelationships.length / RELATIONSHIP_PAGE_SIZE));
  const activeRelationshipPage = Math.min(relationshipPage, relationshipPageCount - 1);
  const visibleRelationships = validRelationships.slice(
    activeRelationshipPage * RELATIONSHIP_PAGE_SIZE,
    (activeRelationshipPage + 1) * RELATIONSHIP_PAGE_SIZE,
  );
  const others = names.filter(name => name !== lead);
  const positions: Record<string, Position> = { [lead]: { x: 340, y: 195 } };
  others.forEach((name, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(others.length, 1) - Math.PI / 2;
    positions[name] = { x: 340 + 250 * Math.cos(angle), y: 195 + 142 * Math.sin(angle) };
  });
  const roleLabel = (name: string) => roles.find(role => role.name === name)?.position || '剧情角色';

  const commit = async (next: WriterRelationship[]) => {
    if (!onSaveRelationships) return;
    setSaving(true);
    setEditError('');
    try {
      await onSaveRelationships(next);
      setForm(null);
    } catch (error) {
      setEditError(error instanceof Error && error.message ? error.message : '关系保存失败，请稍后重试。');
    } finally {
      setSaving(false);
    }
  };

  const submitForm = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!form || saving) return;
    const from = form.from.trim();
    const to = form.to.trim();
    if (!from || !to) {
      setEditError('请填写关系两端的角色名。');
      return;
    }
    if (from === to) {
      setEditError('关系两端不能是同一个角色。');
      return;
    }
    const entry: WriterRelationship = {
      from,
      to,
      relation: form.relation.trim() || '剧情关联',
      bidirectional: form.bidirectional,
    };
    const next = [...relationships];
    const targetIndex = form.target ? next.indexOf(form.target) : -1;
    if (targetIndex >= 0) next[targetIndex] = entry;
    else next.push(entry);
    void commit(next);
  };

  const startCreate = () => {
    setEditError('');
    setForm({ target: null, from: '', to: '', relation: '', bidirectional: false });
  };

  const startEdit = (edge: WriterRelationship) => {
    setEditError('');
    setForm({
      target: edge,
      from: String(edge.from || ''),
      to: String(edge.to || ''),
      relation: String(edge.relation || ''),
      bidirectional: isBidirectional(edge),
    });
  };

  const removeEdge = (edge: WriterRelationship) => {
    if (saving) return;
    if (form?.target === edge) setForm(null);
    void commit(relationships.filter(item => item !== edge));
  };

  return (
    <div className="writer-relationship-layout">
      <svg
        className="writer-relationship-graph"
        viewBox="0 0 680 390"
        role="img"
        aria-label={allNames.length === names.length
          ? `${names.length}名角色、${graphRelationships.length}条人物关系组成的关系图谱`
          : `图中展示${names.length}/${allNames.length}名角色、${graphRelationships.length}/${validRelationships.length}条人物关系`}
      >
        <defs>
          <marker id={markerId} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0L8 4L0 8Z" />
          </marker>
          <radialGradient id={nodeGradientId} cx="50%" cy="38%" r="72%">
            <stop offset="0%" stopColor="#1d3a4e" />
            <stop offset="100%" stopColor="#0a141f" />
          </radialGradient>
          <radialGradient id={leadGradientId} cx="50%" cy="38%" r="72%">
            <stop offset="0%" stopColor="#155a63" />
            <stop offset="100%" stopColor="#0a1a24" />
          </radialGradient>
          <filter id={glowId} x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <g className="writer-relationship-graph__orbit">
          <ellipse cx="340" cy="195" rx="250" ry="142" />
          <ellipse cx="340" cy="195" rx="168" ry="96" />
        </g>
        {graphEdgeEntries.map(({ edge, sameDirectionIndex, sameDirectionCount, reverseExists }, index) => {
          const geometry = edgeGeometry(edge, sameDirectionIndex, sameDirectionCount, reverseExists, positions, lead);
          if (!geometry) return null;
          const label = String(edge.relation || '剧情关联');
          const bidirectional = isBidirectional(edge);
          const touchesLead = edge.from === lead || edge.to === lead;
          const visibleLabel = label.length > 10 ? `${label.slice(0, 9)}…` : label;
          const labelWidth = Math.min(132, Math.max(42, visibleLabel.length * 13 + 16));
          return (
            <g
              className={`writer-relationship-graph__edge ${touchesLead ? 'is-lead-edge' : ''}`}
              key={`${edge.from}-${edge.to}-${index}`}
            >
              <title>{`${edge.from} ${bidirectional ? '双向' : '指向'} ${edge.to}：${label}`}</title>
              <path
                d={geometry.path}
                data-relation-edge="true"
                markerStart={bidirectional ? `url(#${markerId})` : undefined}
                markerEnd={`url(#${markerId})`}
              />
              <rect x={geometry.labelX - labelWidth / 2} y={geometry.labelY - 11} width={labelWidth} height="22" rx="11" />
              <text x={geometry.labelX} y={geometry.labelY + 4}>{visibleLabel}</text>
            </g>
          );
        })}
        {names.map(name => {
          const position = positions[name];
          const isLead = name === lead;
          return (
            <g className={`writer-relationship-graph__node ${isLead ? 'is-lead' : ''}`} key={name} transform={`translate(${position.x} ${position.y})`}>
              {isLead && <circle className="writer-relationship-graph__halo" r="46" filter={`url(#${glowId})`} />}
              <circle r={isLead ? 38 : 29} fill={`url(#${isLead ? leadGradientId : nodeGradientId})`} />
              <text className="writer-relationship-graph__name" y="-2">{name.slice(0, 5)}</text>
              <text className="writer-relationship-graph__role" y="15">{roleLabel(name).slice(0, 8)}</text>
            </g>
          );
        })}
      </svg>

      <div className="writer-relationship-list" aria-label="人物关系列表">
        <div>
          <span>CHARACTER LINKS</span>
          <strong>{validRelationships.length}</strong>
        </div>
        {onSaveRelationships && (
          <div className="writer-relationship-editor">
            <button
              type="button"
              className="writer-relationship-editor__add"
              disabled={saving}
              onClick={startCreate}
            >
              <Plus aria-hidden="true" /> 新增关系
            </button>
            {saving && <small role="status">保存中…</small>}
            {editError && <small className="is-error" role="alert">{editError}</small>}
            {form && (
              <form
                className="writer-relationship-editor__form"
                aria-label={form.target ? '编辑人物关系' : '新增人物关系'}
                onSubmit={submitForm}
              >
                <label>
                  <span>从</span>
                  <input
                    list={namesDatalistId}
                    value={form.from}
                    maxLength={80}
                    placeholder="角色名"
                    onChange={event => setForm(current => current && { ...current, from: event.target.value })}
                  />
                </label>
                <label>
                  <span>到</span>
                  <input
                    list={namesDatalistId}
                    value={form.to}
                    maxLength={80}
                    placeholder="角色名"
                    onChange={event => setForm(current => current && { ...current, to: event.target.value })}
                  />
                </label>
                <label>
                  <span>关系</span>
                  <input
                    value={form.relation}
                    maxLength={120}
                    placeholder="如：师徒 / 对立 / 盟友"
                    onChange={event => setForm(current => current && { ...current, relation: event.target.value })}
                  />
                </label>
                <label className="writer-relationship-editor__toggle">
                  <input
                    type="checkbox"
                    checked={form.bidirectional}
                    onChange={event => setForm(current => current && { ...current, bidirectional: event.target.checked })}
                  />
                  <span>双向关系</span>
                </label>
                <datalist id={namesDatalistId}>
                  {allNames.map(name => <option key={name} value={name} />)}
                </datalist>
                <div className="writer-relationship-editor__actions">
                  <button type="submit" disabled={saving}>{form.target ? '保存修改' : '添加'}</button>
                  <button type="button" disabled={saving} onClick={() => { setForm(null); setEditError(''); }}>取消</button>
                </div>
              </form>
            )}
          </div>
        )}
        {hiddenNames.length > 0 && (
          <div className="writer-relationship-list__overflow" aria-label={`图外角色 ${hiddenNames.length} 名`}>
            <span>图外角色</span>
            {hiddenNames.map(name => <small key={name}><strong>{name}</strong> · {roleLabel(name)}</small>)}
          </div>
        )}
        {validRelationships.length > 0 ? visibleRelationships.map((edge, index) => {
          const bidirectional = isBidirectional(edge);
          return (
            <article key={`${edge.from}-${edge.to}-list-${activeRelationshipPage}-${index}`}>
              <p><strong>{edge.from || '未知'}</strong><span aria-label={bidirectional ? '双向关系' : '指向'}>{bidirectional ? '↔' : '→'}</span><strong>{edge.to || '未知'}</strong></p>
              <small>{edge.relation || '存在剧情关联'}</small>
              {onSaveRelationships && (
                <span className="writer-relationship-list__tools">
                  <button
                    type="button"
                    aria-label={`编辑 ${edge.from} 与 ${edge.to} 的关系`}
                    disabled={saving}
                    onClick={() => startEdit(edge)}
                  >
                    <Pencil aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    aria-label={`删除 ${edge.from} 与 ${edge.to} 的关系`}
                    disabled={saving}
                    onClick={() => removeEdge(edge)}
                  >
                    <Trash2 aria-hidden="true" />
                  </button>
                </span>
              )}
            </article>
          );
        }) : <p className="writer-relationship-list__empty">角色已识别，但剧本中尚未提取到可靠关系；补充分场角色或人物关系后即可生成连线。</p>}
        {relationshipPageCount > 1 && (
          <nav className="writer-relationship-list__pagination" aria-label="人物关系列表分页">
            <button type="button" disabled={activeRelationshipPage === 0} onClick={() => setRelationshipPage(activeRelationshipPage - 1)}>上一页</button>
            <span>{activeRelationshipPage + 1} / {relationshipPageCount}</span>
            <button type="button" disabled={activeRelationshipPage === relationshipPageCount - 1} onClick={() => setRelationshipPage(activeRelationshipPage + 1)}>下一页</button>
          </nav>
        )}
      </div>
    </div>
  );
}
