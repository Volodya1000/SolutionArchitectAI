import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter } from 'react-router';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { ThemeProvider } from '../shared/ui/theme-provider';
import { Workspace } from './workspace';

const savedChat = {
  id: 'saved',
  task_id: 'task',
  title: 'Обсуждение сервиса',
  created_at: '2026-11-26T00:00:00Z',
};
const server = setupServer(
  http.get('/api/chats', () => HttpResponse.json([savedChat])),
  http.get('/api/model', () => HttpResponse.json({ model: 'fake-chat', available: true })),
  http.get('/api/preferences', () => HttpResponse.json({ theme: 'system' })),
);

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(() => {
  server.resetHandlers();
  localStorage.clear();
  document.documentElement.classList.remove('dark');
});
afterAll(() => server.close());

function showWorkspace() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <MemoryRouter>
          <Workspace />
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

it('shows loading states and saved chat navigation when the model is unavailable', async () => {
  let respond = () => {};
  const pending = new Promise<void>((resolve) => {
    respond = resolve;
  });
  server.use(
    http.get('/api/chats', async () => {
      await pending;
      return HttpResponse.json([savedChat]);
    }),
    http.get('/api/model', async () => {
      await pending;
      return HttpResponse.json({ model: 'fake-chat', available: false });
    }),
  );

  showWorkspace();

  expect(screen.getByText('Загружаем чаты…')).toBeVisible();
  expect(screen.getByText('Проверяем API модели…')).toBeVisible();
  respond();
  expect(await screen.findByText('Модель недоступна')).toBeVisible();
  expect(await screen.findByRole('link', { name: savedChat.title })).toBeVisible();
});

it('retries a failed chat list request from the sidebar', async () => {
  let available = false;
  server.use(
    http.get('/api/chats', () =>
      available ? HttpResponse.json([savedChat]) : new HttpResponse(null, { status: 503 }),
    ),
  );

  showWorkspace();

  const navigation = within(screen.getByRole('navigation', { name: 'Чаты' }));
  expect(await navigation.findByRole('alert')).toHaveTextContent('Не удалось загрузить чаты.');
  available = true;
  await userEvent.click(navigation.getByRole('button', { name: 'Повторить' }));
  expect(await navigation.findByRole('link', { name: savedChat.title })).toBeVisible();
  expect(navigation.queryByRole('alert')).not.toBeInTheDocument();
});

it('keeps the current workspace available when creating a chat fails', async () => {
  server.use(http.post('/api/chats', () => new HttpResponse(null, { status: 503 })));

  showWorkspace();

  const saved = await screen.findByRole('link', { name: savedChat.title });
  const create = screen.getByRole('button', { name: 'Новый чат' });
  await userEvent.click(create);
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось выполнить запрос.');
  expect(create).toBeEnabled();
  expect(saved).toBeVisible();
  expect(screen.getByRole('heading', { name: 'Место для продуманных решений' })).toBeVisible();
});

it('keeps the selected theme locally when the server cannot save it', async () => {
  server.use(http.put('/api/preferences', () => new HttpResponse(null, { status: 503 })));

  showWorkspace();

  const theme = screen.getByRole('combobox', { name: 'Тема' });
  await userEvent.selectOptions(theme, 'dark');
  expect(await screen.findByText(/Выбор сохранён на устройстве/)).toBeVisible();
  expect(theme).toHaveValue('dark');
  expect(document.documentElement).toHaveClass('dark');
  expect(localStorage.getItem('saa-theme')).toBe('dark');
});
