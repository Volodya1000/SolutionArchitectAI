import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { Link, MemoryRouter, Route, Routes } from 'react-router';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { sessionStore } from '../../shared/ui/session-storage';
import { Documents } from './documents';

const version = {
  file_id: 'file',
  task_id: 'task',
  version_id: 'v1',
  sha256: 'abc',
  mime_type: 'text/markdown',
  size: 3,
  original_name: 'BRD.md',
  uploaded_at: '2026-11-27T12:00:00Z',
};
const run = {
  id: 'run',
  status: 'completed',
  progress: { completed_parts: 1, total_parts: 1 },
  error_code: null,
  created_at: '2026-11-27T12:00:00Z',
  model: 'fake',
  version_ids: ['v1'],
  analysis_scope: '',
  configuration_current: true,
  coverage: { complete: true, total_fragments: 1, processed_fragments: 1 },
  requirements: [],
};
const server = setupServer(
  http.get('/api/documents', () =>
    HttpResponse.json([
      {
        file_id: 'file',
        task_id: 'task',
        name: 'BRD.md',
        created_at: version.uploaded_at,
        latest_version: version,
      },
    ]),
  ),
  http.get('/api/documents/:id/versions', () => HttpResponse.json([version])),
  http.get('/api/extractions/matching', () =>
    HttpResponse.json({ active: null, current_completed: null, latest_completed: null }),
  ),
  http.get('/api/extractions/history', () => HttpResponse.json({ items: [], has_more: false })),
  http.get('/api/document-uploads/:id', () => new HttpResponse(null, { status: 404 })),
  http.get('/api/extraction-operations/:id', () => new HttpResponse(null, { status: 404 })),
);
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterAll(() => server.close());
afterEach(() => {
  server.resetHandlers();
  sessionStore.clear();
});

function show(path = '/documents') {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[path]}>
        <Link to="/documents">К документам</Link>
        <Link to="/other">Другой раздел</Link>
        <Routes>
          <Route path="/documents" element={<Documents />} />
          <Route path="*" element={<div>Другой экран</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it('keeps selected versions and analysis instructions after navigation and a fresh mount', async () => {
  const view = show();
  await userEvent.click(
    await screen.findByRole('checkbox', { name: 'Выбрать последнюю версию BRD.md' }),
  );
  await userEvent.click(screen.getByText('Уточнить анализ'));
  await userEvent.type(
    screen.getByLabelText('На что обратить внимание (необязательно)'),
    'Безопасность',
  );
  await userEvent.click(screen.getByText('Другой раздел'));
  await userEvent.click(screen.getByText('К документам'));
  expect(
    await screen.findByRole('checkbox', { name: 'Выбрать последнюю версию BRD.md' }),
  ).toBeChecked();
  expect(screen.getByLabelText('На что обратить внимание (необязательно)')).toHaveValue(
    'Безопасность',
  );
  view.unmount();
  show();
  expect(
    await screen.findByRole('checkbox', { name: 'Выбрать последнюю версию BRD.md' }),
  ).toBeChecked();
  expect(screen.getByLabelText('На что обратить внимание (необязательно)')).toHaveValue(
    'Безопасность',
  );
});

it('loads version history only after its card is expanded', async () => {
  let reads = 0;
  server.use(
    http.get('/api/documents/:id/versions', () => {
      reads++;
      return HttpResponse.json([version]);
    }),
  );
  show();
  await screen.findByRole('checkbox', { name: 'Выбрать последнюю версию BRD.md' });
  expect(reads).toBe(0);
  await userEvent.click(screen.getByRole('button', { name: 'История версий BRD.md' }));
  await screen.findByRole('checkbox', { name: 'Анализировать BRD.md · v1' });
  expect(reads).toBe(1);
});

it('starts a fresh clarification history without opening a previously completed analysis', async () => {
  const payloads: unknown[] = [];
  server.use(
    http.get('/api/extractions/matching', () =>
      HttpResponse.json({ active: null, current_completed: run, latest_completed: run }),
    ),
    http.post('/api/extractions', async ({ request }) => {
      payloads.push(await request.json());
      return HttpResponse.json(run);
    }),
  );
  show();
  await userEvent.click(
    await screen.findByRole('checkbox', { name: 'Выбрать последнюю версию BRD.md' }),
  );
  await screen.findByRole('link', { name: /Открыть/ });
  await userEvent.click(
    screen.getByRole('checkbox', { name: 'Начать с новой историей уточнений' }),
  );
  await userEvent.click(await screen.findByRole('button', { name: 'Извлечь требования' }));
  await waitFor(() => expect(payloads).toHaveLength(1));
  expect(payloads[0]).toMatchObject({
    answer_history_mode: 'new',
    answer_history_id: null,
    version_ids: ['v1'],
  });
});

it('reuses the explicitly selected analysis history for a new analysis', async () => {
  const payloads: unknown[] = [];
  server.use(
    http.get('/api/extractions/context/clarifications', () =>
      HttpResponse.json({
        run_id: 'context',
        history_id: 'history-b',
        cycle: 0,
        initialized: true,
        resume_pending: false,
        requirements: [],
        questions: [],
        decisions: [],
        risks: [],
        completed_cycles: [],
      }),
    ),
    http.post('/api/extractions', async ({ request }) => {
      payloads.push(await request.json());
      return HttpResponse.json(run);
    }),
  );
  show('/documents?run=context');
  await userEvent.click(
    await screen.findByRole('checkbox', { name: 'Выбрать последнюю версию BRD.md' }),
  );
  await userEvent.click(await screen.findByRole('button', { name: 'Извлечь требования' }));
  await waitFor(() => expect(payloads).toHaveLength(1));
  expect(payloads[0]).toMatchObject({
    answer_history_mode: 'reuse',
    answer_history_id: 'history-b',
  });
});

it('recovers an accepted upload after reopening without uploading the bytes again', async () => {
  let uploads = 0;
  let operation = '';
  server.use(
    http.post('/api/documents', ({ request }) => {
      uploads++;
      operation = new URL(request.url).searchParams.get('operation_id') ?? '';
      return HttpResponse.error();
    }),
  );
  const view = show();
  await userEvent.upload(screen.getByLabelText('Новый документ'), new File(['BRD'], 'BRD.md'));
  await userEvent.click(await screen.findByRole('button', { name: 'Загрузить документ' }));
  await screen.findByRole('alert');
  view.unmount();
  server.use(
    http.get('/api/document-uploads/:id', ({ params }) => {
      expect(params.id).toBe(operation);
      return HttpResponse.json({ operation_id: operation, stage: 'completed', version });
    }),
  );
  show();
  expect(
    await screen.findByText('Версия сохранена. Ранее загруженные версии доступны в истории.'),
  ).toBeVisible();
  expect(uploads).toBe(1);
});

it('checks a reselected file and retries an unresolved upload with the saved operation ID', async () => {
  const operations: string[] = [];
  server.use(
    http.post('/api/documents', ({ request }) => {
      operations.push(new URL(request.url).searchParams.get('operation_id') ?? '');
      return operations.length === 1 ? HttpResponse.error() : HttpResponse.json(version);
    }),
  );
  const view = show();
  await userEvent.upload(screen.getByLabelText('Новый документ'), new File(['BRD'], 'BRD.md'));
  await userEvent.click(await screen.findByRole('button', { name: 'Загрузить документ' }));
  await screen.findByRole('alert');
  view.unmount();
  show();
  await waitFor(() => expect(screen.getByLabelText('Новый документ')).toBeEnabled());
  await userEvent.upload(screen.getByLabelText('Новый документ'), new File(['BAD'], 'BRD.md'));
  expect(await screen.findByRole('alert')).toHaveTextContent('Выберите тот же файл');
  expect(operations).toHaveLength(1);
  await userEvent.upload(screen.getByLabelText('Новый документ'), new File(['BRD'], 'BRD.md'));
  await userEvent.click(await screen.findByRole('button', { name: 'Повторить загрузку' }));
  await waitFor(() => expect(operations).toHaveLength(2));
  expect(operations[1]).toBe(operations[0]);
});

it('recovers the exact extraction operation after reopening even when history has no matching run', async () => {
  let starts = 0;
  let operation = '';
  server.use(
    http.post('/api/extractions', async ({ request }) => {
      const body = (await request.json()) as { operation_id: string };
      operation = body.operation_id;
      starts++;
      return HttpResponse.error();
    }),
  );
  const view = show();
  await userEvent.click(
    await screen.findByRole('checkbox', { name: 'Выбрать последнюю версию BRD.md' }),
  );
  await userEvent.click(screen.getByRole('button', { name: 'Извлечь требования' }));
  await screen.findByRole('alert');
  view.unmount();
  server.use(
    http.get('/api/extraction-operations/:id', ({ params }) => {
      expect(params.id).toBe(operation);
      return HttpResponse.json(run);
    }),
  );
  show();
  expect(
    await screen.findByRole('link', { name: 'Открыть восстановленный анализ' }),
  ).toHaveAttribute('href', '/requirements?run=run');
  expect(starts).toBe(1);
});

it('retries the saved analysis independently of a changed draft after reopening', async () => {
  const commands: unknown[] = [];
  server.use(
    http.post('/api/extractions', async ({ request }) => {
      commands.push(await request.json());
      return HttpResponse.error();
    }),
  );
  const view = show();
  const selected = await screen.findByRole('checkbox', { name: 'Выбрать последнюю версию BRD.md' });
  await userEvent.click(selected);
  await userEvent.click(screen.getByText('Уточнить анализ'));
  await userEvent.type(
    screen.getByLabelText('На что обратить внимание (необязательно)'),
    'Безопасность',
  );
  await userEvent.click(screen.getByRole('button', { name: 'Извлечь требования' }));
  await screen.findByRole('alert');
  await userEvent.click(selected);
  view.unmount();
  show();
  const retry = await screen.findByRole('button', { name: 'Повторить запуск' });
  await waitFor(() => expect(retry).toBeEnabled());
  await userEvent.click(retry);
  await waitFor(() => expect(commands).toHaveLength(2));
  expect(commands[1]).toEqual(commands[0]);
  expect(commands[1]).toMatchObject({ version_ids: ['v1'], analysis_scope: 'Безопасность' });
});
