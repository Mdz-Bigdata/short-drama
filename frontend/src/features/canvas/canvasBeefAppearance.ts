export type CanvasThemeChoice = 'follow' | 'light' | 'dark' | 'custom';
export type CanvasGrid = 'dots' | 'lines' | 'blank';

export interface CustomCanvasTheme {
  /** Six-digit HEX with #. */
  background: string;
  /** -0.5 … 0.5 along OKLCH lightness; 0 shows the colour exactly as typed. */
  brightness: number;
  grid: string;
  /** 0 … 1. */
  gridStrength: number;
}

export interface CanvasAppearance {
  theme: CanvasThemeChoice;
  grid: CanvasGrid;
  custom: CustomCanvasTheme;
}

export const DEFAULT_CUSTOM: CustomCanvasTheme = { background: '#e9eaec', brightness: 0, grid: '#8a8f98', gridStrength: 0.35 };
export const DEFAULT_APPEARANCE: CanvasAppearance = { theme: 'follow', grid: 'dots', custom: DEFAULT_CUSTOM };
/** Light boards sit on a fog grey deeper than white nodes; dark boards on a neutral grey lighter than dark nodes. */
const PRESETS = {
  light: { background: '#e6e7ea', grid: '#9aa0a8', gridStrength: 0.4 },
  dark: { background: '#2b2c2f', grid: '#6c7078', gridStrength: 0.45 },
} as const;

/** "abc", "#abc", "a1b2c3" or "#A1B2C3" as "#a1b2c3"; anything else null. */
export function normaliseHex(value: string): string | null {
  const raw = value.trim().replace(/^#/, '');
  if (/^[0-9a-f]{3}$/i.test(raw)) return `#${raw.split('').map(ch => ch + ch).join('')}`.toLowerCase();
  if (/^[0-9a-f]{6}$/i.test(raw)) return `#${raw}`.toLowerCase();
  return null;
}

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, Number.isFinite(value) ? value : 0));

/** Any stored value as a well-formed appearance; what cannot be read falls back to the default. */
export function normaliseAppearance(value: unknown): CanvasAppearance {
  const found = (value && typeof value === 'object' ? value : {}) as Partial<CanvasAppearance> & { custom?: Partial<CustomCanvasTheme> };
  const theme = (['follow', 'light', 'dark', 'custom'] as const).includes(found.theme as CanvasThemeChoice) ? found.theme as CanvasThemeChoice : 'follow';
  const grid = (['dots', 'lines', 'blank'] as const).includes(found.grid as CanvasGrid) ? found.grid as CanvasGrid : 'dots';
  const custom: Partial<CustomCanvasTheme> = found.custom ?? {};
  return {
    theme, grid,
    custom: {
      background: normaliseHex(String(custom.background ?? '')) ?? DEFAULT_CUSTOM.background,
      brightness: clamp(Number(custom.brightness ?? 0), -0.5, 0.5),
      grid: normaliseHex(String(custom.grid ?? '')) ?? DEFAULT_CUSTOM.grid,
      gridStrength: clamp(Number(custom.gridStrength ?? DEFAULT_CUSTOM.gridStrength), 0, 1),
    },
  };
}

/** The colours a board is drawn with, given its choice and the workspace's own light or dark mode. */
export function resolveAppearance(appearance: CanvasAppearance, global: 'light' | 'dark'): { mode: 'light' | 'dark'; background: string; grid: string; gridStrength: number; kind: CanvasGrid } {
  if (appearance.theme === 'custom') {
    const { background, brightness, grid, gridStrength } = appearance.custom;
    const shown = brightness ? `oklch(from ${background} calc(l + ${brightness}) c h)` : background;
    return { mode: lightness(background) + brightness > 0.6 ? 'light' : 'dark', background: shown, grid, gridStrength, kind: appearance.grid };
  }
  const mode = appearance.theme === 'follow' ? global : appearance.theme;
  return { mode, ...PRESETS[mode], kind: appearance.grid };
}

/** Rough perceived lightness 0 … 1 of a HEX colour, enough to pick light or dark node chrome. */
export function lightness(hex: string): number {
  const clean = normaliseHex(hex) ?? '#000000';
  const [r, g, b] = [1, 3, 5].map(at => Number.parseInt(clean.slice(at, at + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** CSS custom properties a board element takes. */
export function appearanceStyle(resolved: ReturnType<typeof resolveAppearance>): Record<string, string> {
  const hex = normaliseHex(resolved.grid) ?? '#808080';
  const rgb = [1, 3, 5].map(at => Number.parseInt(hex.slice(at, at + 2), 16)).join(', ');
  return {
    '--canvas-beef-bg': resolved.background,
    '--canvas-beef-grid': resolved.grid,
    '--canvas-beef-grid-rgb': rgb,
    '--canvas-beef-grid-strength': String(resolved.gridStrength),
  };
}

const boardKey = (canvasId: string) => `canvas.appearance.${canvasId}`;
const defaultKey = (accountId: string) => `canvas.appearance.default.${accountId || 'anonymous'}`;

function read(key: string): CanvasAppearance | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? normaliseAppearance(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

function write(key: string, value: CanvasAppearance): void {
  try {
    localStorage.setItem(key, JSON.stringify(normaliseAppearance(value)));
  } catch {
    // Kept for this visit only.
  }
}

/** A board's appearance: its own, else this account's default for new boards, else follow the workspace. */
export function boardAppearance(canvasId: string, accountId: string): CanvasAppearance {
  return read(boardKey(canvasId)) ?? read(defaultKey(accountId)) ?? DEFAULT_APPEARANCE;
}

export const saveBoardAppearance = (canvasId: string, value: CanvasAppearance) => write(boardKey(canvasId), value);
export const saveDefaultAppearance = (accountId: string, value: CanvasAppearance) => write(defaultKey(accountId), value);
