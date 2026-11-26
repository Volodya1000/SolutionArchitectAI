import { describe, expect, it } from 'vitest';
import { applyRunSnapshot } from './stream';

const initial = {
  id: 'run-a',
  chat_id: 'chat-a',
  assistant_message_id: 'm',
  status: 'running',
  sequence: 3,
  content: 'Ответ',
  incomplete: true,
  error_code: null,
  model: 'fake-chat',
} as const;

describe('run snapshots', () => {
  it('ignores late events from another chat', () => {
    expect(
      applyRunSnapshot(initial, { ...initial, chat_id: 'chat-b', sequence: 4 }, 'chat-a'),
    ).toBe(initial);
  });
  it('ignores duplicate or older snapshots', () => {
    expect(
      applyRunSnapshot(initial, { ...initial, sequence: 2, content: 'старый' }, 'chat-a'),
    ).toBe(initial);
  });
  it('restores missing deltas using a newer persisted snapshot', () => {
    expect(
      applyRunSnapshot(initial, { ...initial, sequence: 8, content: 'Полный ответ' }, 'chat-a')
        .content,
    ).toBe('Полный ответ');
  });
});
