// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import MuseumAssetExperience from './MuseumAssetExperience';
import { museumCatalog } from './museumCatalog';


beforeEach(() => {
  Object.defineProperty(window, 'WebGL2RenderingContext', {
    configurable: true,
    value: undefined,
  });
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});


describe('MuseumAssetExperience', () => {
  it('migrates all eight artifacts, 24 questions, sources and namespaced assets', () => {
    expect(museumCatalog).toHaveLength(8);
    expect(museumCatalog.map(item => item.name)).toEqual([
      '猫头鹰尊',
      '三星堆青铜面具',
      '青铜鼎',
      '兵马俑',
      '唐三彩马',
      '永乐佛像',
      '青花瓷瓶',
      '青铜瑞兽香炉',
    ]);
    expect(museumCatalog.reduce((total, item) => total + (item.qa?.length ?? 0), 0)).toBe(24);
    museumCatalog.forEach(item => {
      expect(item.story?.length).toBeGreaterThan(100);
      expect(item.modelAsset.url.startsWith('/museum/models/')).toBe(true);
      expect(item.thumbnail.startsWith('/museum/thumbnails/')).toBe(true);
      expect(item.modelAsset.sourceLabel.length).toBeGreaterThan(0);
      expect(item.modelAsset.sourceUrl.startsWith('https://')).toBe(true);
      expect(item.modelAsset.scale).toBeGreaterThan(0);
    });
  });

  it('switches artifacts and updates the plaque and detail labels', () => {
    render(<MuseumAssetExperience kind="prop" />);

    fireEvent.click(screen.getByRole('button', { name: '切换到三星堆青铜面具' }));

    expect(screen.getByRole('heading', { name: '三星堆青铜面具' })).toBeTruthy();
    expect(screen.getByText('纵目巨耳')).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: '查看细节：双耳' }));
    expect(screen.getByText('招风巨耳')).toBeTruthy();

    const favorite = screen.getByRole('button', { name: '收藏三星堆青铜面具' });
    fireEvent.click(favorite);
    expect(favorite.getAttribute('aria-pressed')).toBe('true');
  });

  it('reveals answers, stories and the selected model source link', () => {
    render(<MuseumAssetExperience kind="scene" />);

    expect(screen.getByText(/三千多年前的某个夜晚/)).toBeTruthy();
    const question = screen.getByRole('button', {
      name: '为什么商朝人偏偏选猫头鹰，而不是别的鸟？',
    });
    fireEvent.click(question);
    expect(screen.getByText(/商代，猫头鹰（鸮）是被崇拜的神鸟/)).toBeTruthy();

    expect(screen.getByText('模型来源：Minneapolis Institute of Art')).toBeTruthy();
    const source = screen.getByRole('link', { name: /查看 3D 模型来源/ });
    expect(source.getAttribute('href')).toBe(museumCatalog[0].modelAsset.sourceUrl);
    expect(source.getAttribute('target')).toBe('_blank');
  });
});
