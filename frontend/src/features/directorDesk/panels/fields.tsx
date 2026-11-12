import { useEffect, useLayoutEffect, useRef, type InputHTMLAttributes, type ReactNode } from 'react';

type DraftProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'defaultValue' | 'onChange' | 'onBlur' | 'onKeyDown'> & {
  value: string | number;
  /** The text as it was typed, once the user is done with it; `input` is there to set what it shows afterwards. */
  onDone: (text: string, input: HTMLInputElement) => void;
};

/**
 * Text that is sent when the user is done with it: on blur, or on Enter, which leaves focus in the field. Dropped to
 * the page, focus would hand the next Backspace (a typo spotted a moment late) to the desk, which deletes what is
 * selected on the stage. Between sends the text follows `value` (a server answer, an undo, the playhead moving), but
 * never over what is being typed.
 */
export function DraftInput({ value, onDone, ...rest }: DraftProps) {
  const input = useRef<HTMLInputElement>(null);
  const typed = useRef(false);
  const shown = String(value);
  // What the field showed once it was last sent or followed the value. A send the plan draws the same as before
  // (−180° shown as 180°) leaves the value where it was; without this, every Enter and the blur after would send it
  // again, each one a PATCH and an undo step.
  const settled = useRef(shown);
  useLayoutEffect(() => {
    if (!input.current || typed.current) return;
    input.current.value = shown;
    settled.current = shown;
  }, [shown]);
  const finish = (node: HTMLInputElement) => {
    if (!typed.current && node.value === settled.current) return;
    typed.current = false;
    onDone(node.value, node);
    settled.current = node.value;
  };
  return (
    <input
      {...rest} ref={input} defaultValue={shown}
      onChange={() => { typed.current = true; }}
      onBlur={event => finish(event.currentTarget)}
      onKeyDown={event => { if (event.key === 'Enter') finish(event.currentTarget); }}
    />
  );
}

/**
 * A number that is sent when the user is done with it (blur or Enter), not on every keystroke:
 * each send is a PATCH and an undo entry.
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
  const send = (text: string, input: HTMLInputElement) => {
    const next = Number(text);
    const clamped = Math.min(max ?? Infinity, Math.max(min ?? -Infinity, next));
    input.value = String(text.trim() === '' || !Number.isFinite(next) ? value : clamped);
    if (text.trim() !== '' && Number.isFinite(next) && clamped !== value) onCommit(clamped);
  };
  return (
    <label className="desk-field">
      <span>{label}</span>
      <DraftInput type="number" inputMode="decimal" value={value} min={min} max={max} step={step} disabled={disabled} onDone={send} />
      {suffix}
    </label>
  );
}

/**
 * A colour that is sent once, when the picker is closed. React's onChange is the browser's `input` event,
 * which fires on every move inside the picker, and each send is a PATCH and an undo entry. The browser's
 * own `change` fires when the picker is dismissed. Keyed by the value so a server answer resets the swatch.
 */
export function ColorField({ label, value, disabled, wide, onCommit }: { label: string; value: string; disabled?: boolean; wide?: boolean; onCommit: (value: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const send = (next: string) => { if (next !== value) onCommit(next); };
  const latest = useRef(send);
  useEffect(() => { latest.current = send; });
  useEffect(() => {
    const node = input.current;
    if (!node) return undefined;
    const onPicked = () => latest.current(node.value);
    node.addEventListener('change', onPicked);
    return () => node.removeEventListener('change', onPicked);
  }, [value]);
  return (
    <label className={`desk-field ${wide ? 'is-wide' : ''}`}>
      <span>{label}</span>
      <input key={value} ref={input} type="color" defaultValue={value} disabled={disabled} onBlur={event => send(event.target.value)} />
    </label>
  );
}
