export type Mode = 'follow' | 'append' | 'rewrite';

export interface Draft {
  mode: Mode;
  text: string;
}

/** Whether a draft differs from what the account has saved for that stage. */
export function isChanged(saved: Draft, draft: Draft): boolean {
  if (saved.mode !== draft.mode) return true;
  return draft.mode !== 'follow' && saved.text !== draft.text.trim();
}
