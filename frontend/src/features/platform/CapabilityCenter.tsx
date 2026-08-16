import { useEffect, useMemo, useState } from 'react';
import { Check, ChevronDown, ChevronRight, Command, ExternalLink, LoaderCircle, Search } from 'lucide-react';

import { apiRequest } from '../../api/client';


interface Ability {
  id: string;
  label: string;
  command: string;
  entrypoint: string;
  implementation_status: 'implemented' | 'provider-dependent' | 'interchange-only' | 'unverified';
  evidence: string;
  enabled: boolean;
}

interface CapabilitySource {
  source_id: string;
  source_url: string;
  reviewed_commit: string;
  reviewed_at: string;
  license_observation: string;
  code_treatment: 'attributed-adaptation' | 'clean-room' | 'api-interoperability';
  attribution: string;
  enabled_count: number;
  abilities: Ability[];
}

interface CapabilityResponse {
  items: CapabilitySource[];
  total: number;
}

interface CapabilityCenterProps {
  role?: string;
}


export function CapabilityCenter({ role = 'user' }: CapabilityCenterProps) {
  const [sources, setSources] = useState<CapabilitySource[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [commandText, setCommandText] = useState('');
  const [commandResult, setCommandResult] = useState('');

  useEffect(() => {
    let active = true;
    apiRequest<CapabilityResponse>('/api/platform/capabilities')
      .then(data => { if (active) setSources(data.items); })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : '能力注册表加载失败'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const enabledAbilities = useMemo(
    () => sources.flatMap(source => source.abilities).filter(item => item.enabled),
    [sources],
  );

  const toggleExpanded = (sourceId: string) => {
    setExpanded(current => {
      const next = new Set(current);
      if (next.has(sourceId)) next.delete(sourceId);
      else next.add(sourceId);
      return next;
    });
  };

  const toggleAbility = async (sourceId: string, ability: Ability) => {
    const key = `${sourceId}:${ability.id}`;
    setBusy(key);
    setError('');
    try {
      const updated = await apiRequest<Ability>(
        `/api/platform/capabilities/${sourceId}/${ability.id}`,
        { method: 'PATCH', body: JSON.stringify({ enabled: !ability.enabled }) },
      );
      setSources(current => current.map(source => source.source_id !== sourceId ? source : {
        ...source,
        enabled_count: source.enabled_count + (updated.enabled ? 1 : -1),
        abilities: source.abilities.map(item => item.id === ability.id ? updated : item),
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : '能力状态更新失败');
    } finally {
      setBusy('');
    }
  };

  const invoke = async () => {
    if (!commandText.trim()) return;
    setBusy('command');
    setCommandResult('');
    setError('');
    try {
      const result = await apiRequest<{ label: string; entrypoint: string; payload: string }>(
        '/api/platform/commands/invoke',
        { method: 'POST', body: JSON.stringify({ command: commandText.trim() }) },
      );
      setCommandResult(`${result.label} → ${result.entrypoint}${result.payload ? ` · 参数：${result.payload}` : ''}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '命令调用失败');
    } finally {
      setBusy('');
    }
  };

  return (
    <section className="capability-center" aria-labelledby="capability-title">
      <div className="capability-heading">
        <div>
          <h3 id="capability-title">工业化能力与可调用入口</h3>
          <p>{sources.length || 13} 个上游来源 · 每项能力可下拉检查、全局启用并通过 /command 调用</p>
        </div>
        <span className="capability-role">{role === 'admin' ? '管理员 · 可配置全局状态' : '成员 · 使用已启用能力'}</span>
      </div>

      <div className="command-palette" role="search">
        <Command size={18} aria-hidden="true" />
        <label htmlFor="global-command" className="sr-only">输入能力命令</label>
        <input
          id="global-command"
          list="enabled-command-list"
          value={commandText}
          onChange={event => setCommandText(event.target.value)}
          onKeyDown={event => { if (event.key === 'Enter') void invoke(); }}
          placeholder="输入 /command，例如 /minimax-h3-skills.multi-reference-video 雨夜追车"
        />
        <datalist id="enabled-command-list">
          {enabledAbilities.map(item => <option key={item.command} value={item.command}>{item.label}</option>)}
        </datalist>
        <button type="button" onClick={() => void invoke()} disabled={busy === 'command'}>
          {busy === 'command' ? <LoaderCircle className="spin" size={16} /> : <Search size={16} />}
          调用
        </button>
      </div>
      {commandResult && <div className="command-result"><Check size={15} /> {commandResult}</div>}
      {error && <div className="inline-error" role="alert">{error}</div>}

      {loading ? (
        <div className="capability-loading"><LoaderCircle className="spin" /> 正在同步全局能力注册表…</div>
      ) : (
        <div className="capability-source-grid">
          {sources.map(source => {
            const open = expanded.has(source.source_id);
            return (
              <article className={`capability-source ${open ? 'open' : ''}`} key={source.source_id}>
                <button
                  type="button"
                  className="capability-source-trigger"
                  onClick={() => toggleExpanded(source.source_id)}
                  aria-expanded={open}
                  aria-controls={`abilities-${source.source_id}`}
                  aria-label={`${source.source_id}，${source.abilities.length} 项能力`}
                >
                  <span>
                    <strong>{source.source_id}</strong>
                    <small>{source.enabled_count}/{source.abilities.length} 已启用</small>
                  </span>
                  {open ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                </button>
                {open && (
                  <div className="ability-list" id={`abilities-${source.source_id}`}>
                    <a href={source.source_url} target="_blank" rel="noreferrer" className="source-link">
                      查看能力来源 <ExternalLink size={12} />
                    </a>
                    <div className="source-provenance">
                      <span>审计 {source.reviewed_at} · {source.reviewed_commit.slice(0, 7)}</span>
                      <span>{source.code_treatment} · {source.license_observation}</span>
                      {source.attribution && <span>{source.attribution}</span>}
                    </div>
                    {source.abilities.map(ability => {
                      const key = `${source.source_id}:${ability.id}`;
                      return (
                        <div className="ability-row" key={ability.id}>
                          <div>
                            <strong>{ability.label}</strong>
                            <code>{ability.command}</code>
                            <small>{ability.entrypoint}</small>
                            <small className={`implementation-status ${ability.implementation_status}`}>
                              {ability.implementation_status === 'provider-dependent'
                                ? '已实现 · 需配置服务商'
                                : ability.implementation_status === 'interchange-only'
                                  ? '部分实现 · 仅交换格式，未验证原生导入'
                                  : '已实现'}
                              {ability.evidence ? ` · ${ability.evidence}` : ''}
                            </small>
                          </div>
                          <button
                            type="button"
                            role="switch"
                            aria-checked={ability.enabled}
                            aria-label={`${ability.label} 全局启用`}
                            className={`switch ${ability.enabled ? 'on' : ''}`}
                            disabled={role !== 'admin' || busy === key}
                            onClick={() => void toggleAbility(source.source_id, ability)}
                            title={role === 'admin' ? '切换项目全局状态' : '仅管理员可修改'}
                          >
                            <span />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
