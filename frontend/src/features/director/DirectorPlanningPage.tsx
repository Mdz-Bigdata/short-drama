import {
  Aperture,
  AudioLines,
  Camera,
  Check,
  Compass,
  Eye,
  Gauge,
  Target,
} from 'lucide-react';

import './DirectorPlanningPage.css';

const DIRECTOR_SET_IMAGE =
  'https://images.unsplash.com/photo-1576714735471-4c0d03047b4b?auto=format&fit=crop&w=1600&q=86';

const STYLE_LABELS: Record<string, string> = {
  cyberpunk: '赛博霓虹',
  realistic: '现实主义',
  cinematic: '电影级叙事',
  standard: '经典叙事',
};

const KEYWORD_CANDIDATES = [
  '强冲突', '反转', '悬念', '成长', '复仇', '救赎', '爱情', '喜剧',
  '武侠', '玄幻', '现实', '惊悚', '赛博', '家国', '逆袭', '情绪',
];

function assetToText(asset: unknown) {
  if (typeof asset === 'string') return asset.trim();
  if (asset && typeof asset === 'object') return JSON.stringify(asset, null, 2);
  return '';
}

function cleanLine(line: string) {
  return line
    .replace(/^\s*(?:#{1,6}|[-*•]+|\d+[.)、])\s*/, '')
    .replace(/[**_`【】]/g, '')
    .trim();
}

function findBrief(source: string) {
  const candidate = source
    .split('\n')
    .map(cleanLine)
    .find(line => line.length >= 24 && !/^(总导演|策划方案|项目名称|类型|主题)[:：]?/.test(line));

  if (!candidate) return '以人物欲望为引擎，用镜头完成情绪递进，让每一次反转都在观众预期之前发生。';
  return candidate.length > 156 ? `${candidate.slice(0, 156)}…` : candidate;
}

function findKeywords(source: string, directorStyle: string) {
  const matches = KEYWORD_CANDIDATES.filter(keyword => source.includes(keyword)).slice(0, 4);
  return [...new Set([STYLE_LABELS[directorStyle] || directorStyle || '电影感', ...matches, '情绪先行', '节奏控制'])].slice(0, 5);
}

export function DirectorPlanningPage({
  title,
  directorStyle,
  shotStyle,
  asset,
}: {
  title?: string;
  directorStyle?: string;
  shotStyle?: string;
  asset?: unknown;
}) {
  const source = assetToText(asset);
  const brief = findBrief(source);
  const keywords = findKeywords(source, directorStyle || '');
  const directorStyleLabel = STYLE_LABELS[directorStyle || ''] || directorStyle || '电影级叙事';
  const shotStyleLabel = STYLE_LABELS[shotStyle || ''] || shotStyle || '电影机位';

  return (
    <main className="director-board" aria-labelledby="director-page-title">
      <div className="director-board__masthead">
        <div>
          <span className="director-board__index">DIRECTION / 01</span>
          <span>总导演工作台</span>
        </div>
        <span className="director-board__status"><Check aria-hidden="true" /> {source ? '策划基线已建立' : '等待策划生成'}</span>
      </div>

      <section className="director-hero" aria-label="导演创作宣言">
        <div className="director-hero__copy">
          <p className="director-hero__eyebrow">EXECUTIVE DIRECTOR'S DESK</p>
          <h1 id="director-page-title" className="director-hero__title">
            <span>总导演</span><span>策划</span>
          </h1>
          <p className="director-hero__project">《{title || '未命名短剧'}》</p>
          <p className="director-hero__statement">{brief}</p>
          <div className="director-keywords" aria-label="导演关键词">
            {keywords.map(keyword => <span key={keyword}>{keyword}</span>)}
          </div>
        </div>

        <figure className="director-hero__visual">
          <img src={DIRECTOR_SET_IMAGE} alt="导演在片场监看拍摄画面" />
          <span className="director-hero__reticle" aria-hidden="true" />
          <div className="director-hero__frame-data" aria-hidden="true">
            <span>CAM A</span><span>24 FPS</span><span>REC ●</span>
          </div>
          <figcaption>
            SET REFERENCE · <a href="https://unsplash.com/photos/t75-VceQYq8" target="_blank" rel="noreferrer">KYLE LOFTUS / UNSPLASH</a>
          </figcaption>
        </figure>
      </section>

      <section className="director-command" aria-labelledby="creative-compass-title">
        <div className="director-command__intro">
          <Compass aria-hidden="true" />
          <p>CREATIVE COMPASS</p>
          <h2 id="creative-compass-title">创作罗盘</h2>
          <span>全片的每个部门，都从这四条导演指令出发。</span>
        </div>
        <div className="director-command__axes">
          <article><Target aria-hidden="true" /><span>叙事引擎</span><strong>欲望先行 · 冲突兑现</strong><small>开场即给目标，结尾必须留钩</small></article>
          <article><Eye aria-hidden="true" /><span>表演方向</span><strong>先收后放 · 反应优先</strong><small>关键情绪交给停顿与微表情</small></article>
          <article><Camera aria-hidden="true" /><span>镜头语法</span><strong>{shotStyleLabel}</strong><small>机位跟随权力关系持续变化</small></article>
          <article><AudioLines aria-hidden="true" /><span>声音策略</span><strong>环境先行 · 音乐后置</strong><small>反转前抽空，落点才给重音</small></article>
        </div>
      </section>

      <div className="director-analysis">
        <section className="director-rhythm" aria-labelledby="rhythm-title">
          <div className="director-section-heading">
            <div><Gauge aria-hidden="true" /><span>RHYTHM DESIGN</span></div>
            <h2 id="rhythm-title">情绪节奏曲线</h2>
          </div>
          <div className="director-rhythm__chart" role="img" aria-label="起势、增压、反转、爆点和悬念的情绪递进曲线">
            <svg viewBox="0 0 720 210" preserveAspectRatio="none" aria-hidden="true">
              <path className="director-rhythm__grid" d="M0 168H720M0 112H720M0 56H720" />
              <path className="director-rhythm__area" d="M0 172 C92 164 125 145 180 148 S274 104 338 118 S444 91 500 96 S594 25 650 42 S696 48 720 18 L720 210 L0 210Z" />
              <path className="director-rhythm__line" d="M0 172 C92 164 125 145 180 148 S274 104 338 118 S444 91 500 96 S594 25 650 42 S696 48 720 18" />
              {[['0', '172'], ['180', '148'], ['338', '118'], ['500', '96'], ['650', '42'], ['720', '18']].map(([cx, cy]) => <circle key={cx} cx={cx} cy={cy} r="5" />)}
            </svg>
            <div className="director-rhythm__labels"><span>起势</span><span>增压</span><span>第一次反转</span><span>临界点</span><span>情绪爆点</span><span>悬念收口</span></div>
          </div>
        </section>

        <aside className="director-look" aria-labelledby="look-title">
          <div className="director-section-heading">
            <div><Aperture aria-hidden="true" /><span>LOOK &amp; TONE</span></div>
            <h2 id="look-title">视听基调</h2>
          </div>
          <div className="director-look__palette" role="img" aria-label="深青、墨蓝、灰蓝和琥珀色主色板"><span /><span /><span /><span /></div>
          <dl>
            <div><dt>影调</dt><dd>{directorStyleLabel}</dd></div>
            <div><dt>画幅</dt><dd>9:16 · 竖屏沉浸</dd></div>
            <div><dt>光线</dt><dd>高反差 · 动机光</dd></div>
            <div><dt>质感</dt><dd>克制颗粒 · 深黑位</dd></div>
          </dl>
        </aside>
      </div>

      <section className="director-notes" aria-labelledby="notes-title">
        <div className="director-notes__heading">
          <div><span>DIRECTOR'S NOTE</span><h2 id="notes-title">导演手记</h2></div>
          <p>本页的视觉与执行指令，均以总导演 Agent 的原始策划为准。</p>
        </div>
        <blockquote>“{brief}”</blockquote>
        {source ? (
          <details>
            <summary>查看完整策划原文</summary>
            <pre>{source}</pre>
          </details>
        ) : (
          <p className="director-notes__empty">策划生成后，完整导演手记将在这里自动归档。</p>
        )}
      </section>
    </main>
  );
}
