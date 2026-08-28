import { ChevronLeft, ChevronRight, Eye, FileUp, Pencil, Save, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react';

import { MarkdownBlocks } from './MarkdownDocument';
import { paginateMarkdown } from './markdownParser';

function paginationItems(total: number, current: number): Array<number | 'ellipsis-left' | 'ellipsis-right'> {
  if (total <= 7) return Array.from({ length: total }, (_, index) => index);
  const items: Array<number | 'ellipsis-left' | 'ellipsis-right'> = [0];
  if (current > 3) items.push('ellipsis-left');
  const start = Math.max(1, Math.min(current - 1, total - 4));
  const end = Math.min(total - 2, Math.max(current + 1, 3));
  for (let index = start; index <= end; index += 1) items.push(index);
  if (current < total - 4) items.push('ellipsis-right');
  items.push(total - 1);
  return items;
}

const MAX_SCRIPT_BYTES = 2 * 1024 * 1024;

function defaultFileName(title: string) {
  const safeTitle = title.replace(/[\\/:*?"<>|]/g, '-').trim().slice(0, 120) || 'screenplay';
  return `${safeTitle}.md`;
}

function normalizeSourceHash(value?: string | void) {
  const normalized = String(value || '').trim().toLowerCase();
  return /^[a-f\d]{64}$/.test(normalized) ? normalized : '';
}

function plainTextPages(source: string, maxCharacters = 2200) {
  if (!source) return [''];
  const pages: string[] = [];
  let start = 0;
  const minimumBreak = Math.floor(maxCharacters * 0.55);
  while (start < source.length) {
    let end = Math.min(source.length, start + maxCharacters);
    if (end < source.length) {
      const newline = source.lastIndexOf('\n', end);
      if (newline >= start + minimumBreak) end = newline + 1;
    }
    pages.push(source.slice(start, end));
    start = end;
  }
  return pages;
}

async function readScriptFile(file: File) {
  const extension = file.name.toLowerCase().match(/\.[^.]+$/)?.[0];
  if (extension !== '.md' && extension !== '.txt') {
    throw new Error('仅支持 .md 或 .txt 文件。');
  }
  if (file.size > MAX_SCRIPT_BYTES) {
    throw new Error('文件不能超过 2 MB。');
  }
  const bytes = await file.arrayBuffer();
  let content: string;
  try {
    content = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    try {
      content = new TextDecoder('gb18030', { fatal: true }).decode(bytes);
    } catch {
      throw new Error('无法读取文件编码，请使用 UTF-8 或 GB18030。');
    }
  }
  if (content.includes('\u0000')) throw new Error('文件包含不支持的空字符。');
  for (const character of content) {
    if (character.charCodeAt(0) < 32 && !'\n\r\t'.includes(character)) {
      throw new Error('文件包含不支持的控制字符。');
    }
  }
  return content.replace(/^\uFEFF/, '');
}

export function ScreenplayReader({
  title,
  script,
  initialFileName,
  sourceHash,
  onClose,
  onSave,
}: {
  title: string;
  script: string;
  initialFileName?: string;
  sourceHash?: string;
  onClose: () => void;
  onSave?: (
    content: string,
    fileName: string,
    baseSourceHash: string,
  ) => string | void | Promise<string | void>;
}) {
  const incomingFileName = initialFileName?.trim() || defaultFileName(title);
  const incomingSourceHash = normalizeSourceHash(sourceHash);
  const [draftState, setDraftState] = useState({
    source: script,
    sourceFileName: incomingFileName,
    sourceHash: incomingSourceHash,
    baseSourceHash: incomingSourceHash,
    draft: script,
    fileName: incomingFileName,
    saved: script,
    savedFileName: incomingFileName,
  });
  const [mode, setMode] = useState<'preview' | 'edit'>(script ? 'preview' : 'edit');
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved'>('idle');
  const [saveInFlight, setSaveInFlight] = useState(false);
  const [error, setError] = useState('');
  const hasLocalChanges = draftState.draft !== draftState.saved
    || draftState.fileName !== draftState.savedFileName;
  const sourceChanged = draftState.source !== script
    || draftState.sourceFileName !== incomingFileName
    || draftState.sourceHash !== incomingSourceHash;
  const activeSource = sourceChanged && !hasLocalChanges ? script : draftState.source;
  const activeSourceFileName = sourceChanged && !hasLocalChanges
    ? incomingFileName
    : draftState.sourceFileName;
  const activeSourceHash = sourceChanged && !hasLocalChanges
    ? incomingSourceHash
    : draftState.sourceHash;
  const draft = sourceChanged && !hasLocalChanges ? script : draftState.draft;
  const fileName = sourceChanged && !hasLocalChanges ? incomingFileName : draftState.fileName;
  const baseSourceHash = sourceChanged && !hasLocalChanges
    ? incomingSourceHash
    : draftState.baseSourceHash;
  const lastSavedDraft = sourceChanged && !hasLocalChanges ? script : draftState.saved;
  const lastSavedFileName = sourceChanged && !hasLocalChanges
    ? incomingFileName
    : draftState.savedFileName;
  const isPlainText = fileName.toLowerCase().endsWith('.txt');
  const previewSource = mode === 'preview' ? draft : '';
  const markdownPages = useMemo(() => paginateMarkdown(previewSource), [previewSource]);
  const textPages = useMemo(() => plainTextPages(previewSource), [previewSource]);
  const pageCount = isPlainText ? textPages.length : markdownPages.length;
  const pageKey = `${fileName}\u0000${draft}`;
  const [pageSelection, setPageSelection] = useState({ script: pageKey, index: 0 });
  const pageIndex = pageSelection.script === pageKey ? pageSelection.index : 0;
  const activePageIndex = Math.min(pageIndex, pageCount - 1);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const pageRef = useRef<HTMLElement>(null);
  const latestDraftRef = useRef(draft);
  const latestFileNameRef = useRef(fileName);
  const saveInFlightRef = useRef(false);
  const fileReadSequenceRef = useRef(0);
  latestDraftRef.current = draft;
  latestFileNameRef.current = fileName;
  const isDirty = draft !== lastSavedDraft || fileName !== lastSavedFileName;

  const goToPage = (nextPage: number) => {
    setPageSelection({ script: pageKey, index: Math.max(0, Math.min(pageCount - 1, nextPage)) });
  };

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    return () => {
      fileReadSequenceRef.current += 1;
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus();
    };
  }, []);

  useEffect(() => {
    pageRef.current?.scrollTo?.({ top: 0 });
  }, [activePageIndex]);

  const requestClose = () => {
    if (isDirty && !window.confirm('当前剧本有未保存修改，确定放弃并关闭吗？')) return;
    onClose();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      if (isDirty) void handleSave();
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      requestClose();
      return;
    }
    const isFormField = event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLInputElement;
    if ((isFormField || mode === 'edit') && event.key !== 'Tab') return;
    if (event.key === 'ArrowLeft' || event.key === 'PageUp') {
      event.preventDefault();
      goToPage(activePageIndex - 1);
      return;
    }
    if (event.key === 'ArrowRight' || event.key === 'PageDown') {
      event.preventDefault();
      goToPage(activePageIndex + 1);
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
    ) || []);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    const readSequence = ++fileReadSequenceRef.current;
    setError('');
    setSaveState('idle');
    try {
      const content = await readScriptFile(file);
      if (readSequence !== fileReadSequenceRef.current) return;
      latestDraftRef.current = content;
      latestFileNameRef.current = file.name;
      setDraftState({
        source: activeSource,
        sourceFileName: activeSourceFileName,
        sourceHash: activeSourceHash,
        baseSourceHash,
        draft: content,
        fileName: file.name,
        saved: lastSavedDraft,
        savedFileName: lastSavedFileName,
      });
      setMode('edit');
      setPageSelection({ script: `${file.name}\u0000${content}`, index: 0 });
    } catch (loadError) {
      if (readSequence !== fileReadSequenceRef.current) return;
      setError(loadError instanceof Error ? loadError.message : '文件读取失败。');
    }
  };

  async function handleSave() {
    if (!onSave || saveInFlightRef.current || !isDirty) return;
    const submittedDraft = draft;
    const submittedFileName = fileName;
    const submittedBaseSourceHash = baseSourceHash;
    setError('');
    if (!draft.trim()) {
      setError('剧本内容不能为空。');
      setSaveState('idle');
      return;
    }
    if (new TextEncoder().encode(draft).byteLength > MAX_SCRIPT_BYTES) {
      setError('剧本内容不能超过 2 MB。');
      setSaveState('idle');
      return;
    }
    saveInFlightRef.current = true;
    setSaveInFlight(true);
    setSaveState('saving');
    try {
      const savedSourceHash = normalizeSourceHash(await onSave(
        submittedDraft,
        submittedFileName,
        submittedBaseSourceHash,
      )) || submittedBaseSourceHash;
      setDraftState(current => ({
        ...current,
        sourceHash: savedSourceHash,
        baseSourceHash: savedSourceHash,
        saved: submittedDraft,
        savedFileName: submittedFileName,
      }));
      const stillCurrent = latestDraftRef.current === submittedDraft
        && latestFileNameRef.current === submittedFileName;
      setSaveState(stillCurrent ? 'saved' : 'idle');
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : '剧本保存失败，请稍后重试。');
      setSaveState('idle');
    } finally {
      saveInFlightRef.current = false;
      setSaveInFlight(false);
    }
  }

  return (
    <div
      className="writer-reader-backdrop"
      onMouseDown={event => { if (event.target === event.currentTarget) requestClose(); }}
      onKeyDown={handleKeyDown}
    >
      <div
        ref={dialogRef}
        className="writer-reader"
        role="dialog"
        aria-modal="true"
        aria-labelledby="writer-reader-title"
      >
        <header className="writer-reader__header">
          <div>
            <span>SCREENPLAY ARCHIVE / {mode === 'edit' ? 'EDITOR' : 'PAGED READER'}</span>
            <h2 id="writer-reader-title">{title} · 完整剧本</h2>
            <small>{fileName}{isDirty ? ' · 未保存' : ''}</small>
          </div>
          <div className="writer-reader__tools">
            <label className="writer-reader__file-button">
              <FileUp aria-hidden="true" /> 打开文件
              <input
                type="file"
                accept=".md,.txt,text/markdown,text/plain"
                aria-label="打开 Markdown 或文本文件"
                onChange={handleFileChange}
              />
            </label>
            <button
              type="button"
              aria-label={mode === 'edit' ? '预览剧本' : '编辑剧本'}
              onClick={() => {
                setError('');
                setMode(current => current === 'edit' ? 'preview' : 'edit');
              }}
            >
              {mode === 'edit' ? <Eye aria-hidden="true" /> : <Pencil aria-hidden="true" />}
              {mode === 'edit' ? '预览' : '编辑'}
            </button>
            <button
              className="is-primary"
              type="button"
              aria-label="保存剧本"
              disabled={!onSave || saveInFlight || !isDirty}
              onClick={() => { void handleSave(); }}
            >
              <Save aria-hidden="true" /> {saveInFlight ? '保存中' : '保存'}
            </button>
            <button ref={closeRef} className="writer-reader__close" type="button" aria-label="关闭剧本阅读器" onClick={requestClose}><X aria-hidden="true" /></button>
          </div>
        </header>

        <div className="writer-reader__message-slot">
          {error && <p className="writer-reader__message is-error" role="alert">{error}</p>}
          {!error && saveState === 'saved' && <p className="writer-reader__message is-success" role="status" aria-live="polite">已保存</p>}
        </div>

        {mode === 'edit' ? (
          <div className="writer-reader__editor">
            <label htmlFor="writer-script-editor">剧本内容</label>
            <textarea
              id="writer-script-editor"
              aria-label="剧本内容"
              value={draft}
              spellCheck={false}
              onChange={event => {
                latestDraftRef.current = event.target.value;
                latestFileNameRef.current = fileName;
                setDraftState({
                  source: activeSource,
                  sourceFileName: activeSourceFileName,
                  sourceHash: activeSourceHash,
                  baseSourceHash,
                  draft: event.target.value,
                  fileName,
                  saved: lastSavedDraft,
                  savedFileName: lastSavedFileName,
                });
                setError('');
                setSaveState('idle');
              }}
              placeholder="在这里输入剧本，或打开 .md / .txt 文件…"
            />
            <small>{draft.length.toLocaleString('zh-CN')} 字符 · Ctrl / ⌘ + S 保存到项目</small>
          </div>
        ) : (
          <section
            ref={pageRef}
            className="writer-reader__page"
            aria-label={`剧本第 ${activePageIndex + 1} 页`}
            tabIndex={0}
          >
            <div className="writer-reader__paper">
              {isPlainText
                ? <pre className="writer-reader__plain-text">{textPages[activePageIndex] || ''}</pre>
                : <MarkdownBlocks blocks={markdownPages[activePageIndex] || []} />}
            </div>
          </section>
        )}

        <footer className={`writer-reader__footer ${mode === 'edit' ? 'is-editing' : ''}`}>
          {mode === 'edit' ? <span>编辑模式 · 支持 Markdown 与纯文本</span> : <>
          <button type="button" onClick={() => goToPage(activePageIndex - 1)} disabled={activePageIndex === 0} aria-label="上一页">
            <ChevronLeft aria-hidden="true" /> 上一页
          </button>
          <nav className="writer-reader__pagination" aria-label="剧本页码">
            {paginationItems(pageCount, activePageIndex).map(item => typeof item === 'number' ? (
              <button
                type="button"
                key={item}
                aria-label={`第 ${item + 1} 页`}
                aria-current={item === activePageIndex ? 'page' : undefined}
                onClick={() => goToPage(item)}
              >
                {item + 1}
              </button>
            ) : <span key={item} aria-hidden="true">…</span>)}
          </nav>
          <span className="writer-reader__counter" role="status" aria-live="polite">第 {activePageIndex + 1} / {pageCount} 页</span>
          <button type="button" onClick={() => goToPage(activePageIndex + 1)} disabled={activePageIndex === pageCount - 1} aria-label="下一页">
            下一页 <ChevronRight aria-hidden="true" />
          </button>
          </>}
        </footer>
      </div>
    </div>
  );
}
