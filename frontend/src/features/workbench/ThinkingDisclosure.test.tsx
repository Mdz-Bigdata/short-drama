// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { TaskResponse } from '../../types';
import { ThinkingDisclosure } from './ThinkingDisclosure';
import { restoreWorkflowHistory } from './workflowMessages';

afterEach(cleanup);

describe('ThinkingDisclosure', () => {
  it('is folded until opened and says it is only reference', () => {
    const { container } = render(<ThinkingDisclosure text={'  先读项目状态\n再回答  '} />);
    const details = container.querySelector('details')!;
    expect(details.open).toBe(false);
    fireEvent.click(screen.getByText('思考过程'));
    expect(details.open).toBe(true);
    expect(container.querySelector('.thinking-disclosure__body')!.textContent).toBe('先读项目状态\n再回答');
    expect(screen.getByText(/仅供参考/)).toBeTruthy();
  });

  it('shows nothing when the model returned no thinking', () => {
    for (const text of [undefined, '', '   ']) {
      const { container } = render(<ThinkingDisclosure text={text} />);
      expect(container.innerHTML).toBe('');
      cleanup();
    }
  });
});

describe('restoreWorkflowHistory', () => {
  it('carries the stored thinking onto the assistant bubble only', () => {
    const task = {
      taskId: 't',
      chatHistory: [
        { id: '1', role: 'user', content: '/agent 看看', reasoning: 'not from a person' },
        { id: '2', role: 'assistant', content: '项目在第一步', reasoning: '先读项目状态' },
        { id: '3', role: 'assistant', content: '好' },
      ],
    } as unknown as TaskResponse;
    const [asked, answered, plain] = restoreWorkflowHistory(task);
    expect(asked.reasoning).toBeUndefined();
    expect(answered.reasoning).toBe('先读项目状态');
    expect('reasoning' in plain).toBe(false);
  });
});
