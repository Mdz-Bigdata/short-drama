import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { HUMANOID_CLIPS, HUMANOID_CLIP_GROUPS, HUMANOID_MODEL_SHA256, HUMANOID_MODEL_URL, clipForPosture, humanoidClip } from './humanoidClips';
import { posePosture } from './poses';

interface Gltf {
  nodes: Array<{ name?: string }>;
  accessors: Array<{ max?: number[] }>;
  animations: Array<{ name: string; samplers: Array<{ input: number }>; channels: Array<{ target: { node: number; path: string } }> }>;
  skins: Array<{ joints: number[] }>;
}

// The file the desk ships, read the way a browser will get it: the table below it has to describe it.
const FILE = readFileSync(resolve(process.cwd(), 'public/models/director-desk', HUMANOID_MODEL_URL.split('/').pop()!));
const GLTF = JSON.parse(FILE.subarray(20, 20 + FILE.readUInt32LE(12)).toString('utf8')) as Gltf;

describe('the built-in figure and its clip table', () => {
  it('is the file the table was written for', () => {
    expect(createHash('sha256').update(FILE).digest('hex')).toBe(HUMANOID_MODEL_SHA256);
  });

  it('lists every motion in the file, in the file’s order, under its name and at its length', () => {
    expect(HUMANOID_CLIPS.map(clip => clip.index)).toEqual(GLTF.animations.map((_, index) => index));
    expect(HUMANOID_CLIPS.map(clip => clip.name)).toEqual(GLTF.animations.map(animation => animation.name));
    GLTF.animations.forEach((animation, index) => {
      const length = Math.max(...animation.samplers.map(sampler => GLTF.accessors[sampler.input].max?.[0] ?? 0));
      expect(HUMANOID_CLIPS[index].duration, animation.name).toBeCloseTo(length, 3);
    });
  });

  it('only moves bones of the skin, and turns most of them in every motion', () => {
    const joints = new Set(GLTF.skins[0].joints);
    const swordArm = GLTF.nodes.findIndex(node => node.name === 'rightUpperArm');
    GLTF.animations.forEach(animation => {
      expect(animation.channels.every(channel => joints.has(channel.target.node)), animation.name).toBe(true);
      // A bone a motion holds at rest has no channel in it, so not all 53 turn; a motion that turned only a few would be a broken copy.
      const turned = new Set(animation.channels.filter(channel => channel.target.path === 'rotation').map(channel => channel.target.node));
      expect(turned.size, animation.name).toBeGreaterThanOrEqual(40);
      expect(turned.has(swordArm), animation.name).toBe(true);
    });
  });

  it('gives every motion an id of its own and a posture the stage knows', () => {
    expect(new Set(HUMANOID_CLIPS.map(clip => clip.id)).size).toBe(HUMANOID_CLIPS.length);
    HUMANOID_CLIPS.forEach(clip => expect(posePosture(clip.posture), clip.id).toBe(clip.posture));
  });

  it('groups the motions for a picker without losing one, fighting motions among them', () => {
    expect(HUMANOID_CLIP_GROUPS.map(item => item.group)).toEqual(['站立', '移动', '蹲姿', '坐姿', '持剑', '拳脚', '受击', '腾跃']);
    expect(HUMANOID_CLIP_GROUPS.flatMap(item => item.clips)).toHaveLength(HUMANOID_CLIPS.length);
    expect(HUMANOID_CLIP_GROUPS.find(item => item.group === '持剑')!.clips.map(clip => clip.name)).toEqual(['持剑戒备', '挥剑劈砍', '持剑格挡', '持剑突刺', '回身重斩', '三连斩', '重击连招']);
    expect(humanoidClip('human-sword-combo-v1')).toMatchObject({ index: 15, loop: false, posture: 'fight' });
  });

  it('still falls back to the first ten for a posture and for an id it does not know', () => {
    expect(clipForPosture('run')).toBe('human-jog-v1');
    expect(clipForPosture('fight')).toBe('human-idle-v1');
    expect(humanoidClip('no-such-clip').id).toBe('human-idle-v1');
  });
});
