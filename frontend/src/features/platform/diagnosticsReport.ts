export type Status = 'ok' | 'warning' | 'error';

export interface Finding {
  id: string;
  label: string;
  status: Status;
  detail: string;
  elapsed_ms: number;
}

export interface Report {
  status: Status;
  counts: Record<Status, number>;
  checked_at: string;
  checks: Finding[];
}

export interface DiagnosticsResponse extends Report {
  startup: Report | null;
}

/** What changed since the server started: checks whose status is different now. */
export function changedSinceStartup(now: Report, startup: Report | null): Finding[] {
  if (!startup) return [];
  const before = new Map(startup.checks.map(item => [item.id, item.status]));
  return now.checks.filter(item => before.has(item.id) && before.get(item.id) !== item.status);
}
