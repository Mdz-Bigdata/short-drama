export interface ProjectSkill {
  id: string;
  name: string;
  slug: string;
  description: string;
  markdown_content: string;
  source_type: 'created' | 'markdown_upload' | 'skill_package';
  command: string;
  content_sha256: string;
  version: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProjectSkillDraft {
  name: string;
  slug: string;
  description: string;
  markdown_content: string;
  enabled: boolean;
}
