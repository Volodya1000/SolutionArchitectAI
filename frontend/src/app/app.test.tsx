import { fixtureId } from '@/shared/api/test-network-fixtures';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { App } from './app';

const original = {
  id: fixtureId('saved-chat'),
  task_id: fixtureId('task'),
  title: 'Сохранённый диалог',
  created_at: '2026-11-26T00:00:00Z',
};
const created = { ...original, id: fixtureId('new-chat'), title: 'Диалог 2' };
const server = setupServer(
  http.get('/api/preferences', () => HttpResponse.json({ theme: 'system' })),
  http.get('/api/model', () => HttpResponse.json({ model: 'fake-chat', available: true })),
  http.get('/api/chats/:id/discussion', () => HttpResponse.json(null)),
);

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(() => {
  server.resetHandlers();
  window.history.replaceState(null, '', '/');
});
afterAll(() => server.close());

it('opens a saved chat by URL and navigates to a newly created conversation', async () => {
  const chats = [original];
  let submitted: unknown;
  let completeCreation = () => {};
  const creation = new Promise<void>((resolve) => {
    completeCreation = resolve;
  });
  server.use(
    http.get('/api/chats', () => HttpResponse.json(chats)),
    http.get('/api/chats/:chatId', ({ params }) => {
      const chat = chats.find(({ id }) => id === params.chatId);
      if (!chat) return new HttpResponse(null, { status: 404 });
      return HttpResponse.json({
        chat,
        runs: [],
        messages:
          chat.id === original.id
            ? [
                {
                  id: fixtureId('saved-message'),
                  role: 'user',
                  content: 'Согласуем границы сервиса',
                  position: 1,
                  incomplete: false,
                },
              ]
            : [],
      });
    }),
    http.post('/api/chats', async ({ request }) => {
      submitted = await request.json();
      await creation;
      chats.push(created);
      return HttpResponse.json(created, { status: 201 });
    }),
  );
  window.history.replaceState(null, '', `/chats/${fixtureId('saved-chat')}`);

  render(<App />);

  expect(await screen.findByText('Согласуем границы сервиса')).toBeVisible();
  expect(screen.getByRole('link', { name: original.title })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await userEvent.click(screen.getByRole('link', { name: /SolutionArchitect/ }));
  expect(screen.getByRole('heading', { name: 'Место для продуманных решений' })).toBeVisible();

  const start = screen.getByRole('button', { name: 'Начать обсуждение' });
  await userEvent.click(start);
  await waitFor(() => expect(start).toBeDisabled());
  expect(screen.getByRole('button', { name: 'Новый чат' })).toBeDisabled();
  completeCreation();

  expect(await screen.findByRole('heading', { name: 'Рабочий чат' })).toBeVisible();
  expect(submitted).toEqual({ title: created.title });
  await waitFor(() =>
    expect(screen.getByRole('link', { name: created.title })).toHaveAttribute(
      'aria-current',
      'page',
    ),
  );
  expect(window.location.pathname).toBe(`/chats/${fixtureId('new-chat')}`);
  expect(await screen.findByRole('textbox', { name: 'Сообщение' })).toBeVisible();
  expect(screen.queryByText('Согласуем границы сервиса')).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole('link', { name: original.title }));
  expect(await screen.findByText('Согласуем границы сервиса')).toBeVisible();
  expect(window.location.pathname).toBe(`/chats/${fixtureId('saved-chat')}`);
});
