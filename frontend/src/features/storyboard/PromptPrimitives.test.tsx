// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { PromptFields } from './PromptPrimitives';


describe('PromptFields', () => {
  afterEach(cleanup);

  it('renders an inline Markdown character summary as a two-dimensional table', () => {
    const summary = '总表：| character_id | 姓名 | 身份 | 主要状态 | 主色 | 声音 ID | |---|---|---|---|---|---| | char_001 | 沈川（原现代名沈川，字行舟） | 现代文学系博士 / 魏晋流浪乞儿 / 后为宰执 | modern, beggar_child, youth_scholar, chancellor | 青灰 8A9BA8 / 米白 EDE6D6 | VC_ShenChuan | | char_002 | 崔玦（字玄珪） | 清河崔氏嫡子 / 权臣 | heir, statesman | 玄黑 1F1F2A / 朱红 A93226 / 金 C9A86A | VC_CuiJue |';

    render(<PromptFields value={{ appearance: summary }} />);

    const table = screen.getByRole('table', { name: '外貌' });
    const scoped = within(table);
    expect(scoped.getByRole('columnheader', { name: 'character_id' })).toBeTruthy();
    expect(scoped.getByRole('columnheader', { name: '声音 ID' })).toBeTruthy();
    expect(scoped.getByRole('cell', { name: 'char_001' })).toBeTruthy();
    expect(scoped.getByRole('cell', { name: 'VC_CuiJue' })).toBeTruthy();
    expect(scoped.getAllByRole('row')).toHaveLength(3);
    expect(screen.queryByText(summary)).toBeNull();
  });

  it('keeps ordinary field text unchanged', () => {
    render(<PromptFields value={{ appearance: '黑色马尾，面部清秀' }} />);

    expect(screen.getByText('黑色马尾，面部清秀')).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
  });
});
