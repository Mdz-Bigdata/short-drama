import type { ReactNode } from 'react';

/**
 * A number that is sent when the user is done with it (blur or Enter), not on every keystroke:
 * each send is a PATCH and an undo entry. Keyed by the value so a server answer resets the text.
 */
export function NumberField({ label, value, min, max, step = 0.1, disabled, suffix, onCommit }: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  suffix?: ReactNode;
  onCommit: (value: number) => void;
}) {
  const send = (text: string) => {
    const next = Number(text);
    if (text.trim() === '' || !Number.isFinite(next) || next === value) return;
    onCommit(Math.min(max ?? Infinity, Math.max(min ?? -Infinity, next)));
  };
  return (
    <label className="desk-field">
      <span>{label}</span>
      <input
        key={value}
        type="number" inputMode="decimal" defaultValue={value} min={min} max={max} step={step} disabled={disabled}
        onBlur={event => send(event.target.value)}
        onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur(); }}
      />
      {suffix}
    </label>
  );
}
