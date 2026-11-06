import { useCallback, useEffect, useState } from 'react';
import { Clapperboard, Download, Hand, MessageSquare, RefreshCw, Send, Upload } from 'lucide-react';

import {
  askPrevizAgent, attachPreviz, describeOperation, fetchBlenderStatus, fetchPreviz, pullFromBlender, pushToBlender,
  renderPreviz, savePrevizOptions, type BlenderStatus, type PrevizView, type PullResult,
} from '../blenderApi';
import { apiUrl } from '../../../api/client';

interface Props {
  taskId: string;
  sceneId: string;
  shotIds: number[];
  planRevision: number;
  editable: boolean;
  /** Something outside the desk changed the plan (the agent, a pull from Blender): read it again. */
  onPlanChanged: () => void | Promise<void>;
  onSelectShot: (shotId: number) => void;
}

interface ChatLine {
  from: 'you' | 'agent';
  text: string;
  tools?: string[];
}

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

const SIZES = [{ value: 960, label: '试看 960' }, { value: 1920, label: '交付 1920' }];

export function BlenderPanel({ taskId, sceneId, shotIds, planRevision, editable, onPlanChanged, onSelectShot }: Props) {
  const [status, setStatus] = useState<BlenderStatus | null>(null);
  const [view, setView] = useState<PrevizView | null>(null);
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [longEdge, setLongEdge] = useState(960);
  const [pulled, setPulled] = useState<PullResult | null>(null);
  const [chat, setChat] = useState<ChatLine[]>([]);
  const [draft, setDraft] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [nextStatus, nextView] = await Promise.all([fetchBlenderStatus(), fetchPreviz(taskId, sceneId)]);
      setStatus(nextStatus);
      setView(nextView);
    } catch (err) {
      setError(messageOf(err, '读取 Blender 预演失败'));
    }
  }, [sceneId, taskId]);

  useEffect(() => {
    const handle = window.setTimeout(() => { void refresh(); }, 0);
    return () => window.clearTimeout(handle);
  }, [refresh, planRevision]);

  const run = async (label: string, action: () => Promise<string>) => {
    if (busy) return;
    setBusy(label);
    setError('');
    setNotice('');
    try {
      setNotice(await action());
      await refresh();
    } catch (err) {
      setError(messageOf(err, `${label}失败`));
    } finally {
      setBusy('');
    }
  };

  const latest = view?.latest ?? null;
  const handheld = new Set(view?.options.handheld_shots ?? []);

  const render = () => run('渲染', async () => {
    const result = await renderPreviz(taskId, sceneId, longEdge);
    return `已渲染 ${result.segments.length} 镜、${(result.frames / result.fps).toFixed(1)} 秒${result.reused ? '（与上次相同，直接复用）' : ''}${result.live ? '；打开的 Blender 已同步' : ''}`;
  });

  const attach = () => run('交给分镜', async () => {
    const result = await attachPreviz(taskId, sceneId);
    const failed = result.failed.length ? `；${result.failed.map(item => `第 ${item.shot_id} 镜：${item.error}`).join('；')}` : '';
    return `已把 ${result.attached.length} 镜的预演登记为运动参考视频，第 5 阶段出片时由它管机位与切点${failed}`;
  });

  const push = () => run('推到 Blender', async () => {
    const result = await pushToBlender(taskId, sceneId);
    return `Blender 里已重建：${result.proxies.length} 个代理、${result.cameras.length} 台摄影机`;
  });

  const pull = (apply: boolean) => run(apply ? '同步回方案' : '读取 Blender', async () => {
    const result = await pullFromBlender(taskId, sceneId, apply);
    setPulled(apply ? null : result);
    if (apply) {
      await onPlanChanged();
      return result.applied ? `已按 Blender 里的位置更新方案（版本 ${result.revision}）` : 'Blender 里没有需要同步的改动';
    }
    return result.operations.length ? `Blender 里改了 ${result.operations.length} 处，确认后写回方案` : 'Blender 里的站位与机位和方案一致';
  });

  const toggleHandheld = (shotId: number) => run('设置手持', async () => {
    const next = new Set(handheld);
    if (next.has(shotId)) next.delete(shotId); else next.add(shotId);
    await savePrevizOptions(taskId, sceneId, { handheld_shots: [...next].sort((a, b) => a - b) });
    return `第 ${shotId} 镜${next.has(shotId) ? '改为真实手持（低频摆动 + 微震）' : '取消手持'}，重新渲染后生效`;
  });

  const send = async () => {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft('');
    setChat(lines => [...lines, { from: 'you', text }]);
    setBusy('对话');
    setError('');
    try {
      const answer = await askPrevizAgent(taskId, sceneId, text);
      const tools = (answer.tool_calls ?? []).map(call => `${call.tool}${call.result?.ok === false ? '（失败）' : ''}`);
      setChat(lines => [...lines, { from: 'agent', text: answer.reply || '已完成。', tools }]);
      if ((answer.tool_calls ?? []).some(call => ['edit_stage', 'repair_stage', 'pull_from_blender'].includes(call.tool))) await onPlanChanged();
      await refresh();
    } catch (err) {
      setChat(lines => [...lines, { from: 'agent', text: messageOf(err, '助手暂时不可用') }]);
    } finally {
      setBusy('');
    }
  };

  return (
    <section className="desk-blender" aria-label="Blender 预演">
      <p className="desk-blender__status" role="status">
        {status === null ? '正在检查本机 Blender…'
          : status.blender_found ? `本机 Blender ${status.blender_version}` : '本机没有找到 Blender，请安装 4.2 以上版本，或在后端 .env 设置 BLENDER_BIN'}
        {status?.blender_found && (status.live_connected ? ' · 打开的 Blender 已连接' : ' · 实时同步未连接')}
      </p>
      {status && !status.live_connected && (
        <details className="desk-blender__help">
          <summary>在 Blender 里实时看（可选）</summary>
          <ol>
            <li><a href={apiUrl(status.addon_download)} download><Download aria-hidden="true" /> 下载桥接插件</a></li>
            <li>Blender › 编辑 › 偏好设置 › 插件 › 从磁盘安装，选这个 zip 并勾选启用</li>
            <li>3D 视口按 N › 「短剧预演」面板 › 开始连接（端口 {status.live_port}）</li>
          </ol>
        </details>
      )}

      <div className="desk-blender__actions">
        <label className="desk-field">
          <span>画质</span>
          <select value={longEdge} onChange={event => setLongEdge(Number(event.target.value))} disabled={Boolean(busy)}>
            {SIZES.map(size => <option key={size.value} value={size.value}>{size.label}</option>)}
          </select>
        </label>
        <button type="button" className="desk-button is-primary" disabled={Boolean(busy) || !status?.blender_found} onClick={() => { void render(); }}>
          <Clapperboard aria-hidden="true" /> {busy === '渲染' ? '渲染中…' : '用 Blender 渲染预演'}
        </button>
        <button type="button" className="desk-button" disabled={Boolean(busy) || !status?.live_connected} onClick={() => { void push(); }}>
          <Upload aria-hidden="true" /> 推到 Blender
        </button>
        <button type="button" className="desk-button" disabled={Boolean(busy) || !status?.live_connected || !editable} onClick={() => { void pull(false); }}>
          <RefreshCw aria-hidden="true" /> 读取 Blender 里的改动
        </button>
      </div>

      {pulled && pulled.operations.length > 0 && (
        <div className="desk-blender__pull" role="group" aria-label="Blender 里的改动">
          <ul>{pulled.operations.map((operation, index) => <li key={index}>{describeOperation(operation)}</li>)}</ul>
          <button type="button" className="desk-button is-primary" disabled={Boolean(busy)} onClick={() => { void pull(true); }}>写回方案</button>
          <button type="button" className="desk-button" onClick={() => setPulled(null)}>不要</button>
        </div>
      )}

      {notice && <p className="desk-blender__notice" role="status">{notice}</p>}
      {error && <p className="desk-inspector__error" role="alert">{error}</p>}

      {latest ? (
        <div className="desk-blender__result">
          {view?.stale && <p className="desk-badge is-stale" role="note">站位或机位在这次渲染之后改过了，请重新渲染</p>}
          <video key={latest.video_url} src={apiUrl(latest.video_url)} controls playsInline aria-label="Blender 白模预演" />
          <ul className="desk-blender__shots">
            {latest.segments.map(segment => {
              const still = latest.stills.find(item => item.shot_id === segment.shot_id);
              return (
                <li key={segment.shot_id}>
                  <button type="button" className="desk-blender__thumb" aria-label={`选中第 ${segment.shot_id} 镜`} onClick={() => onSelectShot(segment.shot_id)}>
                    {still && <img src={apiUrl(still.url)} alt="" />}
                  </button>
                  <span>第 {segment.shot_id} 镜 · {segment.seconds}s · 帧 {segment.start}–{segment.end}</span>
                  <button
                    type="button"
                    className={`desk-blender__hand ${handheld.has(segment.shot_id) ? 'is-on' : ''}`}
                    aria-pressed={handheld.has(segment.shot_id)}
                    aria-label={`第 ${segment.shot_id} 镜真实手持`}
                    disabled={Boolean(busy)}
                    onClick={() => { void toggleHandheld(segment.shot_id); }}
                  >
                    <Hand aria-hidden="true" />
                  </button>
                </li>
              );
            })}
          </ul>
          <div className="desk-blender__legend">
            {latest.proxies.filter(proxy => proxy.kind !== 'extra').map(proxy => (
              <span key={proxy.id}><i style={{ background: proxy.color }} aria-hidden="true" />{proxy.name}</span>
            ))}
          </div>
          <button type="button" className="desk-button is-primary" disabled={Boolean(busy) || Boolean(view?.stale) || !editable} onClick={() => { void attach(); }}>
            {busy === '交给分镜' ? '登记中…' : '交给分镜当运动参考'}
          </button>
          <p className="desk-blender__note">预演视频只管机位、切点、时间与走位；人物长相、服装与场景仍由设定集和场景图决定。</p>
        </div>
      ) : (
        <p className="desk-inspector__empty">还没有渲染过。点「用 Blender 渲染预演」，或在下面直接说要怎么拍。</p>
      )}

      <div className="desk-blender__chat" aria-label="用对话操作预演">
        <h3><MessageSquare aria-hidden="true" /> 用对话操作预演</h3>
        <ol className="desk-blender__log" aria-live="polite">
          {chat.map((line, index) => (
            <li key={index} className={`is-${line.from}`}>
              <p>{line.text}</p>
              {line.tools && line.tools.length > 0 && <small>调用：{line.tools.join(' → ')}</small>}
            </li>
          ))}
        </ol>
        <form onSubmit={event => { event.preventDefault(); void send(); }}>
          <textarea
            value={draft}
            rows={2}
            placeholder={shotIds.length ? '例如：第 2 镜让陆昭往左走两步、镜头改成缓推，然后渲染给我看' : '这一场还没有镜头'}
            aria-label="对预演说的话"
            disabled={!editable}
            onChange={event => setDraft(event.target.value)}
            onKeyDown={event => { if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); void send(); } }}
          />
          <button type="submit" className="desk-button is-primary" disabled={!draft.trim() || Boolean(busy) || !editable} aria-label="发送">
            <Send aria-hidden="true" /> {busy === '对话' ? '处理中…' : '发送'}
          </button>
        </form>
      </div>
    </section>
  );
}
