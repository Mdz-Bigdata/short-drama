import { createRoot } from 'react-dom/client';
import '../src/index.css';
import { AcquisitionPanel, type AcquisitionView } from '../src/features/workbench/AcquisitionPanel';

const now = new Date('2026-10-30T15:00:00+08:00');
const iso = (hours: number) => new Date(now.getTime() + hours * 3600_000).toISOString();
const view: AcquisitionView = {
  channels: [
    { id: 'douyin', name: '抖音', color: '#1f2430', language: 'zh', autoRead: false, autoReply: false },
    { id: 'youtube', name: 'YouTube', color: '#dd3838', language: 'en', autoRead: true, autoReply: true },
    { id: 'kuaishou', name: '快手', color: '#ff6a00', language: 'zh', autoRead: false, autoReply: false },
    { id: 'xiaohongshu', name: '小红书', color: '#ff2442', language: 'zh', autoRead: false, autoReply: false },
  ],
  capabilities: { youtubeRead: true, youtubeReply: true, timezone: 'Asia/Shanghai' },
  settings: { auto_sync: true }, syncedAt: iso(-0.4), syncErrors: [],
  works: [
    { id: 'w1', platform: 'douyin', url: 'https://www.douyin.com/video/7431000000000000001', episode: 1, title: '', metrics: { views: 48210, likes: 3120 }, metrics_at: iso(-3), comments: 214 },
    { id: 'w2', platform: 'douyin', url: 'https://www.douyin.com/video/7431000000000000002', episode: 2, title: '', metrics: {}, metrics_at: null, comments: 0 },
    { id: 'w3', platform: 'youtube', url: 'https://youtu.be/dQw4w9WgXcQ', episode: 1, title: '', metrics: { views: 12800, likes: 640, comments: 96 }, metrics_at: iso(-0.4), comments: 96 },
  ],
  leads: [
    { id: 'l1', platform: 'douyin', author_name: '老周影视', intent: 'business', score: 92, judged_by: 'model', status: 'new',
      reply: '感谢关注《拭剑奴》！合作与版权事宜欢迎私信留言，我们会尽快对接。',
      dm: '您好，看到您在《拭剑奴》下关于合作的留言。方便说说您那边的方向（发行、投放还是版权）吗？我们按方向准备资料给您。',
      reply_to: '', evidence: [{ comment_id: 'c1', work_id: 'w1', text: '这剧版权谈吗？我们做海外分发', published_at: '', intent: 'business' }], send_state: '', note: '' },
    { id: 'l2', platform: 'youtube', author_name: 'Ann Lee', intent: 'watch_full', score: 78, judged_by: 'model', status: 'new',
      reply: 'Glad you like it! The full series of The Sword Wiper is on YouTube — search the title to watch.', dm: '', reply_to: 'Ugx1',
      evidence: [{ comment_id: 'Ugx1', work_id: 'w3', text: 'Where can I watch the full series?? need ep 2 now', published_at: '', intent: 'watch_full' }], send_state: '', note: '' },
    { id: 'l3', platform: 'douyin', author_name: '一只阿青', intent: 'want_more', score: 61, judged_by: 'rules', status: 'new',
      reply: '收到催更！新一集上线会第一时间更新在主页，关注不迷路～', dm: '你好，谢谢你追《拭剑奴》！下一集上线时我们会在主页第一时间更新。', reply_to: '',
      evidence: [{ comment_id: 'c3', work_id: 'w1', text: '快更新！断手之后呢', published_at: '', intent: 'want_more' }, { comment_id: 'c4', work_id: 'w1', text: '求第二集', published_at: '', intent: 'want_more' }], send_state: '', note: '' },
    { id: 'l4', platform: 'youtube', author_name: 'Marco', intent: 'question', score: 45, judged_by: 'model', status: 'new',
      reply: 'Good question — the answer is coming up in the next episodes!', dm: '', reply_to: 'Ugx9',
      evidence: [{ comment_id: 'Ugx9', work_id: 'w3', text: 'why did the master break his hand?', published_at: '', intent: 'question' }], send_state: 'unknown', send_error: '发送时连接中断（ReadTimeout），回复可能已经发出', note: '' },
    { id: 'l5', platform: 'douyin', author_name: '路过的', intent: 'complaint', score: 40, judged_by: 'rules', status: 'contacted', reply: '谢谢你直说，我们会认真改。', dm: '', reply_to: '', evidence: [{ comment_id: 'c5', work_id: 'w1', text: 'AI味有点重', published_at: '', intent: 'complaint' }], send_state: '', note: '' },
  ],
  followUps: [
    { id: 'f1', lead_id: 'l1', platform: 'douyin', author_name: '老周影视', due_at: iso(-1), reason: '对方说「明天下午聊」', context: '这剧版权谈吗？我们做海外分发', status: 'pending' },
    { id: 'f2', lead_id: 'l3', platform: 'douyin', author_name: '一只阿青', due_at: iso(40), reason: '下周', context: '快更新！断手之后呢', status: 'pending' },
  ],
  inbox: [
    { id: 'm1r', platform: 'douyin', author: '老周影视', from: '草稿', text: '您好，收到！我们明天下午把发行资料和分集表发您，您看合适吗？', at: iso(-20) },
    { id: 'm1', platform: 'douyin', author: '老周影视', from: '对方', text: '想谈海外发行，明天下午再细聊', at: iso(-20) },
  ],
  review: {
    generated_at: now.toISOString(),
    funnel: { comments: 310, leads: 5, reached: 1, replied: 0, won: 0 }, due_follow_ups: 1,
    suggestions: ['有 1 条合作意向还没联系，先处理它们', '1 位观众在问全集去哪看：回复里写清平台和剧名', '1 条跟进已到时间', '1 条 YouTube 回复发送结果不明：先到 YouTube 核对，再标记', '1 个作品还没有导入评论：从平台复制评论粘贴进来'],
    last_24h: { comments: 42, leads: 3 }, platforms: [],
  },
};
window.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
  await new Promise(resolve => setTimeout(resolve, 150));
  const result = init?.method === 'POST' && String(_input).endsWith('/send') ? { state: 'sent' } : undefined;
  return { ok: true, status: 200, json: async () => ({ ...view, result }) } as Response;
}) as typeof fetch;
createRoot(document.getElementById('root')!).render(<AcquisitionPanel taskId="t1" />);
