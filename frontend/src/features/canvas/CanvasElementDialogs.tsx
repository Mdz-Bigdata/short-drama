import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, Loader2, Search } from 'lucide-react';

import { apiUrl } from '../../api/client';
import { t } from '../../i18n';
import {
  ELEMENT_KINDS, SAVABLE_KINDS, elementKindLabel, fetchLibraryElements, saveNodeAsElement, takeLibraryElements,
  type ElementPick, type LibraryElement, type SavedElement, type TakenElements,
} from './canvasElementsApi';
import './CanvasElementDialogs.css';

const SEARCH_DELAY_MS = 250;

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function useEscape(onClose: () => void) {
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [onClose]);
}

const pickKey = (elementId: string, fileId: string) => `${elementId}:${fileId}`;

/**
 * Take pictures from the element library onto this canvas.
 *
 * Each picked picture becomes a media node holding a *copy* (`backend/app/service/canvas_elements.py`):
 * the library's own addresses are private, so the copy is what a connected image or video node is
 * handed as its reference. All the picks of one request are one canvas version. The capability
 * follows NovaNova Studio's "My assets" picker (MIT); the implementation is this project's own.
 */
export function CanvasElementPickerDialog({ projectId, canvasId, prepare, onApplied, onClose }: {
  projectId: string;
  canvasId: string;
  /** Saves what is unsaved and answers the version to add on; rejects when the canvas cannot be saved. */
  prepare: () => Promise<number>;
  onApplied: (result: TakenElements) => void | Promise<void>;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const [kind, setKind] = useState('');
  const [typed, setTyped] = useState('');
  const [query, setQuery] = useState('');
  // What was listed, and for which filter: a list for another filter is not shown while the new one loads.
  const [loaded, setLoaded] = useState<{ key: string; items: LibraryElement[]; total: number; page: number } | null>(null);
  const [limit, setLimit] = useState(0);
  const [more, setMore] = useState(false);
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const [picked, setPicked] = useState<ReadonlyMap<string, ElementPick>>(new Map());
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');

  useEscape(onClose);
  useEffect(() => { panel.current?.focus(); }, []);

  useEffect(() => {
    const timer = setTimeout(() => setQuery(typed.trim()), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [typed]);

  const filterKey = `${kind}\n${query}`;
  const items = loaded?.key === filterKey ? loaded.items : null;
  const total = loaded?.key === filterKey ? loaded.total : 0;

  useEffect(() => {
    const abort = new AbortController();
    fetchLibraryElements(projectId, { kind, query }, abort.signal)
      .then(data => {
        setLoaded({ key: `${kind}\n${query}`, items: data.items, total: data.total, page: 1 });
        setLimit(data.max_take);
        setProblem('');
      })
      .catch(error => { if (!abort.signal.aborted) setProblem(messageOf(error, t('读取元素库失败'))); });
    return () => abort.abort();
  }, [kind, projectId, query]);

  const loadMore = async () => {
    if (more || !loaded || !items) return;
    setMore(true);
    try {
      const data = await fetchLibraryElements(projectId, { kind, query, page: loaded.page + 1 });
      const known = new Set(items.map(item => item.id));
      setLoaded({ key: filterKey, items: [...items, ...data.items.filter(item => !known.has(item.id))], total: data.total, page: data.page });
    } catch (error) {
      setProblem(messageOf(error, t('读取元素库失败')));
    } finally {
      setMore(false);
    }
  };

  const toggle = (element: LibraryElement, fileId: string) => setPicked(current => {
    const next = new Map(current);
    const key = pickKey(element.id, fileId);
    if (next.has(key)) next.delete(key); else next.set(key, { element_id: element.id, file_id: fileId });
    return next;
  });

  const picks = useMemo(() => [...picked.values()], [picked]);
  const over = limit > 0 && picks.length > limit;

  const apply = async () => {
    if (busy || !picks.length || over) return;
    setBusy(true);
    setProblem('');
    try {
      const version = await prepare();
      const result = await takeLibraryElements(projectId, canvasId, picks, version);
      await onApplied(result);
      onClose();
    } catch (error) {
      setProblem(messageOf(error, t('取用元素失败')));
      setBusy(false);
    }
  };

  const title = t('从元素库取用');
  return (
    <div className="cn-dialog-backdrop">
      <div ref={panel} className="cn-dialog ced-picker" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
        <h2>{title}</h2>
        <p className="cn-hint">{t('选中的图片会复制一份放到画布上，变成素材节点，可以连到图片或视频生成节点当参考图。元素库里之后的改动不会影响画布上的副本。')}</p>
        <div className="ced-filters">
          <label className="cn-search">
            <Search aria-hidden="true" />
            <input value={typed} onChange={event => { setTyped(event.target.value); setProblem(''); }} placeholder={t('搜索元素')} aria-label={t('搜索元素')} maxLength={120} />
          </label>
          <select value={kind} onChange={event => { setKind(event.target.value); setProblem(''); }} aria-label={t('元素类型')}>
            <option value="">{t('全部类型')}</option>
            {ELEMENT_KINDS.map(item => <option key={item} value={item}>{elementKindLabel(item)}</option>)}
          </select>
        </div>
        {!items && !problem && <p className="cn-hint">{t('读取中…')}</p>}
        {items?.length === 0 && <p className="cn-hint">{query || kind ? t('没有符合条件的元素。') : t('元素库里还没有带图片的元素。')}</p>}
        {items && items.length > 0 && (
          <ul className="ced-grid">
            {items.map(element => {
              const [main, ...rest] = element.images;
              if (!main) return null;
              const chosen = picked.has(pickKey(element.id, main.id));
              const others = rest.filter(image => picked.has(pickKey(element.id, image.id))).length;
              const expanded = open.has(element.id);
              return (
                <li key={element.id} className={chosen || others ? 'is-picked' : ''}>
                  <button
                    type="button" className="ced-card" aria-pressed={chosen}
                    aria-label={`${element.name} · ${elementKindLabel(element.kind)}`}
                    onClick={() => toggle(element, main.id)}
                  >
                    <img src={apiUrl(main.url)} alt="" loading="lazy" decoding="async" />
                    {chosen && <span className="ced-check"><Check aria-hidden="true" /></span>}
                    <strong>{element.name}</strong>
                    <small>{elementKindLabel(element.kind)}</small>
                  </button>
                  {rest.length > 0 && (
                    <button
                      type="button" className="cn-button is-quiet ced-more" aria-expanded={expanded}
                      onClick={() => setOpen(current => {
                        const next = new Set(current);
                        if (next.has(element.id)) next.delete(element.id); else next.add(element.id);
                        return next;
                      })}
                    >{others ? t('其余 {0} 张图，已选 {1} 张', [rest.length, others]) : t('其余 {0} 张图', [rest.length])}</button>
                  )}
                  {expanded && (
                    <div className="ced-views">
                      {rest.map((image, index) => (
                        <button
                          key={image.id} type="button" aria-pressed={picked.has(pickKey(element.id, image.id))}
                          aria-label={t('{0} 的第 {1} 张图', [element.name, index + 2])} title={image.slot}
                          onClick={() => toggle(element, image.id)}
                        >
                          <img src={apiUrl(image.url)} alt="" loading="lazy" decoding="async" />
                        </button>
                      ))}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {items && items.length < total && (
          <button type="button" className="cn-button" disabled={more} onClick={() => { void loadMore(); }}>
            {more && <Loader2 className="cn-spin" aria-hidden="true" />} {t('加载更多（已列出 {0} / {1}）', [items.length, total])}
          </button>
        )}
        <p className="cn-dialog__cost">{t('已选 {0} 张图片', [picks.length])}</p>
        {over && <p className="cn-error" role="alert">{t('一次最多取用 {0} 张图片，少选几张。', [limit])}</p>}
        {problem && <p className="cn-error" role="alert">{problem}</p>}
        <footer className="cn-dialog__foot">
          <button type="button" className="cn-button" onClick={onClose}>{t('取消')}</button>
          <button type="button" className="cn-button is-primary" disabled={busy || !picks.length || over} onClick={() => { void apply(); }}>
            {busy && <Loader2 className="cn-spin" aria-hidden="true" />} {t('放到画布')}
          </button>
        </footer>
      </div>
    </div>
  );
}

/**
 * Keep a node's picture in the element library as a new element: a name and a kind, nothing else.
 *
 * The server copies the picture through the library's own storage path, so the element is an
 * ordinary one from then on. After NovaNova Studio's "Save asset" (MIT); the implementation is this project's own.
 */
export function CanvasSaveElementDialog({ projectId, canvasId, nodeId, defaultName, previewUrl, prepare, onSaved, onClose }: {
  projectId: string;
  canvasId: string;
  nodeId: string;
  defaultName: string;
  /** The picture being kept, as the canvas shows it. */
  previewUrl?: string;
  /** Saves what is unsaved first: the server reads the picture from the stored canvas. */
  prepare: () => Promise<number>;
  onSaved: (element: SavedElement) => void;
  onClose: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [name, setName] = useState(defaultName);
  const [kind, setKind] = useState<string>('prop');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');

  useEscape(onClose);
  useEffect(() => { input.current?.focus(); input.current?.select(); }, []);

  const save = async () => {
    const wanted = name.trim();
    if (busy || !wanted) return;
    setBusy(true);
    setProblem('');
    try {
      await prepare();
      const element = await saveNodeAsElement(projectId, canvasId, nodeId, { name: wanted, kind });
      onSaved(element);
      onClose();
    } catch (error) {
      setProblem(messageOf(error, t('存入元素库失败')));
      setBusy(false);
    }
  };

  const title = t('存入元素库');
  return (
    <div className="cn-dialog-backdrop">
      <form
        className="cn-dialog ced-save" role="dialog" aria-modal="true" aria-label={title}
        onSubmit={event => { event.preventDefault(); void save(); }}
      >
        <h2>{title}</h2>
        <p className="cn-hint">{t('把这个节点的图片存成元素库里的一个新元素，之后可以在别的画布和项目里取用。')}</p>
        <div className="ced-save__body">
          {previewUrl && <img className="ced-save__preview" src={apiUrl(previewUrl)} alt="" />}
          <div className="ced-save__fields">
            <label className="cn-field">
              <span>{t('名称')}</span>
              <input ref={input} value={name} maxLength={160} required onChange={event => setName(event.target.value)} />
            </label>
            <label className="cn-field">
              <span>{t('类型')}</span>
              <select value={kind} onChange={event => setKind(event.target.value)}>
                {SAVABLE_KINDS.map(item => <option key={item} value={item}>{elementKindLabel(item)}</option>)}
              </select>
            </label>
          </div>
        </div>
        {kind === 'actor' && <p className="cn-hint">{t('存为演员时这张图放在正面全身位；其余身份视图到元素库里补齐后才算就绪。')}</p>}
        {problem && <p className="cn-error" role="alert">{problem}</p>}
        <footer className="cn-dialog__foot">
          <button type="button" className="cn-button" onClick={onClose}>{t('取消')}</button>
          <button type="submit" className="cn-button is-primary" disabled={busy || !name.trim()}>
            {busy && <Loader2 className="cn-spin" aria-hidden="true" />} {t('存入元素库')}
          </button>
        </footer>
      </form>
    </div>
  );
}
