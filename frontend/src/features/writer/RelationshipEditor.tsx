import { Pencil, X } from 'lucide-react';
import { useState, type FormEvent } from 'react';

import { graphCast, isBidirectional } from './relationshipCast';
import type { WriterRelationship, WriterRole } from './types';
import { t } from '../../i18n';

const PAGE_SIZE = 20;

interface RelationshipForm {
  target: WriterRelationship | null;
  from: string;
  to: string;
  relation: string;
  bidirectional: boolean;
}

const EMPTY_FORM: RelationshipForm = { target: null, from: '', to: '', relation: '', bidirectional: false };

/** 人物关系编辑: every relation as "A → B · tag", and one form to add a relation or rewrite the one being edited. */
export function RelationshipEditor({
  roles,
  relationships,
  onSave,
}: {
  roles: WriterRole[];
  relationships: WriterRelationship[];
  onSave?: (relationships: WriterRelationship[]) => Promise<void>;
}) {
  const [page, setPage] = useState(0);
  const [form, setForm] = useState<RelationshipForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const { allNames, valid } = graphCast(roles, relationships);
  const pageCount = Math.max(1, Math.ceil(valid.length / PAGE_SIZE));
  const activePage = Math.min(page, pageCount - 1);
  const visible = valid.slice(activePage * PAGE_SIZE, (activePage + 1) * PAGE_SIZE);
  const names = Array.from(new Set([...allNames, form.from, form.to].filter(Boolean)));

  const commit = async (next: WriterRelationship[]) => {
    if (!onSave) return;
    setSaving(true);
    setError('');
    try {
      await onSave(next);
      setForm(EMPTY_FORM);
    } catch (reason) {
      setError(reason instanceof Error && reason.message ? reason.message : t('关系保存失败，请稍后重试。'));
    } finally {
      setSaving(false);
    }
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving) return;
    const from = form.from.trim();
    const to = form.to.trim();
    if (!from || !to) {
      setError(t('请选择关系两端的角色。'));
      return;
    }
    if (from === to) {
      setError(t('关系两端不能是同一个角色。'));
      return;
    }
    const entry: WriterRelationship = { from, to, relation: form.relation.trim() || '剧情关联', bidirectional: form.bidirectional };
    const next = [...relationships];
    const index = form.target ? next.indexOf(form.target) : -1;
    if (index >= 0) next[index] = entry;
    else next.push(entry);
    void commit(next);
  };

  const startEdit = (edge: WriterRelationship) => {
    setError('');
    setForm({ target: edge, from: String(edge.from || ''), to: String(edge.to || ''), relation: String(edge.relation || ''), bidirectional: isBidirectional(edge) });
  };

  const remove = (edge: WriterRelationship) => {
    if (saving) return;
    if (form.target === edge) setForm(EMPTY_FORM);
    void commit(relationships.filter(item => item !== edge));
  };

  const editing = form.target !== null;
  return (
    <div className="writer-relations" aria-label={t('人物关系列表')}>
      <div className="writer-network__card writer-relations__list">
        {valid.length > 0 ? visible.map((edge, index) => {
          const bidirectional = isBidirectional(edge);
          return (
            <div className={`writer-relations__row ${form.target === edge ? 'is-editing' : ''}`} key={`${edge.from}-${edge.to}-${activePage}-${index}`}>
              <strong>{edge.from || '未知'}</strong>
              <span className="writer-relations__arrow" aria-label={bidirectional ? t('双向关系') : t('指向')}>{bidirectional ? '↔' : '→'}</span>
              <strong>{edge.to || '未知'}</strong>
              <em className="writer-relations__tag">{edge.relation || '剧情关联'}</em>
              {onSave && (
                <span className="writer-relations__tools">
                  <button type="button" aria-label={`编辑 ${edge.from} 与 ${edge.to} 的关系`} disabled={saving} onClick={() => startEdit(edge)}><Pencil aria-hidden="true" /></button>
                  <button type="button" aria-label={`删除 ${edge.from} 与 ${edge.to} 的关系`} disabled={saving} onClick={() => remove(edge)}><X aria-hidden="true" /></button>
                </span>
              )}
            </div>
          );
        }) : <p className="writer-relations__empty">{t('角色已识别，但剧本中尚未提取到可靠关系；补充分场角色或人物关系后即可生成连线。')}</p>}
        {pageCount > 1 && (
          <nav className="writer-relations__pagination" aria-label={t('人物关系列表分页')}>
            <button type="button" disabled={activePage === 0} onClick={() => setPage(activePage - 1)}>{t('上一页')}</button>
            <span>{activePage + 1} / {pageCount}</span>
            <button type="button" disabled={activePage === pageCount - 1} onClick={() => setPage(activePage + 1)}>{t('下一页')}</button>
          </nav>
        )}
      </div>
      {onSave && (
        <form className="writer-network__card writer-relations__form" aria-label={editing ? t('编辑人物关系') : t('新增人物关系')} onSubmit={submit}>
          <div className="writer-relations__ends">
            <label>
              <span>{t('起始角色')}</span>
              <select value={form.from} disabled={saving} onChange={event => setForm(current => ({ ...current, from: event.target.value }))}>
                <option value="">{t('选择角色')}</option>
                {names.map(name => <option key={name} value={name}>{name}</option>)}
              </select>
            </label>
            <label>
              <span>{t('目标角色')}</span>
              <select value={form.to} disabled={saving} onChange={event => setForm(current => ({ ...current, to: event.target.value }))}>
                <option value="">{t('选择角色')}</option>
                {names.map(name => <option key={name} value={name}>{name}</option>)}
              </select>
            </label>
          </div>
          <label className="writer-relations__relation">
            <span>{t('关系描述')}</span>
            <div>
              <input value={form.relation} maxLength={120} placeholder={t('例如: 夫妻, 宿敌')} disabled={saving} onChange={event => setForm(current => ({ ...current, relation: event.target.value }))} />
              <button type="submit" className="is-primary" disabled={saving}>{editing ? t('保存修改') : t('添加')}</button>
              {editing && <button type="button" disabled={saving} onClick={() => { setForm(EMPTY_FORM); setError(''); }}>{t('取消')}</button>}
            </div>
          </label>
          <label className="writer-relations__toggle">
            <input type="checkbox" checked={form.bidirectional} disabled={saving} onChange={event => setForm(current => ({ ...current, bidirectional: event.target.checked }))} />
            <span>{t('双向关系')}</span>
          </label>
          {saving && <small role="status">{t('保存中…')}</small>}
          {error && <small className="is-error" role="alert">{error}</small>}
        </form>
      )}
    </div>
  );
}
