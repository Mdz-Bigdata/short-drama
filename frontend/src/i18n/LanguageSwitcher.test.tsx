// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { setLocale, t, useLocale } from './index';
import { LanguageSwitcher } from './LanguageSwitcher';

function Greeting() {
  useLocale();
  return <p>{t('立即登录')}</p>;
}

describe('LanguageSwitcher', () => {
  afterEach(() => {
    cleanup();
    setLocale('zh-CN');
  });

  it('switches every subscribed component to the chosen language', async () => {
    render(<><LanguageSwitcher /><Greeting /></>);
    expect(screen.getByText('立即登录')).toBeTruthy();
    await userEvent.selectOptions(screen.getByLabelText('界面语言 / Language / Ngôn ngữ'), 'en');
    expect(screen.getByText('Sign in')).toBeTruthy();
    await userEvent.selectOptions(screen.getByLabelText('界面语言 / Language / Ngôn ngữ'), 'vi');
    expect(screen.getByText('Đăng nhập')).toBeTruthy();
  });
});
