import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter } from 'react-router';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { ThemeProvider } from '../shared/ui/theme-provider';
import { Workspace } from './workspace';
import { mockExtractions } from '../shared/api/extraction-test-fixtures';
import { sessionStore } from '../shared/ui/session-storage';

const source = {
  file_id: 'file-1',
  version_id: 'v1',
  sha256: 'abc123',
  fragment_id: 'fragment-1',
  locator: { kind: 'lines', start: 2, end: 2, section: 'Функции' },
  quote: 'Сохранять отчёты',
  status: 'verified',
  reason: null,
};
const run = {
  id: 'run-1',
  status: 'completed',
  progress: { completed_parts: 1, total_parts: 1 },
  error_code: null,
  created_at: '2026-11-26T12:00:00Z',
  model: 'fake-extract',
  coverage: { complete: true, total_fragments: 2, processed_fragments: 2 },
  requirements: [
    {
      id: 'req-1',
      category: 'functional',
      original_text: 'Сохранять отчёты',
      normalized_text: 'Система сохраняет отчёты.',
      sources: [source],
      status: 'needs_review',
    },
    {
      id: 'req-2',
      category: 'gap',
      original_text: 'Срок не указан',
      normalized_text: 'Срок хранения отчётов не определён.',
      sources: [],
      status: 'needs_review',
    },
  ],
};
const server = setupServer(
  http.get('/api/chats', () => HttpResponse.json([])),
  http.get('/api/model', () => HttpResponse.json({ model: 'fake', available: true })),
  http.get('/api/preferences', () => HttpResponse.json({ theme: 'system' })),
  ...mockExtractions([run]),
  http.get('/api/extractions/:id', () => HttpResponse.json(run)),
);
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterAll(() => server.close());
afterEach(() => {
  server.resetHandlers();
  localStorage.clear();
  sessionStore.clear();
});

function show(path = '/requirements') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <MemoryRouter initialEntries={[path]}>
          <Workspace />
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

it('shows the original source quote once and keeps technical metadata behind disclosure', async () => {
  show();
  const row = (await screen.findByText('Система сохраняет отчёты.')).closest('tr');
  if (!row) throw new Error('Requirement row is missing');
  expect(within(row).queryByText('Исходная формулировка')).not.toBeInTheDocument();
  await userEvent.click(within(row).getByText('Цитата из документа'));
  expect(within(row).getAllByText(source.quote)).toHaveLength(1);
  expect(within(row).getByText('SHA-256: abc123')).not.toBeVisible();
  await userEvent.click(within(row).getByText('Технические сведения'));
  expect(within(row).getByText('SHA-256: abc123')).toBeVisible();
});

it.each(['', '   '])(
  'preserves original wording when an unverified source has a blank quote (%j)',
  async (quote) => {
    server.use(
      ...mockExtractions([
        {
          ...run,
          requirements: [
            {
              ...run.requirements[0],
              sources: [
                {
                  ...source,
                  quote,
                  status: 'unverified',
                  reason: 'missing_evidence',
                },
              ],
            },
          ],
        },
      ]),
    );
    show();
    await screen.findByText('Система сохраняет отчёты.');
    await userEvent.click(screen.getByText('Исходная формулировка'));
    expect(screen.getByText('Сохранять отчёты')).toBeVisible();
    expect(screen.queryByText('Цитата из документа')).not.toBeInTheDocument();
  },
);

it('filters candidate requirements and links evidence to an exact source version', async () => {
  show();
  expect(await screen.findByText('Система сохраняет отчёты.')).toBeVisible();
  expect(screen.getByText('Срок хранения отчётов не определён.')).toBeVisible();
  expect(screen.queryByText('req-1')).not.toBeInTheDocument();
  const evidence = screen.getByRole('link', { name: 'Источник · Строка 2 · Функции' });
  expect(evidence).toHaveAttribute('href', '/documents?version=v1&fragment=fragment-1&run=run-1');
  expect(screen.queryByText('Ссылка технически проверена')).not.toBeInTheDocument();
  expect(screen.getByText('Источник не подтверждён')).toBeVisible();
  await userEvent.selectOptions(
    screen.getByRole('combobox', { name: 'Категория требований' }),
    'gap',
  );
  expect(screen.queryByText('Система сохраняет отчёты.')).not.toBeInTheDocument();
  expect(screen.getByText('Срок хранения отчётов не определён.')).toBeVisible();
});

it('shows unverified sources and incomplete coverage without approving the extraction', async () => {
  server.use(
    ...mockExtractions([
      {
        ...run,
        coverage: { complete: false, total_fragments: 4, processed_fragments: 2 },
        requirements: [
          {
            ...run.requirements[0],
            sources: [{ ...source, status: 'unverified', reason: 'quote_not_found' }],
          },
        ],
      },
    ]),
  );
  show();
  expect(await screen.findByText(/Неполное покрытие: 2 из 4/)).toBeVisible();
  expect(screen.getByText('Цитата не подтверждена исходным текстом.')).toBeVisible();
  expect(screen.getByText(/кандидаты для проверки/)).toBeVisible();
});

it('cancels an active extraction and keeps its saved progress visible', async () => {
  const active = {
    ...run,
    status: 'running',
    progress: { completed_parts: 1, total_parts: 3 },
    requirements: [],
  };
  let cancelled = false;
  server.use(
    ...mockExtractions([active]),
    http.get('/api/extractions/:id', () => HttpResponse.json(active)),
    http.post('/api/extractions/:id/cancel', () => {
      cancelled = true;
      return HttpResponse.json({ ...active, status: 'cancelled' });
    }),
  );
  show();
  expect(await screen.findByText('Выполняется извлечение…')).toBeVisible();
  expect(screen.getByText('Обработано частей: 1 из 3')).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: 'Отменить извлечение' }));
  expect(await screen.findByText('Извлечение отменено')).toBeVisible();
  expect(cancelled).toBe(true);
  expect(screen.queryByRole('button', { name: 'Отменить извлечение' })).not.toBeInTheDocument();
});

it('selects a historical extraction without replacing earlier requirements', async () => {
  const old = {
    ...run,
    id: 'run-old',
    created_at: '2026-11-25T12:00:00Z',
    requirements: [{ ...run.requirements[0], normalized_text: 'Старая формулировка сохраняется.' }],
  };
  server.use(
    ...mockExtractions([run, old]),
    http.get('/api/extractions/:id', ({ params }) =>
      HttpResponse.json(params.id === 'run-old' ? old : run),
    ),
  );
  show();
  expect(await screen.findByText('Система сохраняет отчёты.')).toBeVisible();
  await userEvent.selectOptions(
    screen.getByRole('combobox', { name: 'История извлечений' }),
    'run-old',
  );
  expect(await screen.findByText('Старая формулировка сохраняется.')).toBeVisible();
  expect(screen.queryByText('Система сохраняет отчёты.')).not.toBeInTheDocument();
});

it('loads another page of compact history without fetching the unselected results', async () => {
  const history = Array.from({ length: 51 }, (_, index) => ({ ...run, id: `run-${index}` }));
  let details = 0;
  server.use(...mockExtractions(history));
  server.use(
    http.get('/api/extractions/run-0', () => {
      details++;
      return HttpResponse.json({ ...run, id: 'run-0' });
    }),
  );
  show();
  await screen.findByText('Система сохраняет отчёты.');
  expect(screen.getByRole('combobox', { name: 'История извлечений' }).children).toHaveLength(50);
  await userEvent.click(screen.getByRole('button', { name: 'Загрузить ещё анализы' }));
  await waitFor(() =>
    expect(screen.getByRole('combobox', { name: 'История извлечений' }).children).toHaveLength(51),
  );
  expect(details).toBe(1);
});

it('keeps errors actionable and displays a typed generation failure', async () => {
  server.use(http.get('/api/extractions/history', () => new HttpResponse(null, { status: 503 })));
  show();
  const error = await screen.findByRole('alert');
  server.use(
    ...mockExtractions([
      { ...run, status: 'failed', error_code: 'context_too_large', requirements: [] },
    ]),
  );
  await userEvent.click(within(error).getByRole('button', { name: 'Повторить' }));
  expect(await screen.findByText('Извлечение завершилось ошибкой')).toBeVisible();
  expect(screen.getByText(/Окно модели слишком мало/)).toBeVisible();
});

it('does not invent a document link for a fragment absent from the supplied context', async () => {
  server.use(
    ...mockExtractions([
      {
        ...run,
        requirements: [
          {
            ...run.requirements[0],
            sources: [
              {
                ...source,
                file_id: null,
                version_id: null,
                sha256: null,
                locator: null,
                fragment_id: 'invented',
                status: 'unverified',
                reason: 'fragment_not_in_context',
              },
            ],
          },
        ],
      },
    ]),
  );
  show();
  expect(await screen.findByText('Подтверждающий фрагмент недоступен.')).toBeVisible();
  expect(screen.getByText('Цитата не подтверждена исходным текстом.')).toBeVisible();
  expect(screen.queryByRole('link', { name: /Источник/ })).not.toBeInTheDocument();
});

it('refreshes an active extraction until its persisted result is complete', async () => {
  let reads = 0;
  let details = 0;
  server.use(
    ...mockExtractions([{ ...run, status: 'running', requirements: [] }]),
    http.get('/api/extractions/:id', () => {
      details++;
      return HttpResponse.json(run);
    }),
  );
  server.use(
    http.get('/api/extractions/:id/status', () =>
      HttpResponse.json(++reads < 2 ? { ...run, status: 'running' } : run),
    ),
    http.get('/api/extractions/run-1', () => {
      details++;
      return HttpResponse.json(run);
    }),
  );
  show();
  expect(await screen.findByText('Выполняется извлечение…')).toBeVisible();
  expect(await screen.findByText('Извлечение завершено', {}, { timeout: 3000 })).toBeVisible();
  expect(await screen.findByText('Система сохраняет отчёты.')).toBeVisible();
  expect(reads).toBeGreaterThanOrEqual(2);
  expect(details).toBe(1);
});

it('shows effective requirements while another question still blocks the waiting run', async () => {
  const waiting = { ...run, status: 'waiting_input' };
  server.use(...mockExtractions([waiting]));
  server.use(
    http.get('/api/extractions/run-1/clarifications', () =>
      HttpResponse.json({
        run_id: 'run-1',
        history_id: 'history',
        cycle: 0,
        initialized: true,
        resume_pending: false,
        requirements: [
          {
            ...run.requirements[0],
            normalized_text: 'Хранить отчёты 90 дней — ответ архитектора.',
          },
        ],
        questions: [
          {
            id: 'q2',
            gap_key: 'volume',
            revision: 1,
            text: 'Каков объём?',
            basis: 'Объём отсутствует',
            dependent_decision: 'Размер хранилища',
            blocking: true,
            requirement_ids: ['req-1'],
            sources: [source],
            status: 'open',
            previous_basis: null,
          },
        ],
        decisions: [],
        risks: [],
        completed_cycles: [],
      }),
    ),
  );
  show('/requirements?run=run-1&requirement=req-1');
  expect(await screen.findByText('Ожидает ответа архитектора')).toBeVisible();
  expect(await screen.findByText('Хранить отчёты 90 дней — ответ архитектора.')).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: 'Открыть блокирующие вопросы' }));
  expect(screen.getByText('Блокирующих вопросов: 1')).toBeVisible();
  expect(screen.getByRole('region', { name: 'Каков объём?' })).toBeVisible();
  expect(screen.getByRole('button', { name: 'Отменить извлечение' })).toBeEnabled();
});
