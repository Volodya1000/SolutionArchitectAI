import { expect, it } from 'vitest';
import { messageSchema } from './client';
import { fixtureId } from './test-network-fixtures';

it.each(['system', 'user', 'assistant'])('accepts the backend message role %s', (role) => {
  expect(
    messageSchema.parse({
      id: fixtureId('message'),
      role,
      content: 'Text',
      position: 1,
      incomplete: false,
    }).role,
  ).toBe(role);
});

it('rejects an incompatible assistant role at the HTTP boundary', () => {
  expect(
    messageSchema.safeParse({
      id: fixtureId('message'),
      role: 'bot',
      content: 'Text',
      position: 1,
      incomplete: false,
    }).success,
  ).toBe(false);
});
