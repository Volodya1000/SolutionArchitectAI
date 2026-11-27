import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest';
import { type Snapshot, scopeKey } from '../../shared/api/client';
import { Chat } from './chat';
import { sessionStore } from '../../shared/ui/session-storage';

const empty: Snapshot = {
  chat: { id: 'a', task_id: 'task', title: 'Чат', created_at: '2026-11-26T00:00:00Z' },
  messages: [],
  runs: [],
};
let snapshot = empty;
function acceptQuestion() {
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
  return run;
}

const server = setupServer(http.get('/api/chats/a', () => HttpResponse.json(snapshot)));
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(() => {
  vi.restoreAllMocks();
  server.resetHandlers();
  snapshot = empty;
  sessionStore.clear();
});

it('keeps the conversation and composer visible after a background history error', async () => {
  acceptQuestion();
  const { client } = show();
  await screen.findByText('Сохранённый ответ');
  const input = screen.getByRole('textbox', { name: 'Сообщение' });
  await userEvent.type(input, 'Черновик');
  server.use(http.get('/api/chats/a', () => new HttpResponse(null, { status: 503 })));
  await client.invalidateQueries({ queryKey: [...scopeKey, 'chat', 'a'] });
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось обновить историю');
  expect(screen.getByText('Сохранённый ответ')).toBeVisible();
  expect(input).toHaveValue('Черновик');
});

it.each(['getItem', 'setItem', 'removeItem'] as const)(
  'sends and reopens drafts when session storage %s throws',
  async (method) => {
    vi.spyOn(Storage.prototype, method).mockImplementation(() => {
      throw new Error('Storage denied');
    });
    server.use(http.post('/api/chats/a/runs', () => HttpResponse.json(acceptQuestion())));
    const view = show();
    const input = await screen.findByRole('textbox', { name: 'Сообщение' });
    await userEvent.type(input, 'Вопрос');
    view.unmount();
    const reopened = show();
    expect(await screen.findByRole('textbox', { name: 'Сообщение' })).toHaveValue('Вопрос');
    await userEvent.click(screen.getByRole('button', { name: 'Отправить сообщение' }));
    expect(await screen.findByText('Сохранённый ответ')).toBeVisible();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    reopened.unmount();
  },
);
afterAll(() => server.close());
function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <Chat chatId="a" />
    </QueryClientProvider>,
  );
  return { client, ...view };
}

it('disables sending until the draft contains text', async () => {
  show();
  const input = await screen.findByRole('textbox', { name: 'Сообщение' });
  const send = screen.getByRole('button', { name: 'Отправить сообщение' });
  expect(send).toBeDisabled();
  await userEvent.type(input, '   ');
  expect(send).toBeDisabled();
  await userEvent.type(input, 'Вопрос');
  expect(send).toBeEnabled();
  await userEvent.clear(input);
  expect(send).toBeDisabled();
});

it('preserves unsent input when server history is refreshed', async () => {
  const { client } = show();
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

it.each(['unchanged', 'before retry', 'during retry'])(
  'retries the same command and preserves a draft edited %s',
  async (edit) => {
    const saved = { command_id: crypto.randomUUID(), content: 'Вопрос' };
    sessionStorage.setItem('pending:a', JSON.stringify(saved));
    const commands: unknown[] = [];
    let confirm = () => {};
    const confirmation = new Promise<void>((resolve) => {
      confirm = resolve;
    });
    server.use(
      http.post('/api/chats/a/runs', async ({ request }) => {
        const command: unknown = await request.json();
        commands.push(command);
        if (commands.length === 1) return HttpResponse.error();
        if (edit === 'during retry') await confirmation;
        return HttpResponse.json(acceptQuestion());
      }),
    );
    show();
    await userEvent.type(await screen.findByRole('textbox', { name: 'Сообщение' }), 'Вопрос');
    await userEvent.click(screen.getByRole('button', { name: 'Отправить сообщение' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось');
    const input = screen.getByRole('textbox', { name: 'Сообщение' });
    if (edit === 'before retry') {
      await userEvent.clear(input);
      await userEvent.type(input, 'Новый вопрос');
    }
    await userEvent.click(screen.getByRole('button', { name: 'Повторить отправку' }));
    if (edit === 'during retry') {
      await userEvent.clear(input);
      await userEvent.type(input, 'Новый вопрос');
      await userEvent.keyboard('{Enter}');
      expect(commands).toHaveLength(2);
      confirm();
    }
    await waitFor(() => expect(screen.getByText('Сохранённый ответ')).toBeVisible());
    expect(commands).toHaveLength(2);
    expect(commands[0]).toEqual(saved);
    expect(commands[0]).toEqual(commands[1]);
    const expectedDraft = edit === 'unchanged' ? '' : 'Новый вопрос';
    await waitFor(() => expect(input).toHaveValue(expectedDraft));
    expect(sessionStorage.getItem('draft:a') ?? '').toBe(expectedDraft);
    expect(screen.getAllByText('Вопрос', { exact: true })).toHaveLength(1);
  },
);

it('keeps cancellation attached to its answer after a later completed run', async () => {
  const runs: Snapshot['runs'] = [
    {
      id: 'cancelled',
      chat_id: 'a',
      assistant_message_id: 'partial',
      status: 'cancelled',
      sequence: 3,
      content: 'Неполный список рисков',
      incomplete: true,
      error_code: null,
      model: 'fake-chat',
    },
    {
      id: 'completed',
      chat_id: 'a',
      assistant_message_id: 'complete',
      status: 'completed',
      sequence: 8,
      content: 'Полный ответ',
      incomplete: false,
      error_code: null,
      model: 'fake-chat',
    },
  ];
  snapshot = {
    ...empty,
    messages: runs.map((run, index) => ({
      id: run.assistant_message_id,
      role: 'assistant',
      content: run.content,
      position: index + 1,
      incomplete: run.incomplete,
    })),
    runs,
  };
  show();
  await screen.findByText('Неполный список рисков');
  const answers = screen.getAllByRole('article', { name: 'Ответ ассистента' });
  expect(within(answers[0]!).getByRole('status')).toHaveTextContent('Генерация отменена');
  expect(within(answers[1]!).getByRole('status')).toHaveTextContent('Ответ завершён');
});

it.each(['Я', '😀'])('accepts exactly 16000 Unicode characters (%s)', async (character) => {
  show();
  const input = await screen.findByRole('textbox', { name: 'Сообщение' });
  fireEvent.change(input, { target: { value: character.repeat(16000) } });
  expect(screen.getByRole('button', { name: 'Отправить сообщение' })).toBeEnabled();
  expect(input).toHaveAttribute('aria-invalid', 'false');
});

it('keeps oversized input and explains the limit before sending', async () => {
  let requests = 0;
  server.use(
    http.post('/api/chats/a/runs', () => {
      requests++;
      return HttpResponse.json({}, { status: 422 });
    }),
  );
  show();
  const input = await screen.findByRole('textbox', { name: 'Сообщение' });
  const text = 'Я'.repeat(16001);
  fireEvent.change(input, { target: { value: text } });
  await userEvent.keyboard('{Enter}');
  expect(screen.getByRole('button', { name: 'Отправить сообщение' })).toBeDisabled();
  expect(screen.getByRole('alert')).toHaveTextContent('16 000');
  expect(input).toHaveValue(text);
  expect(sessionStorage.getItem('draft:a')).toBe(text);
  expect(requests).toBe(0);
});

it('explains server validation without losing the question', async () => {
  server.use(
    http.post('/api/chats/a/runs', () =>
      HttpResponse.json(
        {
          detail: [
            { loc: ['body', 'content'], type: 'string_too_long', ctx: { max_length: 16000 } },
          ],
        },
        { status: 422 },
      ),
    ),
  );
  show();
  const input = await screen.findByRole('textbox', { name: 'Сообщение' });
  await userEvent.type(input, 'Сохранить мой вопрос');
  await userEvent.click(screen.getByRole('button', { name: 'Отправить сообщение' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('16 000');
  expect(input).toHaveValue('Сохранить мой вопрос');
  expect(sessionStorage.getItem('draft:a')).toBe('Сохранить мой вопрос');
});

it.each(['unchanged', 'edited'])(
  'acknowledges a retry after leaving the chat, preserving only an %s draft',
  async (edit) => {
    let count = 0;
    let confirm = () => {};
    const confirmation = new Promise<void>((resolve) => {
      confirm = resolve;
    });
    server.use(
      http.post('/api/chats/a/runs', async () => {
        if (++count === 1) return HttpResponse.error();
        await confirmation;
        return HttpResponse.json(acceptQuestion());
      }),
    );
    const view = show();
    const input = await screen.findByRole('textbox', { name: 'Сообщение' });
    await userEvent.type(input, 'Вопрос');
    await userEvent.click(screen.getByRole('button', { name: 'Отправить сообщение' }));
    await screen.findByRole('alert');
    if (edit === 'edited') {
      await userEvent.clear(input);
      await userEvent.type(input, 'Новый черновик');
    }
    await userEvent.click(screen.getByRole('button', { name: 'Повторить отправку' }));
    await waitFor(() => expect(count).toBe(2));
    view.unmount();
    confirm();
    await waitFor(() => expect(sessionStorage.getItem('pending:a')).toBeNull());
    show();
    expect(await screen.findByRole('textbox', { name: 'Сообщение' })).toHaveValue(
      edit === 'edited' ? 'Новый черновик' : '',
    );
    expect(snapshot.runs).toHaveLength(1);
  },
);
