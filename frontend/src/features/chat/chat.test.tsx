import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { type Snapshot, scopeKey } from '../../shared/api/client';
import { Chat } from './chat';

const empty: Snapshot = {
  chat: { id: 'a', task_id: 'task', title: 'Чат', created_at: '2026-11-26T00:00:00Z' },
  messages: [],
  runs: [],
};
let snapshot = empty;
const server = setupServer(http.get('/api/chats/a', () => HttpResponse.json(snapshot)));
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(() => {
  server.resetHandlers();
  snapshot = empty;
  sessionStorage.clear();
});
afterAll(() => server.close());
function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <Chat chatId="a" />
    </QueryClientProvider>,
  );
  return client;
}

it('preserves unsent input when server history is refreshed', async () => {
  const client = show();
  const input = await screen.findByRole('textbox', { name: 'Сообщение' });
  await userEvent.type(input, 'Несохранённый вопрос');
  await client.invalidateQueries({ queryKey: [...scopeKey, 'chat', 'a'] });
  expect(input).toHaveValue('Несохранённый вопрос');
});

it('restores the draft when a chat is reopened', async () => {
  sessionStorage.setItem('draft:a', 'Сохранённый черновик');
  show();
  expect(await screen.findByRole('textbox', { name: 'Сообщение' })).toHaveValue(
    'Сохранённый черновик',
  );
});

it('shows a send error and retries the same command without duplicating messages', async () => {
  const saved = { command_id: crypto.randomUUID(), content: 'Вопрос' };
  sessionStorage.setItem('pending:a', JSON.stringify(saved));
  const commands: unknown[] = [];
  server.use(
    http.post('/api/chats/a/runs', async ({ request }) => {
      const command: unknown = await request.json();
      commands.push(command);
      if (commands.length === 1) return HttpResponse.error();
      const run = {
        id: 'run',
        chat_id: 'a',
        assistant_message_id: 'answer',
        status: 'completed' as const,
        sequence: 2,
        content: 'Сохранённый ответ',
        incomplete: false,
        error_code: null,
        model: 'fake-chat',
      };
      snapshot = {
        ...empty,
        messages: [
          { id: 'question', role: 'user', content: 'Вопрос', position: 1, incomplete: false },
          {
            id: 'answer',
            role: 'assistant',
            content: 'Сохранённый ответ',
            position: 2,
            incomplete: false,
          },
        ],
        runs: [run],
      };
      return HttpResponse.json(run);
    }),
  );
  show();
  await userEvent.type(await screen.findByRole('textbox', { name: 'Сообщение' }), 'Вопрос');
  await userEvent.click(screen.getByRole('button', { name: 'Отправить сообщение' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось');
  await userEvent.click(screen.getByRole('button', { name: 'Повторить отправку' }));
  await waitFor(() => expect(screen.getByText('Сохранённый ответ')).toBeVisible());
  expect(commands).toHaveLength(2);
  expect(commands[0]).toEqual(saved);
  expect(commands[0]).toEqual(commands[1]);
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Сообщение' })).toHaveValue(''));
  expect(screen.getAllByText('Вопрос', { exact: true })).toHaveLength(1);
});
