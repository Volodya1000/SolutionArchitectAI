import { afterEach, expect, it, vi } from 'vitest';
import { request, chatSchema, messageSchema } from './client';
import { discussionCommandSchema } from './discussions';
import { fixtureId } from './test-network-fixtures';
import { zExtractionStart, zSourceSubject } from './generated/zod.gen';

afterEach(() => vi.unstubAllGlobals());

const chat = {
  id: fixtureId('chat'),
  task_id: fixtureId('task'),
  title: 'Saved chat',
  created_at: '2026-11-28T12:00:00+03:00',
};

it.each([{ id: 'invalid UUID' }, { created_at: 'not-a-date' }])(
  'rejects invalid HTTP response fields before returning data: %o',
  async (invalid) => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...chat, ...invalid }))),
    );
    await expect(request('/chats/example', chatSchema)).rejects.toThrow();
  },
);

it('accepts ISO timezone offsets and preserves optional, nullable, enum and union contracts', () => {
  expect(chatSchema.parse(chat).created_at).toBe(chat.created_at);
  const command = { operation_id: fixtureId('operation'), version_ids: [fixtureId('version')] };
  expect(zExtractionStart.parse(command).analysis_scope).toBe('');
  expect(
    zExtractionStart.parse({ ...command, answer_history_id: null }).answer_history_id,
  ).toBeNull();
  expect(zExtractionStart.safeParse({ ...command, answer_history_mode: 'unknown' }).success).toBe(
    false,
  );
  expect(
    zSourceSubject.parse({
      kind: 'source',
      version_id: fixtureId('version'),
      fragment_id: fixtureId('fragment'),
    }).analysis_id,
  ).toBeUndefined();
  expect(
    discussionCommandSchema.safeParse({
      operation_id: fixtureId('operation'),
      subject: { kind: 'requirement', run_id: fixtureId('run') },
    }).success,
  ).toBe(false);
  expect(
    messageSchema.safeParse({
      id: fixtureId('message'),
      role: 'unknown',
      content: '',
      position: 0,
      incomplete: false,
    }).success,
  ).toBe(false);
});
