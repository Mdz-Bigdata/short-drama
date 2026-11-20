import { BoxGeometry, Group, Mesh } from 'three';
import { describe, expect, it } from 'vitest';

import { floorGridFor, largestSide, niceStep } from './stageFloor';


describe('stage floor grid', () => {
  it('rounds a length to 1, 2 or 5 times a power of ten', () => {
    expect(niceStep(0.0167)).toBeCloseTo(0.02);
    expect(niceStep(0.33)).toBeCloseTo(0.2);
    expect(niceStep(0.6)).toBeCloseTo(0.5);
    expect(niceStep(0.9)).toBeCloseTo(1);
    expect(niceStep(5)).toBe(5);
    expect(niceStep(30)).toBe(20);
    expect(niceStep(0)).toBe(1);
    expect(niceStep(Number.NaN)).toBe(1);
  });

  it('sizes the cells, the fade and the drop from the model, small or large', () => {
    // A 10 cm prop: 2 cm cells, and the grid is still there one metre out instead of fading at 28.
    const cup = floorGridFor(0.1);
    expect(cup.cellSize).toBeCloseTo(0.02);
    expect(cup.sectionSize).toBeCloseTo(0.1);
    expect(cup.fadeDistance).toBeCloseTo(1);
    expect(cup.drop).toBeCloseTo(0.0002);

    // A 60 m street: the floor reaches well past the far end of the model.
    const street = floorGridFor(60);
    expect(street.cellSize).toBe(10);
    expect(street.sectionSize).toBe(50);
    expect(street.fadeDistance).toBe(600);
    expect(street.fadeDistance).toBeGreaterThan(60 * 2);
  });

  it('falls back to a two-metre stage when the model has no size', () => {
    expect(floorGridFor(0)).toEqual(floorGridFor(2));
    expect(floorGridFor(Number.NaN)).toEqual(floorGridFor(2));
    expect(largestSide(new Group())).toBe(0);
  });

  it('measures the longest side of the whole model, offsets included', () => {
    const model = new Group();
    const near = new Mesh(new BoxGeometry(1, 2, 1));
    const far = new Mesh(new BoxGeometry(1, 1, 1));
    far.position.x = 7;
    model.add(near, far);
    // x runs from -0.5 to 7.5.
    expect(largestSide(model)).toBeCloseTo(8);
  });
});
