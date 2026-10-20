import { useCallback, useEffect, useRef, useState, type ChangeEvent } from 'react';
import { ArrowDown, ArrowLeft, ArrowUp, BookOpen, FileText, Pencil, Plus, Save, Trash2, Upload, X } from 'lucide-react';

import {
  DOCUMENT_ROLE_LABELS,
  SOURCE_KIND_LABELS,
  createScriptDocument,
  deleteScriptDocument,
  describeSources,
  formatBytes,
  listScriptDocuments,
  readScriptDocument,
  updateScriptDocument,
  type ScriptDocument,
  type ScriptDocumentDetail,
  type ScriptDocumentRole,
  type ScriptSourceKind,
} from './scriptLibraryApi';
import { isUnauthorized } from '../../api/client';
import { t } from '../../i18n';

const MAX_DOCUMENT_BYTES = 2 * 1024 * 1024;

async function readTextFile(file: File): Promise<string> {
  const extension = file.name.toLowerCase().match(/\.[^.]+$/)?.[0];
  if (extension !== '.md' && extension !== '.txt') {
    throw new Error(t('仅支持 .md 或 .txt 文件。'));
  }
  if (file.size > MAX_DOCUMENT_BYTES) {
    throw new Error(t('文件不能超过 2 MB。'));
  }
  const bytes = await file.arrayBuffer();
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes).replace(/^\uFEFF/, '');
  } catch {
    try {
      return new TextDecoder('gb18030', { fatal: true }).decode(bytes).replace(/^\uFEFF/, '');
    } catch {
      throw new Error(t('无法读取文件编码，请使用 UTF-8 或 GB18030。'));
    }
  }
}

export function ScriptLibrary({ taskId }: { taskId: string }) {
  const [documents, setDocuments] = useState<ScriptDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [open, setOpen] = useState<ScriptDocumentDetail | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [draftName, setDraftName] = useState('');
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const loadSequence = useRef(0);

  const load = useCallback(async () => {
    const sequence = ++loadSequence.current;
    setLoading(true);
    try {
      const data = await listScriptDocuments(taskId);
      if (sequence !== loadSequence.current) return;
      setDocuments(data.documents);
      setError('');
    } catch (loadError) {
      if (sequence !== loadSequence.current) return;
      setError(isUnauthorized(loadError)
        ? '登录状态已过期，请重新登录后继续。'
        : '剧本文库加载失败，请确认后端服务可用后重试。');
    } finally {
      if (sequence === loadSequence.current) setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    // Defer the first fetch so the loading state is not set during render.
    const handle = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(handle);
  }, [load]);

  const importFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = [...(event.target.files || [])];
    event.target.value = '';
    await importFileList(files);
  };

  const importFileList = async (files: File[]) => {
    if (!files.length) return;
    setBusy('import');
    setError('');
    setNotice('');
    let added = 0;
    for (const file of files) {
      try {
        const content = await readTextFile(file);
        await createScriptDocument(taskId, file.name, content);
        added += 1;
      } catch (uploadError) {
        setError(uploadError instanceof Error ? uploadError.message : '文件导入失败。');
      }
    }
    setBusy('');
    if (added) setNotice(t('已导入 {0} 个剧本文件。', [added]));
    await load();
  };

  const openDocument = async (document: ScriptDocument) => {
    setBusy(`open-${document.id}`);
    setError('');
    try {
      const detail = await readScriptDocument(taskId, document.id);
      setOpen(detail);
      setDraft(detail.content);
      setDraftName(detail.name);
      setEditing(false);
    } catch {
      setError(t('剧本文件读取失败，请稍后重试。'));
    } finally {
      setBusy('');
    }
  };

  const saveDocument = async () => {
    if (!open) return;
    setBusy('save');
    setError('');
    try {
      const saved = await updateScriptDocument(taskId, open.id, { name: draftName, content: draft });
      setOpen(saved);
      setDraft(saved.content);
      setDraftName(saved.name);
      setEditing(false);
      setNotice(t('剧本文件已保存。'));
      await load();
    } catch {
      setError(t('剧本文件保存失败，本地修改仍保留在编辑器中。'));
    } finally {
      setBusy('');
    }
  };

  const removeDocument = async (document: ScriptDocument) => {
    if (!window.confirm(t('确定删除剧本文件“{0}”吗？此操作不可撤销。', [document.name]))) return;
    setBusy(`delete-${document.id}`);
    setError('');
    try {
      await deleteScriptDocument(taskId, document.id);
      if (open?.id === document.id) setOpen(null);
      setNotice(t('已删除“{0}”。', [document.name]));
      await load();
    } catch {
      setError(t('剧本文件删除失败，请稍后重试。'));
    } finally {
      setBusy('');
    }
  };

  // A file's part in the project is the person's to set; the server only guesses it from the name on import.
  const changeRole = async (document: ScriptDocument, role: ScriptDocumentRole) => {
    setBusy(`role-${document.id}`);
    setError('');
    try {
      await updateScriptDocument(taskId, document.id, { role });
      setNotice(t('“{0}”现在是{1}。{2}', [document.name, DOCUMENT_ROLE_LABELS[role], role === 'reference' ? '' : '重新执行第 2 阶段后生效。']));
      await load();
    } catch {
      setError(t('文件角色修改失败，请稍后重试。'));
    } finally {
      setBusy('');
    }
  };

  const changeKind = async (document: ScriptDocument, sourceKind: ScriptSourceKind) => {
    setBusy(`kind-${document.id}`);
    setError('');
    try {
      await updateScriptDocument(taskId, document.id, { sourceKind });
      setNotice(t('“{0}”将按{1}读取。', [document.name, SOURCE_KIND_LABELS[sourceKind]]));
      await load();
    } catch {
      setError(t('源文体裁修改失败，请稍后重试。'));
    } finally {
      setBusy('');
    }
  };

  // Own-source episodes play in library order; the two arrows set an explicit order for the pair that swaps.
  const moveEpisode = async (document: ScriptDocument, direction: -1 | 1) => {
    const own = documents.filter(item => item.role === 'episode');
    const index = own.findIndex(item => item.id === document.id);
    const other = own[index + direction];
    if (index < 0 || !other) return;
    setBusy(`move-${document.id}`);
    setError('');
    try {
      const ordered = [...own];
      ordered[index] = other;
      ordered[index + direction] = document;
      await Promise.all(ordered.map((item, position) => updateScriptDocument(taskId, item.id, { order: position })));
      await load();
    } catch {
      setError(t('调整集顺序失败，请稍后重试。'));
    } finally {
      setBusy('');
    }
  };

  const createBlank = async () => {
    setBusy('create');
    setError('');
    try {
      const created = await createScriptDocument(
        taskId,
        `新建剧本_${documents.length + 1}.txt`,
        '在这里输入剧本内容。',
      );
      setNotice(t('已新建“{0}”。', [created.name]));
      await load();
      await openDocument(created);
    } catch {
      setError(t('新建剧本文件失败，请稍后重试。'));
    } finally {
      setBusy('');
    }
  };

  if (open) {
    return (
      <section className="script-library script-library--reader" aria-label={`剧本文件 ${open.name}`}>
        <header className="script-library__reader-bar">
          <button type="button" className="script-library__back" onClick={() => setOpen(null)}>
            <ArrowLeft aria-hidden="true" /> {t('映视界目录')}
          </button>
          <span className="script-library__reader-name">
            <FileText aria-hidden="true" />
            {editing ? (
              <input
                aria-label={t('剧本文件名')}
                value={draftName}
                maxLength={255}
                onChange={event => setDraftName(event.target.value)}
              />
            ) : <strong>{open.name}</strong>}
          </span>
          <div className="script-library__reader-actions">
            {editing ? (
              <>
                <button type="button" disabled={busy === 'save'} onClick={() => { void saveDocument(); }}>
                  <Save aria-hidden="true" /> {busy === 'save' ? t('保存中') : t('保存')}
                </button>
                <button
                  type="button"
                  onClick={() => { setEditing(false); setDraft(open.content); setDraftName(open.name); }}
                >
                  <X aria-hidden="true" /> {t('取消')}
                </button>
              </>
            ) : (
              <>
                <button type="button" onClick={() => setEditing(true)}><Pencil aria-hidden="true" /> {t('编辑')}</button>
                <button type="button" onClick={() => { void removeDocument(open); }}>
                  <Trash2 aria-hidden="true" /> {t('删除')}
                </button>
              </>
            )}
          </div>
        </header>
        {error && <p className="script-library__message is-error" role="alert">{error}</p>}
        {editing ? (
          <textarea
            className="script-library__editor"
            aria-label={t('剧本内容')}
            value={draft}
            spellCheck={false}
            onChange={event => setDraft(event.target.value)}
          />
        ) : (
          <pre className="script-library__paper" tabIndex={0}>{open.content}</pre>
        )}
      </section>
    );
  }

  return (
    <section
      className={`script-library ${dragging ? 'is-dragging' : ''}`}
      aria-label={t('剧本文库')}
      onDragOver={event => { event.preventDefault(); if (!dragging) setDragging(true); }}
      onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }}
      onDrop={event => { event.preventDefault(); setDragging(false); void importFileList([...event.dataTransfer.files]); }}
    >
      <header className="script-library__header">
        <div>
          <BookOpen aria-hidden="true" />
          <h3>{t('已上传的映视界文件')}</h3>
          <span>{documents.length}</span>
          <small className="script-library__drop-hint">{t('可继续拖拽文件加入')}</small>
        </div>
        <div className="script-library__actions">
          <label className="script-library__upload">
            <Upload aria-hidden="true" /> {t('导入 .md / .txt')}
            <input
              ref={fileInput}
              type="file"
              accept=".md,.txt,text/markdown,text/plain"
              multiple
              aria-label={t('导入剧本文件')}
              onChange={event => { void importFiles(event); }}
            />
          </label>
          <button type="button" disabled={Boolean(busy)} onClick={() => { void createBlank(); }}>
            <Plus aria-hidden="true" /> {t('新建')}
          </button>
        </div>
      </header>

      {error && <p className="script-library__message is-error" role="alert">{error}</p>}
      {notice && !error && <p className="script-library__message" role="status">{notice}</p>}

      {!loading && documents.length > 0 && (
        <p className="script-library__sources" role="status">{describeSources(documents)}</p>
      )}

      {loading ? (
        <p className="script-library__empty" role="status">{t('正在加载剧本文库…')}</p>
      ) : documents.length === 0 ? (
        <p className="script-library__empty">{t('还没有剧本文件，导入 .md / .txt 或新建一个开始。')}</p>
      ) : (
        <ul className="script-library__list">
          {documents.map((document, index) => (
            <li key={document.id} className={`is-${document.role}`}>
              <span className="script-library__index">{String(index + 1).padStart(2, '0')}</span>
              <span className="script-library__icon" aria-hidden="true"><FileText /></span>
              <span className="script-library__meta">
                <strong>{document.name}</strong>
                <small>
                  {formatBytes(document.sizeBytes)}
                  {document.role === 'episode' && document.position ? ` · 第 ${document.position} 位` : ''}
                  {document.role === 'episode' && document.episode ? ` · 已排为第 ${document.episode} 集` : ''}
                </small>
              </span>
              <span className="script-library__role">
                <select
                  aria-label={`${document.name} 的角色`}
                  value={document.role}
                  disabled={Boolean(busy)}
                  onChange={event => { void changeRole(document, event.target.value as ScriptDocumentRole); }}
                >
                  {(Object.keys(DOCUMENT_ROLE_LABELS) as ScriptDocumentRole[]).map(role => (
                    <option key={role} value={role}>{DOCUMENT_ROLE_LABELS[role]}</option>
                  ))}
                </select>
                {document.role !== 'reference' && (
                  <select
                    aria-label={`${document.name} 的体裁`}
                    value={document.sourceKind || 'novel'}
                    disabled={Boolean(busy)}
                    onChange={event => { void changeKind(document, event.target.value as ScriptSourceKind); }}
                  >
                    {(Object.keys(SOURCE_KIND_LABELS) as ScriptSourceKind[]).map(kind => (
                      <option key={kind} value={kind}>{SOURCE_KIND_LABELS[kind]}</option>
                    ))}
                  </select>
                )}
                {document.role === 'episode' && (
                  <>
                    <button type="button" aria-label={`${document.name} 前移一集`} disabled={Boolean(busy)} onClick={() => { void moveEpisode(document, -1); }}><ArrowUp aria-hidden="true" /></button>
                    <button type="button" aria-label={`${document.name} 后移一集`} disabled={Boolean(busy)} onClick={() => { void moveEpisode(document, 1); }}><ArrowDown aria-hidden="true" /></button>
                  </>
                )}
              </span>
              <button
                type="button"
                className="script-library__open"
                disabled={busy === `open-${document.id}`}
                onClick={() => { void openDocument(document); }}
              >
                {t('打开 →')}
              </button>
              <button
                type="button"
                className="script-library__delete"
                aria-label={`删除 ${document.name}`}
                disabled={busy === `delete-${document.id}`}
                onClick={() => { void removeDocument(document); }}
              >
                <Trash2 aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
