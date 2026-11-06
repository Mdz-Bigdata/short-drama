import { API_BASE } from '../../api/client';

/** A stored voice is a backend file path or an absolute URL; the media folder serves it by name. */
export function mediaUrlOf(value: string): string {
  if (/^(https?:)?\/\//.test(value) || value.startsWith('data:')) return value;
  const name = value.split('/').pop() ?? value;
  return `${API_BASE}/media/${name}`;
}

/** The spoken words of a dialogue cell: speaker labels, bracketed delivery notes and braces removed. */
export function spokenText(raw: string): string {
  const braced = [...raw.matchAll(/[{｛]([^{}｛｝]+)[}｝]/g)].map(m => m[1]);
  const parts = braced.length ? braced : [raw.replace(/^[^：:「"]{1,12}?[：:]\s*/, '')];
  return parts
    .map(part => part.replace(/[（(][^）)]*[）)]/g, '').replace(/[（(][^）)]*$/, '').replace(/[「」『』“”"'\s]/g, '').trim())
    .filter(part => part && !/^无+$/.test(part))
    .join(' ');
}
