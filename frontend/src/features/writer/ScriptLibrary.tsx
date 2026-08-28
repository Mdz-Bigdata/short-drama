import { useCallback, useEffect, useRef, useState, type ChangeEvent } from 'react';
import { ArrowLeft, BookOpen, FileText, Pencil, Plus, Save, Trash2, Upload, X } from 'lucide-react';

import {
  createScriptDocument,
  deleteScriptDocument,
  formatBytes,
  listScriptDocuments,
  readScriptDocument,
  updateScriptDocument,
  type ScriptDocument,
  type ScriptDocumentDetail,
} from './scriptLibraryApi';

const MAX_DOCUMENT_BYTES = 2 * 1024 * 1024;

async function readTextFile(file: File): Promise<string> {
  const extension = file.name.toLowerCase().match(/\.[^.]+$/)?.[0];
  if (extension !== '.md' && extension !== '.txt') {
    throw new Error('仅支持 .md 或 .txt 文件。');
  }
  if (file.size > MAX_DOCUMENT_BYTES) {
    throw new Error('文件不能超过 2 MB。');
  }
  const bytes = await file.arrayBuffer();
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes).replace(/^\uFEFF/, '');
  } catch {
    try {
      return new TextDecoder('gb18030', { fatal: true }).decode(bytes).replace(/^\uFEFF/, '');
    } catch {
      throw new Error('无法读取文件编码，请使用 UTF-8 或 GB18030。');
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
    } catch {
      if (sequence !== loadSequence.current) return;
      setError('剧本文库加载失败，请确认后端服务可用后重试。');
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
    if (added) setNotice(`已导入 ${added} 个剧本文件。`);
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
      setError('剧本文件读取失败，请稍后重试。');
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
      setNotice('剧本文件已保存。');
      await load();
    } catch {
      setError('剧本文件保存失败，本地修改仍保留在编辑器中。');
    } finally {
      setBusy('');
    }
  };

  const removeDocument = async (document: ScriptDocument) => {
    if (!window.confirm(`确定删除剧本文件“${document.name}”吗？此操作不可撤销。`)) return;
    setBusy(`delete-${document.id}`);
    setError('');
    try {
      await deleteScriptDocument(taskId, document.id);
      if (open?.id === document.id) setOpen(null);
      setNotice(`已删除“${document.name}”。`);
      await load();
    } catch {
      setError('剧本文件删除失败，请稍后重试。');
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
      setNotice(`已新建“${created.name}”。`);
      await load();
      await openDocument(created);
    } catch {
      setError('新建剧本文件失败，请稍后重试。');
    } finally {
      setBusy('');
    }
  };

  if (open) {
    return (
      <section className="script-library script-library--reader" aria-label={`剧本文件 ${open.name}`}>
        <header className="script-library__reader-bar">
          <button type="button" className="script-library__back" onClick={() => setOpen(null)}>
            <ArrowLeft aria-hidden="true" /> 映视界目录
          </button>
          <span className="script-library__reader-name">
            <FileText aria-hidden="true" />
            {editing ? (
              <input
                aria-label="剧本文件名"
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
                  <Save aria-hidden="true" /> {busy === 'save' ? '保存中' : '保存'}
                </button>
                <button
                  type="button"
                  onClick={() => { setEditing(false); setDraft(open.content); setDraftName(open.name); }}
                >
                  <X aria-hidden="true" /> 取消
                </button>
              </>
            ) : (
              <>
                <button type="button" onClick={() => setEditing(true)}><Pencil aria-hidden="true" /> 编辑</button>
                <button type="button" onClick={() => { void removeDocument(open); }}>
                  <Trash2 aria-hidden="true" /> 删除
                </button>
              </>
            )}
          </div>
        </header>
        {error && <p className="script-library__message is-error" role="alert">{error}</p>}
        {editing ? (
          <textarea
            className="script-library__editor"
            aria-label="剧本内容"
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
    <section className="script-library" aria-label="剧本文库">
      <header className="script-library__header">
        <div>
          <BookOpen aria-hidden="true" />
          <h3>已上传的映视界文件</h3>
          <span>{documents.length}</span>
        </div>
        <div className="script-library__actions">
          <label className="script-library__upload">
            <Upload aria-hidden="true" /> 导入 .md / .txt
            <input
              ref={fileInput}
              type="file"
              accept=".md,.txt,text/markdown,text/plain"
              multiple
              aria-label="导入剧本文件"
              onChange={event => { void importFiles(event); }}
            />
          </label>
          <button type="button" disabled={Boolean(busy)} onClick={() => { void createBlank(); }}>
            <Plus aria-hidden="true" /> 新建
          </button>
        </div>
      </header>

      {error && <p className="script-library__message is-error" role="alert">{error}</p>}
      {notice && !error && <p className="script-library__message" role="status">{notice}</p>}

      {loading ? (
        <p className="script-library__empty" role="status">正在加载剧本文库…</p>
      ) : documents.length === 0 ? (
        <p className="script-library__empty">还没有剧本文件，导入 .md / .txt 或新建一个开始。</p>
      ) : (
        <ul className="script-library__list">
          {documents.map((document, index) => (
            <li key={document.id}>
              <span className="script-library__index">{String(index + 1).padStart(2, '0')}</span>
              <span className="script-library__icon" aria-hidden="true"><FileText /></span>
              <span className="script-library__meta">
                <strong>{document.name}</strong>
                <small>{formatBytes(document.sizeBytes)}</small>
              </span>
              <button
                type="button"
                className="script-library__open"
                disabled={busy === `open-${document.id}`}
                onClick={() => { void openDocument(document); }}
              >
                打开 →
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
