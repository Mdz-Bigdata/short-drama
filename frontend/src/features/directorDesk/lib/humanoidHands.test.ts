import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { Box3, Group } from 'three';
import { GLTFLoader } from 'three-stdlib';
import { beforeAll, describe, expect, it } from 'vitest';

import type { StageActor } from '../../spatial/spatialTypes';
import type { Hand, HandGrip } from './contacts';
import { HUMANOID_MODEL_URL } from './humanoidClips';
import { humanoidHandLocator, type HandSource } from './humanoidHands';

// The figure file the desk ships, parsed the way the stage parses it.
const FILE = readFileSync(resolve(process.cwd(), 'public/models/director-desk', HUMANOID_MODEL_URL.split('/').pop()!));

function actor(over: Partial<StageActor> = {}): StageActor {
  return {
    id: 'a1', name: '林夏', role: 'principal', position: [0, 0], yaw_deg: 0, height_m: 1.7, posture: 'stand', figure: 'humanoid', ...over,
  } as StageActor;
}

const clipAt = (clip: string, phase: number) => ({ preset: 'fight', joints: {}, clip, clip_phase: phase });

describe('humanoidHandLocator', () => {
  let source: HandSource;
  let grip: (who: StageActor, hand: Hand) => HandGrip | null;
  /** Where the hand is: the point alone. */
  const locate = (who: StageActor, hand: Hand) => grip(who, hand)?.point ?? null;

  beforeAll(async () => {
    const gltf = await new GLTFLoader().parseAsync(FILE.buffer.slice(FILE.byteOffset, FILE.byteOffset + FILE.byteLength) as ArrayBuffer, '');
    const box = new Box3().setFromObject(gltf.scene);
    source = { scene: gltf.scene, clips: gltf.animations, height: box.max.y - box.min.y, floor: box.min.y };
    const found = humanoidHandLocator(source);
    grip = (who, hand) => found(who, hand) as HandGrip | null;
  });

  it('finds a standing figure’s hands at its sides, below the shoulders and off the floor', () => {
    const right = locate(actor(), 'right')!;
    const left = locate(actor(), 'left')!;
    // Facing +Z with the figure's right towards −X, the way the stage draws it.
    expect(right[0]).toBeLessThan(-0.1);
    expect(left[0]).toBeGreaterThan(0.1);
    [right, left].forEach(point => {
      expect(point[1]).toBeGreaterThan(0.6);
      expect(point[1]).toBeLessThan(1.1);
    });
    const both = locate(actor(), 'both')!;
    expect(both[0]).toBeCloseTo((right[0] + left[0]) / 2, 5);
    expect(both[1]).toBeCloseTo((right[1] + left[1]) / 2, 5);
  });

  it('follows the sword hand through a swing instead of holding one spot', () => {
    const swing = Array.from({ length: 21 }, (_, index) => locate(actor({ pose: clipAt('human-sword-combo-v1', index / 20) }), 'right')!);
    const travelled = swing.slice(1).reduce((sum, point, index) => sum + Math.hypot(point[0] - swing[index][0], point[1] - swing[index][1], point[2] - swing[index][2]), 0);
    expect(travelled).toBeGreaterThan(2);
    const heights = swing.map(point => point[1]);
    expect(Math.max(...heights) - Math.min(...heights)).toBeGreaterThan(0.4);
    // The same frame asked for twice is the same point, in whatever order frames are asked for.
    expect(locate(actor({ pose: clipAt('human-sword-combo-v1', 0.5) }), 'right')).toEqual(swing[10]);
    expect(locate(actor({ pose: clipAt('human-sword-combo-v1', 0) }), 'right')).toEqual(swing[0]);
  });

  it('puts the hand where the figure is drawn: scaled to its height, turned with it, at its mark', () => {
    const pose = clipAt('human-sword-idle-v1', 0.3);
    const base = locate(actor({ pose }), 'right')!;
    const tall = locate(actor({ pose, height_m: 3.4 }), 'right')!;
    expect(tall.map(value => value / 2)).toEqual(base.map(value => expect.closeTo(value, 5)));
    const moved = locate(actor({ pose, position: [4, -2] }), 'right')!;
    expect(moved).toEqual([expect.closeTo(base[0] + 4, 5), expect.closeTo(base[1], 5), expect.closeTo(base[2] - 2, 5)]);
    // A quarter turn to the figure's left: what was ahead (+Z) is now towards +X.
    const turned = locate(actor({ pose, yaw_deg: 90 }), 'right')!;
    expect(turned).toEqual([expect.closeTo(base[2], 5), expect.closeTo(base[1], 5), expect.closeTo(-base[0], 5)]);
  });

  it('says which way the fist points what it holds: up at the top of a cut, across the body in a block, ahead with the arm hanging', () => {
    const raised = grip(actor({ pose: clipAt('human-sword-attack-v1', 0.25) }), 'right')!;
    expect(raised.along![1]).toBeGreaterThan(0.9);
    const block = grip(actor({ pose: clipAt('human-sword-block-v1', 0.5) }), 'right')!;
    expect(block.along![0]).toBeGreaterThan(0.6);
    expect(block.along![1]).toBeGreaterThan(0.4);
    const hanging = grip(actor(), 'right')!;
    expect(hanging.along![2]).toBeGreaterThan(0.8);
    // Unit vectors, square enough to each other to turn a blade by, and turned with the figure.
    [raised, block, hanging].forEach(item => {
      expect(Math.hypot(...item.along!)).toBeCloseTo(1, 3);
      expect(Math.hypot(...item.forward!)).toBeCloseTo(1, 3);
      expect(Math.abs(item.along![0] * item.forward![0] + item.along![1] * item.forward![1] + item.along![2] * item.forward![2])).toBeLessThan(0.5);
    });
    const turned = grip(actor({ yaw_deg: 90 }), 'right')!;
    expect(turned.along).toEqual([expect.closeTo(hanging.along![2], 3), expect.closeTo(hanging.along![1], 3), expect.closeTo(-hanging.along![0], 3)]);
    // Two hands on one thing: the right hand says which way it points.
    expect(grip(actor(), 'both')!.along).toEqual(hanging.along);
    expect(grip(actor(), 'left')!.along![2]).toBeGreaterThan(0.8);
  });

  it('drops with a figure that falls, and never goes under the floor', () => {
    const down = locate(actor({ pose: clipAt('human-fall-v1', 1) }), 'right')!;
    expect(down[1]).toBeLessThan(0.45);
    expect(down[1]).toBeGreaterThanOrEqual(0);
  });

  it('leaves every other kind of figure to the next locator', () => {
    expect(locate(actor({ figure: 'mannequin' }), 'right')).toBeNull();
    expect(locate(actor({ figure: 'standin' }), 'right')).toBeNull();
    expect(locate(actor({ figure: undefined }), 'both')).toBeNull();
  });

  it('answers nothing for a model it does not know the bones of', () => {
    // A scene with no bones at all, standing in for some other model.
    const bare = humanoidHandLocator({ ...source, scene: new Group() });
    expect(bare(actor(), 'right')).toBeNull();
  });
});

