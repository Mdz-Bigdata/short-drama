import { Eye, RefreshCcw, Shirt, Trash2, WandSparkles } from 'lucide-react';
import { useCallback, useEffect, useState, type ReactNode } from 'react';

import { apiRequest, apiUrl } from '../../api/client';
import { t } from '../../i18n';
import AssetImageViewer, { type AssetImageViewerAsset } from '../elements/AssetImageViewer';
import { CharacterDetailDialog } from './CharacterDetailDialog';
import { findPoster, isLook, lookCheckProblems, variantOf, type ElementItem } from '../elements/elementTypes';

interface UntimedMakeup {
  of: string;
  name: string;
  label: string;
  text: string;
}

interface GenerationJob {
  id: string;
  status: string;
  total: number;
  processed: number;
  succeeded: number;
  failed: number;
}

const POLL_MS = 1_500;

function episodesText(item: ElementItem): string {
  const variant = variantOf(item);
  const spans = variant?.spans?.length ? variant.spans : variant?.episodes ? [variant.episodes] : [];
  if (!spans.length) return '';
  // 「第 11 集起」一直穿到剧终（后端的开放区间写成 500）。
  const open = spans.find(([, last]) => last >= 500);
  const closed = spans.filter(([, last]) => last < 500);
  const text = closed.map(([first, last]) => (first === last ? `${first}` : `${first}–${last}`)).join('、');
  const when = [text && `第 ${text} 集`, open && `第 ${open[0]} 集起`].filter(Boolean).join('、');
  if (!variant?.starts) return when;
  return when === `第 ${variant.starts[0]} 集`
    ? `${when}（从第 ${variant.starts[1]} 场起）`
    : `${when}（第 ${variant.starts[0]} 集从第 ${variant.starts[1]} 场起）`;
}

// 定妆图展示板切出来的单张(后端 core/look_board)：四格全身，再三格特写；特写叫什么看出图时的版式。
const LOOK_BODY_VIEWS: ReadonlyArray<readonly [slot: string, label: string]> = [
  ['look_front', '正面全身'],
  ['look_left', '左侧面'],
  ['look_back', '背面'],
  ['look_three_quarter', '三分之四侧面'],
];
const LOOK_CLOSEUP_SLOTS = ['look_closeup_1', 'look_closeup_2', 'look_closeup_3'] as const;
const LOOK_CLOSEUP_LABELS: Record<string, readonly string[]> = {
  makeup: ['正脸胸像', '妆效部位', '腰带与配饰'],
  plain: ['正脸胸像', '腰带与配饰', '袖口或下摆'],
};
const LOOK_BOARD = 'front';

/** 这套定妆图能看的每一张：整板在前，切出来的单张跟在后面。 */
function lookPictures(look: ElementItem): Array<{ slot: string; label: string; url: string }> {
  const urls = new Map(look.files.flatMap(file => (file.media_kind === 'image' && file.url ? [[file.slot, apiUrl(file.url)] as const] : [])));
  const poster = findPoster(look)?.url;
  const board = urls.get(LOOK_BOARD) || (poster ? apiUrl(poster) : '');
  const layout = String(look.metadata?.look_layout || 'plain');
  const closeups = LOOK_CLOSEUP_LABELS[layout] || LOOK_CLOSEUP_LABELS.plain;
  const named: Array<readonly [string, string]> = [
    ...LOOK_BODY_VIEWS,
    ...LOOK_CLOSEUP_SLOTS.map((slot, index) => [slot, closeups[index]] as const),
  ];
  return [
    ...(board ? [{ slot: LOOK_BOARD, label: '整板', url: board }] : []),
    ...named.flatMap(([slot, label]) => (urls.get(slot) ? [{ slot, label, url: urls.get(slot) as string }] : [])),
  ];
}

/** 妆造签上的头像：切出来的正脸胸像，没有就用整板。 */
function lookAvatar(look: ElementItem): string {
  const face = look.files.find(file => file.slot === LOOK_CLOSEUP_SLOTS[0] && file.url);
  const poster = face?.url || findPoster(look)?.url;
  return poster ? apiUrl(poster) : '';
}

/** 画好了、但还没切成单张的旧展示板。 */
function needsSplitting(look: ElementItem): boolean {
  return Boolean(look.files.some(file => file.slot === LOOK_BOARD && file.media_kind === 'image'))
    && !look.files.some(file => file.slot === LOOK_BODY_VIEWS[0][0]);
}

/** One look in the main viewer's place: the picture on the white card, the board's single views beside it,
 *  its description behind 查看描述. Every picture opens in the zoom viewer. */
function PerformanceLookStage({
  look,
  busy,
  onRegenerate,
  onView,
  onDescribe,
}: {
  look: ElementItem;
  busy: string;
  onRegenerate: (item: ElementItem) => void;
  onView: (asset: AssetImageViewerAsset) => void;
  onDescribe: (item: ElementItem) => void;
}) {
  const pictures = lookPictures(look);
  const [picked, setPicked] = useState<{ look: string; slot: string } | null>(null);
  // 默认看正面全身(切开了的话)，不然看整板；换了一套就回到默认。
  const shown = pictures.find(item => picked?.look === look.id && item.slot === picked.slot)
    || pictures.find(item => item.slot === LOOK_BODY_VIEWS[0][0]) || pictures[0];
  const label = variantOf(look)?.label || look.name;
  const episodes = episodesText(look);
  const problems = lookCheckProblems(look);
  const working = busy === look.id;
  const drawn = pictures.length > 0;
  return (
    <section className="character-viewer character-look-viewer" aria-labelledby="character-look-title">
      <header className="character-viewer__header">
        <div>
          <span className="character-section-kicker">PERFORMANCE LOOK</span>
          <h2 id="character-look-title">{label}</h2>
        </div>
        {episodes && <small className="character-look-viewer__episodes">{episodes}</small>}
      </header>
      {Boolean(look.metadata?.needs_redraw) && <p className="character-looks__stale">{t('设定改过，这张图还是旧写法，建议重新生成')}</p>}
      {problems.length > 0 && (
        <details className="character-look-viewer__problems">
          <summary>{t('妆效核对没过 {0} 处，重新生成时会照这些问题改', [problems.length])}</summary>
          <ul>{problems.map((problem, index) => <li key={index}>{problem}</li>)}</ul>
        </details>
      )}
      <div className={`character-viewer__identity character-look-viewer__identity${pictures.length > 1 ? ' has-views' : ''}`}>
        <div
          id="character-look-stage"
          role="tabpanel"
          aria-label={label}
          className={`character-viewer__stage ${drawn ? 'is-ready' : 'is-missing'}`}
        >
          {shown ? (
            <button
              type="button"
              className="character-viewer__image-trigger"
              aria-label={t('放大查看“{0}”的{1}', [look.name, t(shown.label)])}
              onClick={() => onView({ kind: 'actor', name: `${look.name} · ${t(shown.label)}`, description: look.description || '', imageUrl: shown.url })}
            >
              <img decoding="async" src={shown.url} alt={`${look.name} ${t(shown.label)}`} />
            </button>
          ) : (
            <div className="character-look-viewer__empty">
              <Shirt size={28} aria-hidden="true" />
              <span>{t('定妆图待生成')}</span>
            </div>
          )}
          <div className="character-viewer__badge">
            <strong>{t('表演妆造')}</strong>
            {shown && <small>{t(shown.label)}</small>}
          </div>
          <button
            type="button"
            className={`character-look-viewer__regenerate${drawn ? '' : ' is-text'}`}
            onClick={() => onRegenerate(look)}
            disabled={Boolean(busy)}
            aria-label={t('重新生成“{0}”的定妆图', [look.name])}
            title={drawn ? t('重新生成') : t('生成')}
          >
            <RefreshCcw size={16} className={working ? 'is-spinning' : ''} aria-hidden="true" />
            {!drawn && <span>{working ? t('生成中…') : t('生成')}</span>}
          </button>
          <button type="button" className="character-look-viewer__describe" aria-haspopup="dialog" onClick={() => onDescribe(look)}>
            <Eye size={15} aria-hidden="true" /> {t('查看描述')}
          </button>
        </div>
        {pictures.length > 1 && (
          <div className="character-viewer__tabs" role="tablist" aria-label={t('“{0}”的单张', [label])}>
            {pictures.map(item => {
              const selected = item.slot === shown?.slot;
              return (
                <button
                  key={item.slot}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  className={`character-viewer__tab ${selected ? 'is-selected' : ''}`}
                  onClick={() => setPicked({ look: look.id, slot: item.slot })}
                >
                  <span className="character-viewer__tab-image"><img loading="lazy" decoding="async" src={item.url} alt="" /></span>
                  <span className="character-viewer__tab-copy"><strong>{t(item.label)}</strong></span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

/** 表演妆造：剧本里每套戏服和妆效，都是这名角色化好妆、穿好它的一张定妆图；分镜和视频按集数或剧情换上。
 *  顶上一排妆造签，选「设定集」看数字演员本身，选一套就在主视图位置看这套定妆图；描述收在「查看描述」里。
 *  ``children`` 拿到选中那套的主视图（选设定集时是 ``null``），由页面放进工作区中间一栏。 */
export function CharacterLooks({
  taskId,
  characterName,
  refreshToken = 0,
  onGenerated,
  baseImageUrl,
  children,
}: {
  taskId: string;
  characterName: string;
  refreshToken?: number;
  onGenerated?: () => void;
  /** 设定集签上的头像：数字演员本身的正脸。 */
  baseImageUrl?: string;
  children?: (lookStage: ReactNode | null) => ReactNode;
}) {
  const [looks, setLooks] = useState<ElementItem[]>([]);
  const [earlier, setEarlier] = useState<ElementItem[]>([]);
  const [untimed, setUntimed] = useState<UntimedMakeup[]>([]);
  const [timing, setTiming] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [viewing, setViewing] = useState<AssetImageViewerAsset | null>(null);
  // 选中的那套只对当时那名角色有效；换了角色就回到设定集。
  const [picked, setPicked] = useState<{ of: string; id: string } | null>(null);
  const [describing, setDescribing] = useState<ElementItem | null>(null);

  const load = useCallback(async () => {
    const found: ElementItem[] = [];
    for (let page = 1; ; page += 1) {
      const response = await apiRequest<{ items: ElementItem[]; total: number }>(
        `/api/elements?kind=actor&page=${page}&page_size=100&task_id=${encodeURIComponent(taskId)}`,
      );
      found.push(...response.items.filter(item => isLook(item) && !variantOf(item)?.retired));
      if (!response.items.length || page * 100 >= response.total) break;
    }
    // 早先画好的展示板还没切成单张：切一次(不调用模型)，之后每张都能单独放大看。
    for (const [index, item] of found.entries()) {
      if (!needsSplitting(item)) continue;
      try {
        found[index] = await apiRequest<ElementItem>(`/api/elements/${encodeURIComponent(item.id)}/look-views`, { method: 'POST' });
      } catch {
        // 切不开就只看整板。
      }
    }
    setLooks(found);
    // 旧项目留下的服装图和妆效图：资产库已经没有入口，在这里看得到、删得掉。
    const older = await Promise.all((['costume', 'makeup'] as const).map(kind => apiRequest<{ items: ElementItem[] }>(
      `/api/elements?kind=${kind}&page=1&page_size=100&task_id=${encodeURIComponent(taskId)}`,
    )));
    setEarlier(older.flatMap(response => response.items));
    const loose = await apiRequest<{ items?: UntimedMakeup[] }>(`/api/drama/${encodeURIComponent(taskId)}/character-looks/untimed`);
    setUntimed(Array.isArray(loose?.items) ? loose.items : []);
  }, [taskId]);

  useEffect(() => {
    let live = true;
    const handle = window.setTimeout(() => {
      load().catch(err => { if (live) setError(err instanceof Error ? err.message : t('读取表演妆造失败')); });
    }, 0);
    return () => { live = false; window.clearTimeout(handle); };
  }, [load, refreshToken]);

  const own = looks.filter(item => variantOf(item)?.of === characterName);
  const missing = looks.filter(item => !findPoster(item)).length;
  // 换了角色或这套被退掉时，回到设定集。
  const selected = picked?.of === characterName ? own.find(item => item.id === picked.id) : undefined;
  const needsAttention = (item: ElementItem) => !findPoster(item)
    || Boolean(item.metadata?.needs_redraw) || lookCheckProblems(item).length > 0;

  const generateMissing = async () => {
    if (busy) return;
    setBusy('all');
    setError('');
    setNotice(t('正在生成定妆图…'));
    try {
      let job = await apiRequest<GenerationJob>('/api/elements/generation-jobs', {
        method: 'POST',
        body: JSON.stringify({ kind: 'actor', looks: true, task_id: taskId }),
      });
      while (job.status === 'queued' || job.status === 'running') {
        setNotice(t('正在生成定妆图：{0}/{1}…', [job.processed, job.total]));
        await new Promise(resolve => window.setTimeout(resolve, POLL_MS));
        job = await apiRequest<GenerationJob>(`/api/elements/generation-jobs/${encodeURIComponent(job.id)}`);
      }
      await load();
      onGenerated?.();
      if (job.failed > 0) {
        setNotice('');
        setError(t('{0} 张定妆图生成成功，{1} 张失败；可再次点击补全失败项。', [job.succeeded, job.failed]));
      } else {
        setNotice(t('{0} 张定妆图已生成。', [job.succeeded]));
      }
    } catch (err) {
      setNotice('');
      setError(err instanceof Error ? err.message : t('定妆图生成失败'));
    } finally {
      setBusy('');
    }
  };

  const regenerate = async (item: ElementItem) => {
    if (busy) return;
    if (findPoster(item) && !window.confirm(t('重新生成“{0}”的定妆图？这是一次付费出图，新图会替换旧图。', [item.name]))) return;
    setBusy(item.id);
    setError('');
    setNotice('');
    try {
      await apiRequest(`/api/elements/${item.id}/regenerate`, {
        method: 'POST',
        body: JSON.stringify({ prompt: '' }),
      });
      await load();
      onGenerated?.();
      setNotice(t('已重新生成“{0}”的定妆图。', [item.name]));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('定妆图生成失败'));
    } finally {
      setBusy('');
    }
  };

  const saveTiming = async (item: UntimedMakeup) => {
    const words = (timing[item.name] || '').trim();
    if (busy || !words) return;
    setBusy(item.name);
    setError('');
    setNotice('');
    try {
      await apiRequest(`/api/drama/${encodeURIComponent(taskId)}/character-looks/timing`, {
        method: 'PUT',
        body: JSON.stringify({ name: item.name, episodes: words }),
      });
      await load();
      onGenerated?.();
      setNotice(t('“{0}”已合进当时穿的那身，点生成就能出图。', [item.label]));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('保存失败'));
    } finally {
      setBusy('');
    }
  };

  const removeEarlier = async (item: ElementItem) => {
    if (busy || !window.confirm(t('删除旧图“{0}”？删除后不能恢复，之后生成定妆图也不再参考它。', [item.name]))) return;
    setBusy(item.id);
    setError('');
    try {
      await apiRequest(`/api/elements/${item.id}`, { method: 'DELETE' });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('删除失败'));
    } finally {
      setBusy('');
    }
  };

  const lookStage = selected ? (
    <PerformanceLookStage
      look={selected}
      busy={busy}
      onRegenerate={item => { void regenerate(item); }}
      onView={setViewing}
      onDescribe={setDescribing}
    />
  ) : null;
  const hasExtras = untimed.some(item => item.of === characterName) || earlier.length > 0;

  return (
    <>
      <div className="character-looks__bar">
        <span className="character-looks__bar-label" title={t('按剧情给每个人物化好妆、穿好每套戏服。分镜和视频按集数或剧情自动换上，不用另管服装和化妆。')}>
          <Shirt size={15} aria-hidden="true" /> {t('表演妆造')}
        </span>
        <div className="character-looks__chips" role="tablist" aria-label={t('{0}的表演妆造', [characterName])}>
          <button
            type="button"
            role="tab"
            aria-selected={!selected}
            className={`character-looks__chip${selected ? '' : ' is-active'}`}
            title={t('数字演员设定集')}
            onClick={() => setPicked(null)}
          >
            <span className="character-looks__chip-avatar" aria-hidden="true">
              {baseImageUrl ? <img src={baseImageUrl} alt="" loading="lazy" /> : <Shirt size={14} />}
            </span>
            <span>{t('设定集')}</span>
          </button>
          {own.map(item => {
            const avatar = lookAvatar(item);
            const label = variantOf(item)?.label || item.name;
            const active = item.id === selected?.id;
            return (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={active}
                aria-controls={active ? 'character-look-stage' : undefined}
                className={`character-looks__chip${active ? ' is-active' : ''}`}
                title={[episodesText(item) || label, needsAttention(item) ? t('待处理') : ''].filter(Boolean).join(' · ')}
                onClick={() => setPicked({ of: characterName, id: item.id })}
              >
                <span className="character-looks__chip-avatar" aria-hidden="true">
                  {avatar ? <img src={avatar} alt="" loading="lazy" /> : <Shirt size={14} />}
                </span>
                <span>{label}</span>
                {needsAttention(item) && <i className="character-looks__chip-dot" aria-hidden="true" />}
              </button>
            );
          })}
        </div>
        {own.length === 0 && (
          <small className="character-looks__none">{t('剧本里没有写{0}换装或特殊妆效，全程是设定集上的样子。', [characterName])}</small>
        )}
        <div className="character-looks__actions">
          <small>{t('全剧 {0} 套，已生成 {1} 套', [looks.length, looks.length - missing])}</small>
          <button type="button" onClick={() => { void generateMissing(); }} disabled={Boolean(busy) || missing === 0}>
            <WandSparkles size={14} aria-hidden="true" /> {busy === 'all' ? t('生成中…') : t('生成缺失定妆图')}
          </button>
        </div>
      </div>
      {notice && <p className="character-looks__notice" role="status">{notice}</p>}
      {error && <p className="character-looks__error" role="alert">{error}</p>}
      {children ? children(lookStage) : lookStage}
      {hasExtras && (
      <section className="character-looks" aria-label={t('妆造补充')}>
      {untimed.some(item => item.of === characterName) && (
        <section className="character-looks__untimed" aria-label={t('还没定时间的妆效')}>
          <h3>{t('还没定时间的妆效')}</h3>
          <p>{t('剧本里看不出是哪几集。不填时，镜头提到才按文字画上；填了就合进当时穿的那身。')}</p>
          <ul>
            {untimed.filter(item => item.of === characterName).map(item => (
              <li key={item.name}>
                <strong>{item.label}</strong>
                <small>{item.text}</small>
                <form onSubmit={event => { event.preventDefault(); void saveTiming(item); }}>
                  <input
                    aria-label={t('“{0}”的时间', [item.label])}
                    placeholder={t('第9集起 / 第9-12集 / 第2集第3场起')}
                    value={timing[item.name] || ''}
                    onChange={event => setTiming(current => ({ ...current, [item.name]: event.target.value }))}
                  />
                  <button type="submit" disabled={Boolean(busy) || !(timing[item.name] || '').trim()}>{t('保存')}</button>
                </form>
              </li>
            ))}
          </ul>
        </section>
      )}
      {earlier.length > 0 && (
        <section className="character-looks__earlier" aria-label={t('之前的服装和妆效图')}>
          <h3>{t('之前的服装和妆效图')}</h3>
          <p>{t('生成定妆图时会参考同名的旧图，不会自动删除。')}</p>
          <ul>
            {earlier.map(item => {
              const poster = findPoster(item);
              const imageUrl = poster?.url ? apiUrl(poster.url) : '';
              return (
                <li key={item.id}>
                  {imageUrl
                    ? (
                      <button
                        type="button"
                        className="character-looks__thumb"
                        aria-label={t('查看旧图“{0}”', [item.name])}
                        onClick={() => setViewing({ kind: item.kind, name: item.name, description: item.description || '', imageUrl })}
                      >
                        <img src={imageUrl} alt={item.name} loading="lazy" />
                      </button>
                    )
                    : <span className="character-looks__thumb is-empty" />}
                  <small>{item.name}</small>
                  <button
                    type="button"
                    onClick={() => { void removeEarlier(item); }}
                    disabled={Boolean(busy)}
                    aria-label={t('删除旧图“{0}”', [item.name])}
                  >
                    <Trash2 size={13} aria-hidden="true" /> {t('删除')}
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}
      </section>
      )}
      {viewing && <AssetImageViewer asset={viewing} onClose={() => setViewing(null)} />}
      {describing && (
        <CharacterDetailDialog
          title={t('{0} · 妆造描述', [variantOf(describing)?.label || describing.name])}
          onClose={() => setDescribing(null)}
        >
          {episodesText(describing) && <p className="character-dialog__project-value"><strong>{t('穿戴时间')}：</strong>{episodesText(describing)}</p>}
          <p className="character-dialog__project-value">{describing.description || t('这套妆造还没有描述。')}</p>
        </CharacterDetailDialog>
      )}
    </>
  );
}
