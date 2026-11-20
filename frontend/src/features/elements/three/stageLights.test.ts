import { Color } from 'three';
import { describe, expect, it } from 'vitest';

import { STAGE_AMBIENT, STAGE_LIGHTS, STAGE_PANELS, STAGE_SURROUND } from './stageLights';

function saturation(hex: string): number {
  return new Color(hex).getHSL({ h: 0, s: 0, l: 0 }).s;
}

describe('stageLights', () => {
  it('lights the model in neutral white so its colours match the reference image', () => {
    expect(STAGE_LIGHTS.key.color).toBeUndefined();
    expect(STAGE_LIGHTS.fill.color).toBeUndefined();
    expect(saturation(STAGE_AMBIENT.sky)).toBe(0);
    expect(saturation(STAGE_AMBIENT.ground)).toBeLessThan(0.05);
    expect(saturation(STAGE_SURROUND)).toBeLessThan(0.05);
  });

  it('keeps the brand tint to one rim light that is weaker than the key', () => {
    expect(STAGE_LIGHTS.rim.color).toBeTruthy();
    expect(STAGE_LIGHTS.rim.intensity).toBeLessThan(STAGE_LIGHTS.key.intensity / 2);
    // 从背后打：不染正面的颜色。
    expect(STAGE_LIGHTS.rim.position[2]).toBeLessThan(0);
    expect(STAGE_LIGHTS.key.position[2]).toBeGreaterThan(0);
  });

  it('gives glossy and metal surfaces panels to reflect from above and from both sides', () => {
    expect(STAGE_PANELS.some(panel => panel.position[1] > Math.abs(panel.position[0]))).toBe(true);
    expect(STAGE_PANELS.some(panel => panel.position[0] < 0)).toBe(true);
    expect(STAGE_PANELS.some(panel => panel.position[0] > 0)).toBe(true);
  });
});
