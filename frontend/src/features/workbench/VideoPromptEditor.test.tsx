// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { VideoPromptEditor } from './VideoPromptEditor';
import { parseMentions, resolveMentions, splitMentions } from './promptMentions';

const PROMPT = '【人物锚点·锁脸】@[姜照]、@[罗荧]。\n【场景锚点·锁场景】@[地府客服中心大厅]。\n画面：@[罗荧]走到@[姜照工位]前。';
const KINDS = { 姜照: 'actor', 罗荧: 'actor', 地府客服中心大厅: 'scene' };
const NUMBERS = { 姜照: 1, 罗荧: 2, 地府客服中心大厅: 3 };

describe('prompt mentions', () => {
  it('parses, splits and resolves @[name] the same way the backend does', () => {
    expect(parseMentions(PROMPT)).toEqual(['姜照', '罗荧', '地府客服中心大厅', '姜照工位']);
    expect(splitMentions('甲@[乙]丙').map(part => part.text).join('')).toBe('甲@[乙]丙');
    expect(splitMentions('甲@[乙]丙')[1]).toEqual({ text: '@[乙]', mention: '乙' });
    expect(resolveMentions('@[罗荧]走到@[姜照工位]前', NUMBERS)).toBe('罗荧（参考图2）走到姜照工位前');
  });
});

describe('VideoPromptEditor', () => {
  afterEach(cleanup);

  it('colours each mention by its asset kind', () => {
    const { container } = render(
      <VideoPromptEditor shotId={11} prompt={PROMPT} edited={false} mentionKinds={KINDS}
        referenceNumbers={NUMBERS} locked={false} saving={false} onSave={vi.fn()} />,
    );
    const marks = Array.from(container.querySelectorAll('mark.video-prompt-mention'));
    const classOf = (text: string) => marks.find(mark => mark.textContent === text)?.className;
    expect(classOf('@[姜照]')).toContain('is-actor');
    expect(classOf('@[地府客服中心大厅]')).toContain('is-scene');
    expect(classOf('@[姜照工位]')).toContain('is-unknown');
    expect(screen.getByRole('status').textContent).toContain('已同步');
  });

  it('saves an edit and can restore the compiled prompt', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    const { rerender } = render(
      <VideoPromptEditor shotId={11} prompt={PROMPT} edited={false} mentionKinds={KINDS}
        referenceNumbers={NUMBERS} locked={false} saving={false} onSave={onSave} />,
    );
    const save = screen.getByRole('button', { name: /保存/ });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('视频提示词文稿'), { target: { value: `${PROMPT}@[罗荧]回头。` } });
    expect(screen.getByRole('status').textContent).toContain('未保存');
    await user.click(save);
    expect(onSave).toHaveBeenCalledWith(`${PROMPT}@[罗荧]回头。`);

    rerender(
      <VideoPromptEditor key="saved" shotId={11} prompt={`${PROMPT}@[罗荧]回头。`} edited mentionKinds={KINDS}
        referenceNumbers={NUMBERS} locked={false} saving={false} onSave={onSave} />,
    );
    expect(screen.getByRole('status').textContent).toContain('已人工修改');
    await user.click(screen.getByRole('button', { name: /恢复自动编译/ }));
    expect(onSave).toHaveBeenLastCalledWith(null);
  });

  it('previews which reference image each name binds to and the text the model receives', async () => {
    const user = userEvent.setup();
    render(
      <VideoPromptEditor shotId={11} prompt={PROMPT} edited={false} mentionKinds={KINDS}
        referenceNumbers={NUMBERS} locked={false} saving={false} onSave={vi.fn()} />,
    );
    await user.click(screen.getByRole('tab', { name: '解析预览' }));
    const assets = screen.getByRole('list', { name: '引用的资产' });
    expect(within(assets).getByText('参考图 3')).toBeTruthy();
    expect(within(assets).getByText('无参考图，只保留名字')).toBeTruthy();
    expect(screen.getByText(/罗荧（参考图2）走到姜照工位前/)).toBeTruthy();
  });

  it('cannot be edited while a stage is running', () => {
    render(
      <VideoPromptEditor shotId={11} prompt={PROMPT} edited={false} mentionKinds={KINDS}
        referenceNumbers={NUMBERS} locked saving={false} onSave={vi.fn()} />,
    );
    expect((screen.getByLabelText('视频提示词文稿') as HTMLTextAreaElement).disabled).toBe(true);
  });
});
