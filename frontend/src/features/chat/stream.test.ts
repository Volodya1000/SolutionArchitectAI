import { fixtureId } from '@/shared/api/test-network-fixtures';
import { describe, expect, it } from 'vitest';
import { applyRunSnapshot } from './stream';

const initial = {
  config_digest: 'test-config',
  created_at: '2026-01-01T00:00:00Z',

  id: fixtureId('run-a'),
  chat_id: fixtureId('chat-a'),
  assistant_message_id: fixtureId('m'),
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
      applyRunSnapshot(
        initial,
        { ...initial, chat_id: fixtureId('chat-b'), sequence: 4 },
        fixtureId('chat-a'),
      ),
    ).toEqual(initial);
  });
  it.each([2, 3])(
    'preserves displayed text for sequence %i and accepts a newer event',
    (sequence) => {
      const preserved = applyRunSnapshot(
        initial,
        { ...initial, sequence, content: 'чужое содержимое' },
        fixtureId('chat-a'),
      );
      expect(preserved).toEqual(initial);
      expect(preserved.content).toBe('Ответ');
      expect(
        applyRunSnapshot(
          preserved,
          { ...initial, sequence: 4, content: 'Продолжение ответа' },
          fixtureId('chat-a'),
        ).content,
      ).toBe('Продолжение ответа');
    },
  );
  it('restores missing deltas using a newer persisted snapshot', () => {
    expect(
      applyRunSnapshot(
        initial,
        { ...initial, sequence: 8, content: 'Полный ответ' },
        fixtureId('chat-a'),
      ).content,
    ).toBe('Полный ответ');
  });
});
