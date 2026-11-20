/**
 * 连载立项：题材(可叠加)、基调、结局、出海、付费卡点。代码值、名字与说明和后端一致
 * (backend app/data/prompt/serial_brief.json, paywall_plan.json)，由 backend tests/test_serial_brief.py 对照，不要单边改。
 */
export interface SerialBrief {
  genres: string[];
  tone: string;
  ending: string;
  overseas: boolean;
  paywall: boolean;
}

export const EMPTY_SERIAL_BRIEF: SerialBrief = { genres: [], tone: '', ending: '', overseas: false, paywall: false };

export const MAX_GENRES = 3;

export const GENRES: { id: string; label: string; hint: string }[] = [
  { id: 'urban_romance', label: '都市情感', hint: '现代都市里的爱情与婚姻，误会、背叛与重新选择' },
  { id: 'ceo', label: '霸道总裁', hint: '身份悬殊的两个人被绑在一起，强势一方先动心' },
  { id: 'sweet', label: '甜宠', hint: '高糖日常，两个人一路推拉、越走越近' },
  { id: 'rebirth', label: '重生穿越', hint: '带着上一世的记忆或另一个世界的见识，把命改过来' },
  { id: 'war_god', label: '战神归来', hint: '隐姓埋名的强者回到看不起他的人中间' },
  { id: 'palace', label: '古装宫廷', hint: '深宫或权臣之家里的站队、算计与翻盘' },
  { id: 'striver', label: '励志逆袭', hint: '从谷底一步步做起来，把当初的轻视还回去' },
  { id: 'family', label: '家庭伦理', hint: '婆媳、夫妻、亲戚之间的亏欠与清算' },
  { id: 'baby', label: '萌宝', hint: '聪明的孩子把分开的父母重新拉到一起' },
  { id: 'mystery', label: '悬疑探案', hint: '一桩案子牵出一串秘密，线索、推理与反转' },
  { id: 'soft_scifi', label: '软科幻', hint: '一个近未来的设定（系统、循环、读心）落在普通人身上' },
  { id: 'apocalypse', label: '末日重生', hint: '灾变来临前回到过去，囤物资、结队、活下去' },
  { id: 'comedy', label: '喜剧', hint: '错位、误会与嘴硬，笑着把事办了' },
];

export const GENRE_CLASHES: { pair: [string, string]; say: string }[] = [
  { pair: ['comedy', 'mystery'], say: '喜剧和悬疑的气质相冲，除非你就是要这种反差' },
  { pair: ['sweet', 'apocalypse'], say: '甜宠和末日的气质相冲，除非你就是要这种反差' },
];

export const TONES: { id: string; label: string; hint: string }[] = [
  { id: 'blazing', label: '爽燃', hint: '节奏快，憋屈短、反击狠' },
  { id: 'bittersweet', label: '甜虐', hint: '甜和虐交替，虐为了更甜' },
  { id: 'funny', label: '搞笑', hint: '错位与嘴硬，轻松解压' },
  { id: 'dark', label: '暗黑', hint: '代价真实，人心复杂' },
  { id: 'warm', label: '温情', hint: '慢一点，重关系与和解' },
];

export const ENDINGS: { id: string; label: string; hint: string }[] = [
  { id: 'happy', label: '大团圆', hint: '善有善报，该在一起的在一起' },
  { id: 'open', label: '开放式', hint: '主线收住，留一扇门' },
  { id: 'twist', label: '反转式', hint: '最后一下把前面翻过来' },
  { id: 'tragic', label: '悲剧', hint: '失去了，但留下了什么' },
];

/** 付费卡点停在哪一种上。 */
export const PAYWALL_KINDS: { id: string; label: string }[] = [
  { id: 'identity', label: '身份即将揭露' },
  { id: 'life', label: '生死一线' },
  { id: 'emotion', label: '情感爆发中断' },
  { id: 'scheme', label: '反派阴谋得逞' },
  { id: 'truth', label: '真相即将大白' },
];

export function genreClashes(genres: string[]): string[] {
  return GENRE_CLASHES.filter(item => item.pair.every(id => genres.includes(id))).map(item => item.say);
}

/** 新建请求里带的那几项：没选的不带，后端按「没选」处理，提示词不变。 */
export function serialBriefPayload(brief: SerialBrief): Record<string, unknown> {
  return {
    ...(brief.genres.length ? { storyGenres: brief.genres } : {}),
    ...(brief.tone ? { storyTone: brief.tone } : {}),
    ...(brief.ending ? { endingType: brief.ending } : {}),
    ...(brief.overseas ? { overseas: true } : {}),
    ...(brief.paywall ? { paywallPlan: true } : {}),
  };
}
