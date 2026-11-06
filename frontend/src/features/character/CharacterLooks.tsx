import { RefreshCcw, Shirt, Trash2, WandSparkles } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { apiRequest, apiUrl } from '../../api/client';
import { t } from '../../i18n';
import AssetImageViewer, { type AssetImageViewerAsset } from '../elements/AssetImageViewer';
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

/** 角色妆造：剧本里每套戏服和妆效，都是这名角色化好妆、穿好它的一张定妆图；分镜和视频按集数或剧情换上。 */
export function CharacterLooks({
  taskId,
  characterName,
  refreshToken = 0,
  onGenerated,
}: {
  taskId: string;
  characterName: string;
  refreshToken?: number;
  onGenerated?: () => void;
}) {
  const [looks, setLooks] = useState<ElementItem[]>([]);
  const [earlier, setEarlier] = useState<ElementItem[]>([]);
  const [untimed, setUntimed] = useState<UntimedMakeup[]>([]);
  const [timing, setTiming] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [viewing, setViewing] = useState<AssetImageViewerAsset | null>(null);

  const load = useCallback(async () => {
    const found: ElementItem[] = [];
    for (let page = 1; ; page += 1) {
      const response = await apiRequest<{ items: ElementItem[]; total: number }>(
        `/api/elements?kind=actor&page=${page}&page_size=100&task_id=${encodeURIComponent(taskId)}`,
      );
      found.push(...response.items.filter(item => isLook(item) && !variantOf(item)?.retired));
      if (!response.items.length || page * 100 >= response.total) break;
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
      load().catch(err => { if (live) setError(err instanceof Error ? err.message : t('读取角色妆造失败')); });
    }, 0);
    return () => { live = false; window.clearTimeout(handle); };
  }, [load, refreshToken]);

  const own = looks.filter(item => variantOf(item)?.of === characterName);
  const missing = looks.filter(item => !findPoster(item)).length;

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

  return (
    <section className="character-looks" aria-labelledby="character-looks-title">
      <header className="character-looks__head">
        <div>
          <h2 id="character-looks-title"><Shirt size={16} aria-hidden="true" /> {t('角色妆造')}</h2>
          <p>{t('按剧情给每个人物化好妆、穿好每套戏服。分镜和视频按集数或剧情自动换上，不用另管服装和化妆。')}</p>
        </div>
        <div className="character-looks__actions">
          <small>{t('全剧 {0} 套，已生成 {1} 套', [looks.length, looks.length - missing])}</small>
          <button type="button" onClick={() => { void generateMissing(); }} disabled={Boolean(busy) || missing === 0}>
            <WandSparkles size={14} aria-hidden="true" /> {busy === 'all' ? t('生成中…') : t('生成缺失定妆图')}
          </button>
        </div>
      </header>
      {notice && <p className="character-looks__notice" role="status">{notice}</p>}
      {error && <p className="character-looks__error" role="alert">{error}</p>}
      {own.length === 0 ? (
        <p className="character-looks__empty">
          {t('剧本里没有写{0}换装或特殊妆效，全程是设定集上的样子。', [characterName])}
        </p>
      ) : (
        <ul className="character-looks__grid" aria-label={t('{0}的定妆图', [characterName])}>
          {own.map(item => {
            const poster = findPoster(item);
            const imageUrl = poster?.url ? apiUrl(poster.url) : '';
            const label = variantOf(item)?.label || item.name;
            const episodes = episodesText(item);
            return (
              <li key={item.id} className="character-looks__card">
                {imageUrl ? (
                  <button
                    type="button"
                    className="character-looks__image"
                    aria-label={t('查看定妆图“{0}”', [item.name])}
                    onClick={() => setViewing({ kind: 'actor', name: item.name, description: item.description || '', imageUrl })}
                  >
                    <img src={imageUrl} alt={item.name} loading="lazy" />
                  </button>
                ) : (
                  <div className="character-looks__image is-empty">{t('定妆图待生成')}</div>
                )}
                <div className="character-looks__meta">
                  <strong>{label}</strong>
                  {Boolean(item.metadata?.needs_redraw) && <small className="character-looks__stale">{t('设定改过，这张图还是旧写法，建议重新生成')}</small>}
                  {lookCheckProblems(item).length > 0 && <small className="character-looks__stale">{t('妆效核对没过：{0}。建议重新生成，或把妆效写得更具体', [lookCheckProblems(item).join('；')])}</small>}
                  {episodes && <small>{episodes}</small>}
                  {item.description && <p>{item.description}</p>}
                  <button
                    type="button"
                    onClick={() => { void regenerate(item); }}
                    disabled={Boolean(busy)}
                    aria-label={t('重新生成“{0}”的定妆图', [item.name])}
                  >
                    <RefreshCcw size={13} className={busy === item.id ? 'is-spinning' : ''} aria-hidden="true" />
                    {busy === item.id ? t('生成中…') : poster ? t('重新生成') : t('生成')}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
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
      {viewing && <AssetImageViewer asset={viewing} onClose={() => setViewing(null)} />}
    </section>
  );
}
