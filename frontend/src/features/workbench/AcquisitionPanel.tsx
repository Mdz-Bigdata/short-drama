import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import {
  AlertTriangle, CalendarClock, Check, Copy, ExternalLink, Inbox, Link2, MessageSquareText, RefreshCw, Send, Trash2, Upload, Users,
} from 'lucide-react';

import { apiRequest } from '../../api/client';
import { t } from '../../i18n';
import './AcquisitionPanel.css';

type Intent = 'business' | 'watch_full' | 'want_more' | 'question' | 'complaint' | 'praise' | 'neutral' | 'spam';
type LeadStatus = 'new' | 'contacted' | 'replied' | 'won' | 'ignored';

interface Channel { id: string; name: string; color: string; language: string; autoRead: boolean; autoReply: boolean }
interface Work {
  id: string; platform: string; url: string; episode: number | null; title: string;
  metrics: Partial<Record<'views' | 'likes' | 'comments' | 'shares' | 'favorites', number>>; metrics_at: string | null;
  metrics_source?: string; comments: number;
}
interface Evidence { comment_id: string; work_id: string | null; text: string; published_at: string; intent: Intent }
export interface Lead {
  id: string; platform: string; author_name: string; intent: Intent; score: number; judged_by: string;
  status: LeadStatus; reply: string; dm: string; reply_to: string; evidence: Evidence[];
  send_state: '' | 'sending' | 'sent' | 'unknown'; send_error?: string; note: string;
}
interface FollowUp {
  id: string; lead_id: string; platform: string; author_name: string; due_at: string; reason: string; context: string;
  status: 'pending' | 'sent_once' | 'completed' | 'cancelled';
}
interface InboxEntry { id: string; platform: string; author: string; from: string; text: string; at: string }
interface Review {
  generated_at: string;
  funnel: { comments: number; leads: number; reached: number; replied: number; won: number };
  due_follow_ups: number; suggestions: string[];
  last_24h: { comments: number; leads: number };
  platforms: Array<{ platform: string; name: string; works: number; views: number; likes: number; comments: number; leads: number }>;
}
export interface AcquisitionView {
  channels: Channel[];
  capabilities: { youtubeRead: boolean; youtubeReply: boolean; timezone: string };
  settings: { auto_sync: boolean };
  syncedAt: string | null; syncErrors: string[];
  works: Work[]; leads: Lead[]; followUps: FollowUp[]; inbox: InboxEntry[]; review: Review;
  result?: Record<string, unknown>;
}

type Tab = 'leads' | 'works' | 'follow' | 'inbox';

const intentLabels = (): Record<Intent, string> => ({
  business: t('合作意向'), watch_full: t('求全集'), want_more: t('催更'), question: t('剧情提问'),
  complaint: t('差评投诉'), praise: t('夸赞'), neutral: t('其他'), spam: t('广告引流'),
});
const statusLabels = (): Record<LeadStatus, string> => ({
  new: t('待处理'), contacted: t('已联系'), replied: t('有回应'), won: t('已转化'), ignored: t('已忽略'),
});
const followLabels = (): Record<FollowUp['status'], string> => ({
  pending: t('待跟进'), sent_once: t('已跟进一次'), completed: t('已完成'), cancelled: t('已取消'),
});

const when = (iso: string | null | undefined) => {
  if (!iso) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString(undefined, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
};

/** 宣发 · 自动获客：已发布作品的评论 → 线索 → 由人确认的回复 → 跟进 → 复盘。 */
export function AcquisitionPanel({ taskId }: { taskId: string }) {
  const [view, setView] = useState<AcquisitionView | null>(null);
  const [tab, setTab] = useState<Tab>('leads');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const base = `/api/drama/${encodeURIComponent(taskId)}/acquisition`;

  useEffect(() => {
    let active = true;
    void apiRequest<AcquisitionView>(base)
      .then(data => { if (active) setView(data); })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : t('获客数据加载失败')); });
    return () => { active = false; };
  }, [base]);

  const act = async (key: string, path: string, method: string, body?: unknown): Promise<AcquisitionView | null> => {
    setBusy(key);
    setError('');
    setNotice('');
    try {
      const data = await apiRequest<AcquisitionView>(`${base}${path}`, {
        method, ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      setView(data);
      const sent = data.result as { state?: string; error?: string } | undefined;
      if (sent?.state === 'sent') setNotice(t('回复已发到 YouTube，这条线索移到了「已联系」。'));
      if (sent?.state === 'failed') setError(sent.error || t('发送失败'));
      return data;
    } catch (err) {
      setError(err instanceof Error ? err.message : t('操作失败'));
      return null;
    } finally {
      setBusy('');
    }
  };

  const channels = useMemo(() => new Map((view?.channels ?? []).map(item => [item.id, item])), [view?.channels]);
  const due = view?.review.due_follow_ups ?? 0;
  const openLeads = view?.leads.filter(lead => lead.status === 'new').length ?? 0;

  const sync = async () => {
    const data = await act('sync', '/sync', 'POST');
    const result = data?.result as { newComments?: number; newLeads?: number; autoTargets?: number } | undefined;
    if (result) {
      setNotice(result.autoTargets
        ? t('新评论 {0} · 新线索 {1}', [result.newComments ?? 0, result.newLeads ?? 0])
        : t('还没有能自动读取的作品：登记 YouTube 链接，或在「作品与评论」里粘贴导入'));
    }
  };

  return (
    <section className="acq-panel" aria-labelledby="acq-panel-title">
      <header className="acq-panel__head">
        <div>
          <h3 id="acq-panel-title"><Users size={18} aria-hidden="true" /> {t('自动获客')}</h3>
          <p>{t('从已发布作品的评论和私信里找出想看全集、想合作的人，回复由你确认后再发。')}</p>
        </div>
        {view && (
          <div className="acq-panel__sync">
            <label className="acq-switch">
              <input
                type="checkbox"
                checked={view.settings.auto_sync}
                disabled={busy === 'settings'}
                onChange={event => { void act('settings', '/settings', 'PATCH', { auto_sync: event.target.checked }); }}
              />
              <span>{t('定时拉取')}</span>
            </label>
            <button type="button" className="acq-button" disabled={busy === 'sync'} onClick={() => { void sync(); }}>
              <RefreshCw size={14} aria-hidden="true" className={busy === 'sync' ? 'is-spinning' : ''} />
              {busy === 'sync' ? t('同步中…') : t('立即同步')}
            </button>
            {view.syncedAt && <small>{t('上次同步')} {when(view.syncedAt)}</small>}
          </div>
        )}
      </header>

      {error && <p className="acq-panel__error" role="alert">{error}</p>}
      {notice && <p className="acq-panel__notice" role="status">{notice}</p>}
      {!view && !error && <p className="acq-panel__empty">{t('加载中…')}</p>}

      {view && (
        <>
          <div className="acq-funnel" aria-label={t('获客漏斗')}>
            {([
              [t('评论'), view.review.funnel.comments],
              [t('线索'), view.review.funnel.leads],
              [t('已联系'), view.review.funnel.reached],
              [t('有回应'), view.review.funnel.replied],
              [t('已转化'), view.review.funnel.won],
              [t('今日到期跟进'), due],
            ] as const).map(([label, value]) => (
              <div key={label} className="acq-funnel__item"><strong>{value}</strong><span>{label}</span></div>
            ))}
          </div>
          {view.review.suggestions.length > 0 && (
            <ul className="acq-suggestions" aria-label={t('今日建议')}>
              {view.review.suggestions.map(text => <li key={text}>{text}</li>)}
            </ul>
          )}
          {view.syncErrors.length > 0 && (
            <ul className="acq-sync-errors">
              {view.syncErrors.map(text => <li key={text}><AlertTriangle size={13} aria-hidden="true" />{text}</li>)}
            </ul>
          )}

          <div className="acq-tabs" role="tablist" aria-label={t('获客')}>
            {([
              ['leads', t('线索'), openLeads],
              ['works', t('作品与评论'), view.works.length],
              ['follow', t('跟进'), due],
              ['inbox', t('私信接待'), 0],
            ] as const).map(([id, label, count]) => (
              <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? 'is-active' : ''} onClick={() => setTab(id)}>
                {label}{count > 0 && <em>{count}</em>}
              </button>
            ))}
          </div>

          {tab === 'leads' && <LeadList view={view} channels={channels} busy={busy} act={act} />}
          {tab === 'works' && <WorkList view={view} channels={channels} busy={busy} act={act} />}
          {tab === 'follow' && <FollowUpList view={view} channels={channels} busy={busy} act={act} />}
          {tab === 'inbox' && <InboxDesk view={view} busy={busy} act={act} />}
        </>
      )}
    </section>
  );
}

type Act = (key: string, path: string, method: string, body?: unknown) => Promise<AcquisitionView | null>;
interface PartProps { view: AcquisitionView; channels: Map<string, Channel>; busy: string; act: Act }

function PlatformTag({ channel, fallback }: { channel?: Channel; fallback: string }) {
  return (
    <span className="acq-platform" style={{ '--platform-color': channel?.color ?? '#888' } as CSSProperties}>
      {channel?.name ?? fallback}
    </span>
  );
}

function useCopy() {
  const [copied, setCopied] = useState('');
  const copy = async (key: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      window.setTimeout(() => setCopied(current => (current === key ? '' : current)), 1500);
    } catch {
      setCopied('');
    }
  };
  return { copied, copy };
}

function LeadList({ view, channels, busy, act }: PartProps) {
  const [filter, setFilter] = useState<LeadStatus | 'all'>('new');
  const leads = view.leads.filter(lead => filter === 'all' || lead.status === filter);
  if (!view.leads.length) {
    return <p className="acq-panel__empty">{t('还没有线索。先在「作品与评论」登记已发布的作品，再同步或粘贴评论。')}</p>;
  }
  return (
    <div className="acq-leads">
      <div className="acq-filter" role="group" aria-label={t('按状态筛选')}>
        {(['new', 'contacted', 'replied', 'won', 'ignored', 'all'] as const).map(status => (
          <button key={status} type="button" aria-pressed={filter === status} onClick={() => setFilter(status)}>
            {status === 'all' ? t('全部') : statusLabels()[status]}
            <em>{status === 'all' ? view.leads.length : view.leads.filter(lead => lead.status === status).length}</em>
          </button>
        ))}
      </div>
      {leads.length === 0 && <p className="acq-panel__empty">{t('这一栏是空的。')}</p>}
      {leads.map(lead => (
        // The key remounts the card when the stored drafts change, so the editors start from them.
        <LeadCard key={`${lead.id}:${lead.reply}:${lead.dm}`} lead={lead} view={view} channel={channels.get(lead.platform)} busy={busy} act={act} />
      ))}
    </div>
  );
}

function LeadCard({ lead, view, channel, busy, act }: { lead: Lead; view: AcquisitionView; channel?: Channel; busy: string; act: Act }) {
  const [reply, setReply] = useState(lead.reply);
  const [dm, setDm] = useState(lead.dm);
  const [later, setLater] = useState('');
  const { copied, copy } = useCopy();

  const path = `/leads/${encodeURIComponent(lead.id)}`;
  const save = (field: 'reply' | 'dm', value: string) => {
    if (value !== lead[field]) void act(`${lead.id}:${field}`, path, 'PATCH', { [field]: value });
  };
  const work = view.works.find(item => item.id === lead.evidence[0]?.work_id);
  const canSend = lead.platform === 'youtube' && !!lead.reply_to && view.capabilities.youtubeReply && lead.send_state !== 'sent';
  const unclear = lead.send_state === 'unknown' || lead.send_state === 'sending';
  const status = (next: LeadStatus) => { void act(`${lead.id}:status`, path, 'PATCH', { status: next }); };

  return (
    <article className={`acq-lead intent-${lead.intent}`}>
      <header>
        <PlatformTag channel={channel} fallback={lead.platform} />
        <strong>{lead.author_name}</strong>
        <span className="acq-intent">{intentLabels()[lead.intent]}</span>
        <span className="acq-score" title={lead.judged_by === 'model' ? t('模型判定') : t('规则判定')}>{lead.score}</span>
        <span className={`acq-status is-${lead.status}`}>{statusLabels()[lead.status]}</span>
      </header>
      <ul className="acq-evidence">
        {lead.evidence.slice(0, 2).map(item => <li key={item.comment_id}>“{item.text}”</li>)}
      </ul>

      <label className="acq-field">
        <span>{lead.reply_to ? t('公开回复') : t('回复')}</span>
        <textarea rows={2} value={reply} onChange={event => setReply(event.target.value)} onBlur={() => save('reply', reply)} />
      </label>
      {(dm || lead.intent === 'business') && (
        <label className="acq-field">
          <span>{t('私信草稿')}</span>
          <textarea rows={2} value={dm} onChange={event => setDm(event.target.value)} onBlur={() => save('dm', dm)} />
        </label>
      )}

      {unclear && (
        <div className="acq-unclear" role="alert">
          <AlertTriangle size={14} aria-hidden="true" />
          <span>{lead.send_error || t('发送结果不明')}：{t('先到 YouTube 看这条评论下有没有你的回复。')}</span>
          <button type="button" onClick={() => { void act(`${lead.id}:verify`, `${path}/send-result`, 'POST', { sent: true }); }}>{t('已发出')}</button>
          <button type="button" onClick={() => { void act(`${lead.id}:verify`, `${path}/send-result`, 'POST', { sent: false }); }}>{t('没发出')}</button>
        </div>
      )}

      <div className="acq-actions">
        <button type="button" className="acq-button" onClick={() => { void copy('reply', reply); }}>
          {copied === 'reply' ? <Check size={13} aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}{t('复制回复')}
        </button>
        {dm && (
          <button type="button" className="acq-button" onClick={() => { void copy('dm', dm); }}>
            {copied === 'dm' ? <Check size={13} aria-hidden="true" /> : <MessageSquareText size={13} aria-hidden="true" />}{t('复制私信')}
          </button>
        )}
        {canSend && !unclear && (
          <button
            type="button"
            className="acq-button is-primary"
            disabled={busy === `${lead.id}:send` || !reply.trim()}
            onClick={() => { void act(`${lead.id}:send`, `${path}/send`, 'POST'); }}
          >
            <Send size={13} aria-hidden="true" />{busy === `${lead.id}:send` ? t('发送中…') : t('发到 YouTube')}
          </button>
        )}
        {lead.send_state === 'sent' && <span className="acq-sent"><Check size={13} aria-hidden="true" />{t('已在 YouTube 回复')}</span>}
        {work && (
          <a className="acq-button" href={work.url} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden="true" />{t('打开作品')}</a>
        )}
      </div>

      <div className="acq-actions is-secondary">
        {lead.status === 'new' && <button type="button" onClick={() => status('contacted')}>{t('标记已联系')}</button>}
        {lead.status !== 'replied' && lead.status !== 'new' && lead.status !== 'won' && <button type="button" onClick={() => status('replied')}>{t('对方有回应')}</button>}
        {lead.status !== 'won' && <button type="button" onClick={() => status('won')}>{t('已转化')}</button>}
        {lead.status !== 'ignored' && lead.status !== 'won' && <button type="button" onClick={() => status('ignored')}>{t('忽略')}</button>}
        {(lead.status === 'ignored' || lead.status === 'won') && <button type="button" onClick={() => status('new')}>{t('重新打开')}</button>}
        <form
          className="acq-later"
          onSubmit={event => {
            event.preventDefault();
            if (later.trim()) void act(`${lead.id}:follow`, `${path}/follow-up`, 'POST', { when: later.trim() }).then(data => { if (data) setLater(''); });
          }}
        >
          <CalendarClock size={13} aria-hidden="true" />
          <input value={later} onChange={event => setLater(event.target.value)} placeholder={t('明天 / 下周 / 11月3日 15点')} aria-label={t('跟进时间')} />
          <button type="submit" disabled={!later.trim() || busy === `${lead.id}:follow`}>{t('安排跟进')}</button>
        </form>
      </div>
    </article>
  );
}

function WorkList({ view, channels, busy, act }: PartProps) {
  const [platform, setPlatform] = useState('douyin');
  const [url, setUrl] = useState('');
  const [episode, setEpisode] = useState('');
  const [importing, setImporting] = useState('');
  const [pasted, setPasted] = useState('');

  const add = async () => {
    const data = await act('work:add', '/works', 'POST', { platform, url: url.trim(), episode: episode ? Number(episode) : null });
    if (data) { setUrl(''); setEpisode(''); }
  };
  const importNow = async (workId: string) => {
    const data = await act(`import:${workId}`, '/comments/import', 'POST', { work_id: workId, text: pasted });
    if (data) { setPasted(''); setImporting(''); }
  };

  return (
    <div className="acq-works">
      <form className="acq-add" onSubmit={event => { event.preventDefault(); if (url.trim()) void add(); }}>
        <Link2 size={15} aria-hidden="true" />
        <select value={platform} onChange={event => setPlatform(event.target.value)} aria-label={t('平台')}>
          {view.channels.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        <input value={url} onChange={event => setUrl(event.target.value)} placeholder={t('已发布作品的链接')} aria-label={t('作品链接')} />
        <input className="is-short" value={episode} onChange={event => setEpisode(event.target.value.replace(/\D/g, ''))} placeholder={t('集')} aria-label={t('第几集')} />
        <button type="submit" className="acq-button is-primary" disabled={!url.trim() || busy === 'work:add'}>{t('登记')}</button>
      </form>
      <p className="acq-hint">
        {view.capabilities.youtubeRead ? t('YouTube 的评论和数据会自动拉取。') : t('配置 YOUTUBE_API_KEY 后 YouTube 的评论和数据可自动拉取。')}
        {t('抖音、快手、小红书等平台没有对个人开放评论接口：把评论复制下来粘贴导入。')}
      </p>

      {view.works.length === 0 && <p className="acq-panel__empty">{t('还没有登记作品。')}</p>}
      {view.works.map(work => {
        const channel = channels.get(work.platform);
        return (
          <article key={work.id} className="acq-work">
            <header>
              <PlatformTag channel={channel} fallback={work.platform} />
              <strong>{work.episode ? t('第 {0} 集', [work.episode]) : work.title || t('作品')}</strong>
              <a href={work.url} target="_blank" rel="noreferrer" className="acq-work__url">{work.url}</a>
              <button type="button" className="acq-icon" aria-label={t('删除作品')} onClick={() => { void act(`work:${work.id}`, `/works/${encodeURIComponent(work.id)}`, 'DELETE'); }}>
                <Trash2 size={14} aria-hidden="true" />
              </button>
            </header>
            <dl className="acq-metrics">
              <div><dt>{t('播放')}</dt><dd>{work.metrics.views ?? '—'}</dd></div>
              <div><dt>{t('点赞')}</dt><dd>{work.metrics.likes ?? '—'}</dd></div>
              <div><dt>{t('已读评论')}</dt><dd>{work.comments}</dd></div>
              {work.metrics_at && <div><dt>{t('数据时间')}</dt><dd>{when(work.metrics_at)}</dd></div>}
            </dl>
            {!channel?.autoRead && (
              importing === work.id ? (
                <div className="acq-import">
                  <textarea
                    rows={5}
                    value={pasted}
                    onChange={event => setPasted(event.target.value)}
                    placeholder={t('每行一条：昵称：评论内容\n也可以直接粘贴从表格复制的「昵称<Tab>评论」')}
                    aria-label={t('粘贴评论')}
                  />
                  <div className="acq-actions">
                    <button type="button" className="acq-button is-primary" disabled={!pasted.trim() || busy === `import:${work.id}`} onClick={() => { void importNow(work.id); }}>
                      <Upload size={13} aria-hidden="true" />{busy === `import:${work.id}` ? t('判定中…') : t('导入并找线索')}
                    </button>
                    <button type="button" className="acq-button" onClick={() => setImporting('')}>{t('取消')}</button>
                  </div>
                </div>
              ) : (
                <button type="button" className="acq-button" onClick={() => { setImporting(work.id); setPasted(''); }}>
                  <Upload size={13} aria-hidden="true" />{t('粘贴导入评论')}
                </button>
              )
            )}
            {!channel?.autoRead && <MetricsForm work={work} busy={busy} act={act} />}
          </article>
        );
      })}
    </div>
  );
}

function MetricsForm({ work, busy, act }: { work: Work; busy: string; act: Act }) {
  const [views, setViews] = useState('');
  const [likes, setLikes] = useState('');
  const key = `metrics:${work.id}`;
  return (
    <form
      className="acq-metrics-form"
      onSubmit={event => {
        event.preventDefault();
        const body: Record<string, number> = {};
        if (views) body.views = Number(views);
        if (likes) body.likes = Number(likes);
        if (Object.keys(body).length) void act(key, `/works/${encodeURIComponent(work.id)}/metrics`, 'PATCH', body).then(data => { if (data) { setViews(''); setLikes(''); } });
      }}
    >
      <span>{t('手动补数据')}</span>
      <input value={views} onChange={event => setViews(event.target.value.replace(/\D/g, ''))} placeholder={t('播放')} aria-label={t('播放')} />
      <input value={likes} onChange={event => setLikes(event.target.value.replace(/\D/g, ''))} placeholder={t('点赞')} aria-label={t('点赞')} />
      <button type="submit" disabled={(!views && !likes) || busy === key}>{t('保存')}</button>
    </form>
  );
}

function FollowUpList({ view, channels, act }: PartProps) {
  const now = new Date(view.review.generated_at).getTime();
  const open = view.followUps.filter(item => item.status === 'pending' || item.status === 'sent_once');
  const closed = view.followUps.filter(item => item.status === 'completed' || item.status === 'cancelled').slice(0, 10);
  if (!view.followUps.length) {
    return <p className="acq-panel__empty">{t('没有跟进。在线索上写「明天」「下周」就能排一条；私信里对方说改天再聊也会自动排上。')}</p>;
  }
  const row = (item: FollowUp) => {
    const isDue = (item.status === 'pending' || item.status === 'sent_once') && new Date(item.due_at).getTime() <= now;
    const path = `/follow-ups/${encodeURIComponent(item.id)}`;
    return (
      <li key={item.id} className={`acq-follow${isDue ? ' is-due' : ''}`}>
        <div className="acq-follow__when"><CalendarClock size={14} aria-hidden="true" />{when(item.due_at)}{isDue && <em>{t('到期')}</em>}</div>
        <div className="acq-follow__who">
          <PlatformTag channel={channels.get(item.platform)} fallback={item.platform} />
          <strong>{item.author_name}</strong>
          <span>{item.reason}</span>
        </div>
        {item.context && <p>“{item.context}”</p>}
        <div className="acq-actions is-secondary">
          <span className={`acq-status is-${item.status}`}>{followLabels()[item.status]}</span>
          {item.status === 'pending' && <button type="button" onClick={() => { void act(`fu:${item.id}`, path, 'PATCH', { status: 'sent_once' }); }}>{t('已跟进一次')}</button>}
          {(item.status === 'pending' || item.status === 'sent_once') && (
            <>
              <button type="button" onClick={() => { void act(`fu:${item.id}`, path, 'PATCH', { status: 'completed' }); }}>{t('完成')}</button>
              <button type="button" onClick={() => { void act(`fu:${item.id}`, path, 'PATCH', { status: 'cancelled' }); }}>{t('取消')}</button>
            </>
          )}
        </div>
      </li>
    );
  };
  return (
    <div className="acq-follows">
      <p className="acq-hint">{t('时间按 {0} 计。到期提醒在这里和复盘里出现，消息由你发出。', [view.capabilities.timezone])}</p>
      <ul>{open.map(row)}</ul>
      {closed.length > 0 && <details><summary>{t('已结束')} ({closed.length})</summary><ul>{closed.map(row)}</ul></details>}
    </div>
  );
}

function InboxDesk({ view, busy, act }: Omit<PartProps, 'channels'>) {
  const [platform, setPlatform] = useState('douyin');
  const [author, setAuthor] = useState('');
  const [text, setText] = useState('');
  const { copied, copy } = useCopy();
  const result = view.result as { reply?: string; intent?: Intent; followUp?: FollowUp | null } | undefined;

  const answer = async () => {
    const data = await act('inbox', '/inbox', 'POST', { platform, author: author.trim(), text: text.trim() });
    if (data) setText('');
  };

  return (
    <div className="acq-inbox">
      <form onSubmit={event => { event.preventDefault(); if (text.trim()) void answer(); }}>
        <div className="acq-add">
          <Inbox size={15} aria-hidden="true" />
          <select value={platform} onChange={event => setPlatform(event.target.value)} aria-label={t('平台')}>
            {view.channels.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <input value={author} onChange={event => setAuthor(event.target.value)} placeholder={t('对方昵称')} aria-label={t('对方昵称')} />
        </div>
        <textarea rows={3} value={text} onChange={event => setText(event.target.value)} placeholder={t('粘贴对方发来的私信')} aria-label={t('对方的消息')} />
        <button type="submit" className="acq-button is-primary" disabled={!text.trim() || busy === 'inbox'}>
          <MessageSquareText size={14} aria-hidden="true" />{busy === 'inbox' ? t('生成中…') : t('生成回复')}
        </button>
      </form>
      {result?.reply && (
        <div className="acq-answer">
          <header>
            {result.intent && <span className="acq-intent">{intentLabels()[result.intent]}</span>}
            <button type="button" className="acq-button" onClick={() => { void copy('answer', result.reply ?? ''); }}>
              {copied === 'answer' ? <Check size={13} aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}{t('复制回复')}
            </button>
          </header>
          <p>{result.reply}</p>
          {result.followUp && <small><CalendarClock size={13} aria-hidden="true" />{t('已排跟进')} {when(result.followUp.due_at)}</small>}
        </div>
      )}
      {view.inbox.length > 0 && (
        <ul className="acq-history" aria-label={t('最近往来')}>
          {view.inbox.map(item => (
            <li key={item.id} className={item.from === '草稿' ? 'is-draft' : ''}>
              <span>{item.from === '草稿' ? t('草稿') : item.author}</span>
              <p>{item.text}</p>
              <small>{when(item.at)}</small>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
