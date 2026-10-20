// @vitest-environment jsdom
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import { DICTIONARIES, acceptLanguage, getLocale, setLocale, t } from './index';

describe('interface language', () => {
  afterEach(() => setLocale('zh-CN'));

  it('reads Chinese by default, translates, and falls back to Chinese for anything untranslated', () => {
    expect(t('立即登录')).toBe('立即登录');
    setLocale('en');
    expect(t('立即登录')).toBe('Sign in');
    expect(t('一句还没有翻译的话')).toBe('一句还没有翻译的话');
    setLocale('vi');
    expect(t('立即登录')).toBe('Đăng nhập');
    expect(document.documentElement.lang).toBe('vi');
    expect(acceptLanguage()).toBe('vi,zh-CN;q=0.5');
  });

  it('fills numbered and named placeholders in every language', () => {
    expect(t('删除失败: {0}', ['网络错误'])).toBe('删除失败: 网络错误');
    expect(t('删除失败: {0}', ['network'], 'en')).toBe('Delete failed: network');
    expect(t('剧本文件不能超过 {0}MB', [20], 'vi')).toBe('Tệp kịch bản không được vượt quá 20MB');
    expect(t('共 {count} 项', { count: 3 })).toBe('共 3 项');
  });

  it('remembers the choice and ignores unknown languages', () => {
    setLocale('en');
    expect(window.localStorage.getItem('ui.locale')).toBe('en');
    setLocale('fr' as never);
    expect(getLocale()).toBe('en');
  });

  it('keeps every translation free of lost placeholders', () => {
    for (const dictionary of Object.values(DICTIONARIES)) {
      for (const [source, translated] of Object.entries(dictionary)) {
        const wanted = (source.match(/\{\w+\}/g) ?? []).sort();
        expect((translated.match(/\{\w+\}/g) ?? []).sort(), source).toEqual(wanted);
      }
    }
  });

  it('has an English and a Vietnamese entry for every text the converted screens use', () => {
    const script = resolve(__dirname, '../../scripts/i18n-coverage.mjs');
    expect(() => execFileSync('node', [script, '--check'], { stdio: 'pipe' })).not.toThrow();
  });
});
