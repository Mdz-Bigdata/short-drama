import type { ElementItem } from './elementTypes';

/** 真人演员记录(后端 core/real_person)：照片上是谁、授权用途与期限、火山方舟真人人像库素材。 */
export interface RealPersonRecord {
  person: string;
  scope: string;
  expires: string;
  ark_assets: string[];
  confirmed_by?: string;
  confirmed_at?: string;
}

export interface RealPersonPayload {
  person: string;
  scope: string;
  expires: string;
  ark_assets: string[];
  confirmed: boolean;
}

export function realPersonOf(item: ElementItem): RealPersonRecord | null {
  const raw = item.metadata?.real_person;
  if (!raw || typeof raw !== 'object') return null;
  const record = raw as Partial<RealPersonRecord>;
  if (!record.confirmed_by) return null;
  return {
    person: String(record.person || ''),
    scope: String(record.scope || ''),
    expires: String(record.expires || ''),
    ark_assets: Array.isArray(record.ark_assets) ? record.ark_assets.map(String) : [],
    confirmed_by: record.confirmed_by,
    confirmed_at: record.confirmed_at,
  };
}
