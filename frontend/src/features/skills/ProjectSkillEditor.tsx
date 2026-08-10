import { useState } from 'react';
import { Code2, Save, X } from 'lucide-react';

import type { ProjectSkill, ProjectSkillDraft } from './skillTypes';


interface Props {
  skill: ProjectSkill | null;
  busy: boolean;
  onCancel: () => void;
  onSave: (draft: ProjectSkillDraft) => Promise<void>;
}

const EMPTY: ProjectSkillDraft = {
  name: '', slug: '', description: '', markdown_content: '', enabled: true,
};

const fromSkill = (skill: ProjectSkill | null): ProjectSkillDraft => skill ? {
  name: skill.name,
  slug: skill.slug,
  description: skill.description,
  markdown_content: skill.markdown_content,
  enabled: skill.enabled,
} : EMPTY;


export function ProjectSkillEditor({ skill, busy, onCancel, onSave }: Props) {
  const [draft, setDraft] = useState<ProjectSkillDraft>(() => fromSkill(skill));
  const [validation, setValidation] = useState('');

  const change = (key: keyof ProjectSkillDraft, value: string | boolean) => {
    setDraft(current => ({ ...current, [key]: value }));
    setValidation('');
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!draft.name.trim() || !draft.markdown_content.trim()) {
      setValidation('请填写 Skill 名称和 Markdown 指令。');
      return;
    }
    if (!skill && !/^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$/.test(draft.slug)) {
      setValidation('命令标识需为 3-80 位小写字母、数字或中横线。');
      return;
    }
    await onSave({ ...draft, name: draft.name.trim(), slug: draft.slug.trim() });
  };

  return (
    <form className="skill-editor" onSubmit={submit}>
      <div className="skill-editor__heading">
        <div>
          <span className="skill-editor__eyebrow"><Code2 size={14} /> Markdown 编辑器</span>
          <h3>{skill ? `编辑 ${skill.name}` : '新增项目 Skill'}</h3>
        </div>
        {skill && <span className="skill-version">v{skill.version}</span>}
      </div>

      <div className="skill-editor__grid">
        <label>
          <span>Skill 名称</span>
          <input value={draft.name} maxLength={160} onChange={event => change('name', event.target.value)} />
        </label>
        <label>
          <span>命令标识</span>
          <div className="skill-slug-input"><b>/skill.</b><input aria-label="命令标识" value={draft.slug} disabled={Boolean(skill)} maxLength={80} onChange={event => change('slug', event.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''))} /></div>
        </label>
      </div>
      <label>
        <span>Skill 描述</span>
        <input value={draft.description} maxLength={4000} onChange={event => change('description', event.target.value)} placeholder="说明这个 Skill 解决什么问题" />
      </label>
      <label className="skill-editor__markdown">
        <span>Markdown 指令 <small>{new TextEncoder().encode(draft.markdown_content).length} / 131072 bytes</small></span>
        <textarea aria-label="Markdown 指令" value={draft.markdown_content} onChange={event => change('markdown_content', event.target.value)} placeholder={'---\nname: My Skill\ndescription: Workflow guidance\n---\n\n# Instructions\n...'} rows={15} spellCheck={false} />
      </label>
      {validation && <p className="skill-feedback skill-feedback--error" role="alert">{validation}</p>}
      <p className="skill-editor__guard">Markdown 仅作为创作指令注入模型，不执行其中的脚本、URL、命令或代码。</p>
      <div className="skill-editor__actions">
        <button type="button" className="skill-secondary-btn" onClick={onCancel} disabled={busy}><X size={16} /> 取消编辑</button>
        <button type="submit" className="skill-primary-btn" disabled={busy}><Save size={16} /> {busy ? '保存中…' : '保存 Skill'}</button>
      </div>
    </form>
  );
}
