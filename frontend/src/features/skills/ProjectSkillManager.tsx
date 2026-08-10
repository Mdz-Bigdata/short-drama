import { useEffect, useRef, useState } from 'react';
import { Box, FileUp, Pencil, Plus, Power, Upload, X } from 'lucide-react';

import { ProjectSkillEditor } from './ProjectSkillEditor';
import type { ProjectSkill, ProjectSkillDraft } from './skillTypes';


interface Props {
  open: boolean;
  role?: 'admin' | 'editor' | 'user';
  mustChangePassword?: boolean;
  onClose: () => void;
}

const API = 'http://localhost:8000/api/project-skills';
const sourceLabels = {
  created: '在线创建', markdown_upload: 'Markdown 上传', skill_package: 'Skill 包导入',
};


async function responseData(response: Response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || 'Skill 操作失败');
  return data;
}


export function ProjectSkillManager({ open, role, mustChangePassword, onClose }: Props) {
  const [skills, setSkills] = useState<ProjectSkill[]>([]);
  const [editing, setEditing] = useState<ProjectSkill | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [error, setError] = useState('');
  const markdownInput = useRef<HTMLInputElement>(null);
  const packageInput = useRef<HTMLInputElement>(null);
  const canManage = role === 'admin' && !mustChangePassword;

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await responseData(await fetch(API, { credentials: 'include' }));
      setSkills(data.items || []);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Skill 列表加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    let active = true;
    void fetch(API, { credentials: 'include' })
      .then(responseData)
      .then(data => { if (active) setSkills(data.items || []); })
      .catch(caught => { if (active) setError(caught instanceof Error ? caught.message : 'Skill 列表加载失败'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [open, onClose]);

  if (!open) return null;

  const save = async (draft: ProjectSkillDraft) => {
    setBusy(true);
    setError('');
    try {
      const target = editing ? `${API}/${editing.id}` : API;
      const body = editing
        ? { name: draft.name, description: draft.description, markdown_content: draft.markdown_content }
        : draft;
      await responseData(await fetch(target, {
        method: editing ? 'PATCH' : 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      }));
      setFeedback(editing ? 'Skill 已更新并立即应用。' : 'Skill 已创建并立即应用。');
      setEditorOpen(false);
      setEditing(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '保存失败');
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (skill: ProjectSkill) => {
    setError('');
    try {
      await responseData(await fetch(`${API}/${skill.id}/enabled`, {
        method: 'PATCH', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !skill.enabled }),
      }));
      setFeedback(!skill.enabled ? `${skill.name} 已全局启用。` : `${skill.name} 已禁用。`);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '启停失败');
    }
  };

  const upload = async (file: File, endpoint: 'upload' | 'import') => {
    setBusy(true);
    setError('');
    const form = new FormData();
    form.append('file', file);
    try {
      await responseData(await fetch(`${API}/${endpoint}`, { method: 'POST', credentials: 'include', body: form }));
      setFeedback(endpoint === 'upload' ? 'Markdown 已上传并启用。' : 'Skill 包已安全导入并启用。');
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '导入失败');
    } finally {
      setBusy(false);
    }
  };

  const close = () => {
    setEditing(null);
    setEditorOpen(false);
    setFeedback('');
    setError('');
    onClose();
  };

  return (
    <div className="skill-manager-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) close(); }}>
      <section className="skill-manager" role="dialog" aria-modal="true" aria-labelledby="skill-manager-title">
        <header className="skill-manager__header">
          <div className="skill-manager__title"><span><Power size={20} /></span><div><p>PROJECT RUNTIME</p><h2 id="skill-manager-title">项目 Skill 管理</h2></div></div>
          <div className="skill-manager__summary"><b>{skills.filter(skill => skill.enabled).length}</b><span>已启用 / {skills.length} 个</span></div>
          <button type="button" className="skill-icon-btn" aria-label="关闭 Skill 管理" onClick={close}><X size={21} /></button>
        </header>

        {!canManage && <p className="skill-manager__notice">{mustChangePassword ? '请先在用户中心修改管理员初始密码，再管理全局 Skill。' : '当前账号可查看 Skill；只有管理员可以新增、编辑和启停。'}</p>}

        <div className="skill-manager__toolbar">
          <div><h3>全局 Markdown Skills</h3><p>启用后立即进入项目所有文本模型的创作指令链。</p></div>
          {canManage && <div className="skill-manager__tools">
            <button type="button" onClick={() => { setEditing(null); setEditorOpen(true); }}><Plus size={16} /> 新增 Skill</button>
            <button type="button" onClick={() => markdownInput.current?.click()}><FileUp size={16} /> 上传 Markdown</button>
            <button type="button" onClick={() => packageInput.current?.click()}><Box size={16} /> 导入 Skill 包</button>
            <input ref={markdownInput} className="skill-file-input" aria-label="选择 Markdown 文件" type="file" accept=".md,text/markdown,text/plain" onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file, 'upload'); event.target.value = ''; }} />
            <input ref={packageInput} className="skill-file-input" aria-label="选择 Skill 包文件" type="file" accept=".zip,application/zip" onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file, 'import'); event.target.value = ''; }} />
          </div>}
        </div>

        {feedback && <p className="skill-feedback" role="status">{feedback}</p>}
        {error && <p className="skill-feedback skill-feedback--error" role="alert">{error}</p>}

        <div className="skill-manager__body">
          {editorOpen ? <ProjectSkillEditor key={editing?.id || 'new'} skill={editing} busy={busy} onSave={save} onCancel={() => { setEditorOpen(false); setEditing(null); setError(''); }} /> : (
            <div className="skill-list" aria-busy={loading}>
              {loading && !skills.length && <p className="skill-empty">正在加载 Skill…</p>}
              {!loading && !skills.length && <div className="skill-empty"><Upload size={28} /><b>还没有自定义 Skill</b><span>新建 Markdown，或上传 `.md` / 导入含 `SKILL.md` 的 ZIP 包。</span></div>}
              {skills.map(skill => <article className={`project-skill-card ${skill.enabled ? 'is-enabled' : ''}`} key={skill.id}>
                <div className="project-skill-card__state"><span>{skill.enabled ? '运行中' : '已停用'}</span><small>{sourceLabels[skill.source_type] || skill.source_type}</small></div>
                <div className="project-skill-card__content"><div><h3>{skill.name}</h3><code>{skill.command}</code></div><p>{skill.description || '暂无描述'}</p><pre>{skill.markdown_content.slice(0, 180)}</pre><small>v{skill.version} · SHA {skill.content_sha256.slice(0, 10)}</small></div>
                <div className="project-skill-card__actions">
                  <button type="button" aria-label={`编辑${skill.name}`} disabled={!canManage} onClick={() => { setEditing(skill); setEditorOpen(true); }}><Pencil size={16} /> 编辑</button>
                  <button type="button" role="switch" aria-checked={skill.enabled} aria-label={`启用${skill.name}`} disabled={!canManage} onClick={() => void toggle(skill)}><span /></button>
                </div>
              </article>)}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
