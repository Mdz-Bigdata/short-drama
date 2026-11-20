import { describe, expect, it } from 'vitest';

import {
  DIAGRAM_HEIGHT, DIAGRAM_WIDTH, arrowHead, cameraCone, contactStar, darker, diagramFileName, footprint, forwardOf, gridLines, legendText,
  metresLabel, placeTags, postureHeight, projectionFor, ringPoints, ringRadii, routeMidpoint, tagWidth,
} from './blockingDiagram';

const BOUNDS: [number, number, number, number] = [-5, -4, 5, 4];

describe('blocking diagram layout', () => {
  it('keeps the whole floor and the headroom above it inside the picture, at every view', () => {
    for (const tilt of [90, 45, 18]) {
      const projection = projectionFor(BOUNDS, tilt);
      const corners = [projection.at(-5, -4, 2.4), projection.at(5, -4, 2.4), projection.at(-5, 4), projection.at(5, 4)];
      for (const [x, y] of corners) {
        expect(x).toBeGreaterThanOrEqual(0);
        expect(x).toBeLessThanOrEqual(DIAGRAM_WIDTH);
        expect(y).toBeGreaterThanOrEqual(90);
        expect(y).toBeLessThanOrEqual(DIAGRAM_HEIGHT);
      }
    }
  });

  it('draws near things lower, raises height, and flattens height to nothing from straight above', () => {
    const oblique = projectionFor(BOUNDS, 45);
    expect(oblique.at(0, 2)[1]).toBeGreaterThan(oblique.at(0, -2)[1]);
    expect(oblique.at(0, 0, 1.7)[1]).toBeLessThan(oblique.at(0, 0)[1]);
    expect(oblique.at(3, 0)[0]).toBeGreaterThan(oblique.at(-3, 0)[0]);
    const top = projectionFor(BOUNDS, 90);
    expect(top.at(0, 0, 1.7)[1]).toBeCloseTo(top.at(0, 0)[1], 6);
    expect(top.rise).toBeCloseTo(0, 6);
  });

  it('rules one line per metre and marks every fifth', () => {
    const lines = gridLines(BOUNDS, projectionFor(BOUNDS, 45));
    expect(lines).toHaveLength(11 + 9);
    expect(lines.filter(line => line.major)).toHaveLength(3 + 1);
  });

  it('faces +z at yaw 0 and +x at yaw 90, and turns a footprint with its piece', () => {
    expect(forwardOf(0)[1]).toBeCloseTo(1);
    expect(forwardOf(90)[0]).toBeCloseTo(1);
    const square = footprint({ position: [1, 1], size: [2, 1, 1], yaw_deg: 0 });
    expect(square.map(([x]) => x).sort((a, b) => a - b)).toEqual([0, 0, 2, 2]);
    const turned = footprint({ position: [1, 1], size: [2, 1, 1], yaw_deg: 90 });
    expect(Math.max(...turned.map(([x]) => x)) - Math.min(...turned.map(([x]) => x))).toBeCloseTo(1);
  });

  it('opens a lens cone to its field of view and reaches a little past what it aims at', () => {
    const cone = cameraCone({ position: [0, 5], target: [0, 0], fov_deg: 40 });
    expect(cone.reach).toBeCloseTo(6.25);
    const left = cone.points[1];
    const right = cone.points[cone.points.length - 1];
    const angle = Math.abs(Math.atan2(left[0], 5 - left[1])) + Math.abs(Math.atan2(right[0], 5 - right[1]));
    expect((angle * 180) / Math.PI).toBeCloseTo(40, 3);
    // A lens that stands on its target still draws a wedge instead of dividing by zero.
    expect(cameraCone({ position: [1, 1], target: [1, 1], fov_deg: 40 }).points.every(point => point.every(Number.isFinite))).toBe(true);
    expect(cameraCone({ position: [0, 60], target: [0, 0], fov_deg: 10 }).reach).toBe(14);
  });

  it('lifts a tag that would cover another and keeps tags inside the picture', () => {
    const tags = placeTags([
      { name: '陆沉', color: '#E0453A', head: [800, 400] },
      { name: '苏晚', color: '#20B5A0', head: [810, 402] },
      { name: '角落里的人', color: '#3A78D6', head: [3, 500] },
    ]);
    const [first, second] = [tags.find(tag => tag.name === '陆沉')!, tags.find(tag => tag.name === '苏晚')!];
    const overlap = first.x < second.x + second.width && second.x < first.x + first.width
      && first.y < second.y + second.height && second.y < first.y + first.height;
    expect(overlap).toBe(false);
    expect(tags.find(tag => tag.name === '角落里的人')!.x).toBeGreaterThanOrEqual(8);
    expect(tagWidth('陆沉')).toBeGreaterThan(tagWidth('AB'));
  });

  it('puts a route number halfway along its length and points the arrowhead along the last leg', () => {
    expect(routeMidpoint([[0, 0], [10, 0], [10, 2]])).toEqual([6, 0]);
    const head = arrowHead([0, 0], [10, 0], 4);
    expect(head[0]).toEqual([10, 0]);
    expect(head[1][0]).toBeCloseTo(6);
    expect(head[1][1]).toBeCloseTo(2);
    expect(head[2][1]).toBeCloseTo(-2);
  });

  it('shortens the figure by posture, darkens a colour, and names a file safely', () => {
    expect(postureHeight('stand')).toBe(1);
    expect(postureHeight('sit')).toBeLessThan(1);
    expect(postureHeight('kneel')).toBeLessThan(postureHeight('sit'));
    expect(darker('#ffffff', 0.5)).toBe('#808080');
    expect(darker('nonsense')).toBe('#444444');
    expect(diagramFileName('E1/S01 夜', { index: 2, total: 4 }, 'top')).toBe('E1_S01__-站位图-2of4-top.png');
  });

  it('lays an effect ring on the floor: a circle from above, flattened as the view tilts', () => {
    const top = projectionFor(BOUNDS, 90);
    const ring = ringPoints([0, 0], 2, top, 4);
    const centre = top.at(0, 0);
    for (const point of ring) expect(Math.hypot(point[0] - centre[0], point[1] - centre[1])).toBeCloseTo(2 * top.scale);
    const oblique = projectionFor(BOUNDS, 45);
    const flat = ringPoints([0, 0], 2, oblique, 4);
    const middle = oblique.at(0, 0);
    expect(Math.abs(flat[1][1] - middle[1])).toBeLessThan(Math.abs(flat[0][0] - middle[0]));
    expect(ringRadii(3, 3)).toEqual([3, 2, 1]);
    expect(ringRadii(1.5, 1)).toEqual([1.5]);
    expect(ringRadii(2, 9)).toHaveLength(3);
  });

  it('draws a contact star around its point, writes metres in halves, and turns the legend into pasteable lines', () => {
    const star = contactStar([100, 100], 10);
    expect(star).toHaveLength(8);
    expect(star[0][0]).toBeCloseTo(100);
    expect(star[0][1]).toBeCloseTo(90);
    expect(metresLabel(2.24)).toBe('约 2 米');
    expect(metresLabel(2.3)).toBe('约 2.5 米');
    expect(metresLabel(0.1)).toBe('约 0.5 米');
    expect(legendText([
      { mark: '拳轨迹', meaning: '陆沉打向苏晚，\n两人相距约 2 米', color: '红', where: '偏右 1 米' },
      { mark: '标尺', meaning: '陆沉与苏晚相距约 2 米', color: '深灰', where: '' },
    ])).toBe('标记\t含义\t颜色\t指向位置\n拳轨迹\t陆沉打向苏晚， 两人相距约 2 米\t红\t偏右 1 米\n标尺\t陆沉与苏晚相距约 2 米\t深灰\t—');
  });
});
