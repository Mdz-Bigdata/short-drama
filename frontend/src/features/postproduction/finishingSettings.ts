/**
 * 成片精修: the title card on a chosen frame, the film's subtitle style, a film-wide grade and an ending card.
 *
 * The backend keeps these beside the four basic switches (timeline.settings.finishing) and sends them with
 * GET /timeline as post.finishing: the value, the options it accepts (by id) and the episode's 下集预告 to offer
 * as the ending card's line (app/core/film_finishing.py). An edit names only what moves and goes out through the
 * same `settings` operation as the switches. This file types that and holds the small sums the panel shows.
 */

export type ColorSlider = 'brightness' | 'contrast' | 'saturation' | 'warmth';

export interface TitleBackground { shot_uid?: number | null; shot_id?: number | null; at: number }

export interface FinishingValue {
  title: { animation: string; background: TitleBackground | null };
  subtitle: { size: string; color: string; position: string; outline: string };
  color: { preset: string } & Record<ColorSlider, number>;
  ending: { enabled: boolean; text: string };
}

export interface FinishingOptions {
  title_animations: string[];
  subtitle: { sizes: string[]; positions: string[]; outlines: string[]; colors: Array<{ id: string; rgb: [number, number, number] }> };
  color: { limit: number; sliders: ColorSlider[]; presets: Array<{ id: string } & Record<ColorSlider, number>> };
  ending: { max_chars: number; seconds: number };
}

export interface FinishingView {
  value: FinishingValue;
  options: FinishingOptions;
  /** The episode ledger's 下集预告, offered as the ending card's line; empty when there is none. */
  ending_teaser?: string;
}

/** What an edit sends: only the items that change, grouped as the value is. */
export interface FinishingChanges {
  title?: Partial<FinishingValue['title']>;
  subtitle?: Partial<FinishingValue['subtitle']>;
  color?: Partial<FinishingValue['color']>;
  ending?: Partial<FinishingValue['ending']>;
}

/** Whether the grade leaves the picture alone (then no colour filter is added at all). */
export function isNeutralGrade(color: FinishingValue['color'], sliders: ColorSlider[]): boolean {
  return sliders.every(name => !color[name]);
}

/** Every slider back at zero. */
export function neutralGrade(sliders: ColorSlider[]): Partial<Record<ColorSlider, number>> {
  return Object.fromEntries(sliders.map(name => [name, 0]));
}

/** A slider's value as the panel shows it: +12, 0, -30. */
export function signed(value: number): string {
  const whole = Math.round(value);
  return whole > 0 ? `+${whole}` : String(whole);
}

/** Where a newly picked title frame starts: the middle of the clip, where a shot has usually settled. */
export function defaultMoment(duration: number | null | undefined): number {
  return duration && duration > 0 ? Math.round((duration / 2) * 10) / 10 : 0;
}

/** The last moment of a clip a frame can be taken from. */
export function lastMoment(duration: number | null | undefined): number {
  return duration && duration > 0.1 ? Math.floor((duration - 0.1) * 10) / 10 : 0;
}
