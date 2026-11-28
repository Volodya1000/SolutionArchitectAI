import {
  fixtureId,
  storedModelProfileFixture,
  fixtureHash,
  clarificationModelProfileFixture,
} from '@/shared/api/test-network-fixtures';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { Requirements } from '../features/requirements';
import { Documents } from '../features/documents';
import { mockExtractions } from '../shared/api/extraction-test-fixtures';
import { sessionStore } from '../shared/ui/session-storage';
import { WorkspaceHeading } from './workspace-content';

const requirement = {
  id: fixtureId('r1'),
  category: 'functional',
  original_text: 'Правило',
  normalized_text: 'Хранить отчёты',
  sources: [],
  status: 'needs_review',
};
const run = {
  pipeline_versions: null,
  current_pipeline_versions: null,
  model_profile: storedModelProfileFixture,
  contract_version: 'requirements-1',
  prompt_version: 'extract-3',

  id: fixtureId('selected-run'),
  status: 'waiting_input',
  progress: { completed_parts: 1, total_parts: 1 },
  error_code: null,
  created_at: '2026-11-27T00:00:00Z',
  model: 'fake',
  version_ids: [fixtureId('v1')],
  analysis_scope: '',
  configuration_current: true,
  coverage: {
    warnings: [],
    complete: true,
    total_fragments: 1,
    processed_fragments: 1,
  },
  requirements: [requirement],
};
const question = {
  source_fingerprints: {},
  requirement_fingerprints: {},
  requirement_basis_fingerprints: {},
  previous_basis: null,
  previous_sources: [],
  mandatory_conflict: null,

  id: fixtureId('q1'),
  gap_key: 'retention',
  revision: 1,
  text: 'Каков срок?',
  basis: 'Нет срока',
  dependent_decision: 'Хранилище',
  blocking: true,
  requirement_ids: [fixtureId('r1')],
  sources: [],
  status: 'open',
};
const view = {
  ...{ conflict_assessments: [] },
  metadata: null,
  resume_version: 0,

  run_id: run.id,
  history_id: fixtureId('selected-history'),
  cycle: 0,
  initialized: true,
  resume_pending: false,
  requirements: [requirement],
  questions: [
    question,
    { ...question, id: fixtureId('q2'), text: 'Предпочтение?', blocking: false },
  ],
  decisions: [],
  risks: [
    {
      resolution_reason: null,
      id: fixtureId('risk'),
      decision_id: fixtureId('decision'),
      consequences: 'Переполнение',
      mitigation: 'Квоты',
      status: 'open',
    },
  ],
  completed_cycles: [],
};
const version = {
  storage_key: 'fixture-key',

  file_id: fixtureId('f1'),
  task_id: fixtureId('task'),
  version_id: fixtureId('v1'),
  sha256: fixtureHash('hash'),
  mime_type: 'text/markdown',
  size: 10,
  original_name: 'BRD.md',
  uploaded_at: '2026-11-27T00:00:00Z',
};
const commands: unknown[] = [];
const matching: URLSearchParams[] = [];
const server = setupServer(
  http.get(`/api/extractions/${fixtureId('selected-run')}/clarifications`, () =>
    HttpResponse.json(view),
  ),
  http.get('/api/documents', () =>
    HttpResponse.json([
      {
        file_id: fixtureId('f1'),
        task_id: fixtureId('task'),
        name: 'BRD.md',
        created_at: version.uploaded_at,
        latest_version: version,
      },
    ]),
  ),
  http.get('/api/extractions/matching', ({ request }) => {
    matching.push(new URL(request.url).searchParams);
    return HttpResponse.json({ active: null, current_completed: null, latest_completed: null });
  }),
  http.get('/api/extraction-operations/:id', () => new HttpResponse(null, { status: 404 })),
  http.post('/api/extractions', async ({ request }) => {
    commands.push(await request.json());
    return HttpResponse.json({ ...run, id: fixtureId('new-run'), status: 'queued' });
  }),
  ...mockExtractions([run]),
);
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterAll(() => server.close());
afterEach(() => {
  server.resetHandlers();
  sessionStore.clear();
  commands.length = 0;
  matching.length = 0;
});

function show() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[`/requirements?run=${fixtureId('selected-run')}`]}>
        <Routes>
          <Route path="/requirements" element={<Requirements />} />
          <Route path="/documents" element={<Documents />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it('shows counted tabs and a waiting notice before the list that opens only blockers', async () => {
  show();
  const table = await screen.findByRole('table', { name: 'Кандидаты требований' });
  expect(screen.getByRole('tab', { name: 'Требования 1' })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  expect(await screen.findByRole('tab', { name: 'Уточнения 2' })).toHaveAttribute(
    'aria-selected',
    'false',
  );
  expect(screen.getByRole('tab', { name: 'Риски 1' })).toBeVisible();
  const notice = screen.getByRole('region', { name: 'Анализ ожидает решения' });
  expect(notice.compareDocumentPosition(table) & 4).toBe(4);
  await userEvent.click(
    within(notice).getByRole('button', { name: 'Открыть блокирующие вопросы' }),
  );
  expect(screen.getByRole('region', { name: 'Каков срок?' })).toHaveFocus();
  expect(screen.queryByRole('region', { name: 'Предпочтение?' })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Показать все вопросы' }));
  expect(screen.getByRole('region', { name: 'Предпочтение?' })).toBeVisible();
  await userEvent.click(screen.getByRole('tab', { name: 'Риски 1' }));
  expect(screen.getByRole('region', { name: 'Риски A-07' })).toHaveTextContent('Переполнение');
  expect(screen.queryByLabelText('Ответ архитектора')).not.toBeInTheDocument();
});

it('supports keyboard tab navigation without losing the selected analysis', async () => {
  show();
  const requirements = await screen.findByRole('tab', { name: 'Требования 1' });
  requirements.focus();
  await userEvent.keyboard('{ArrowRight}');
  expect(screen.getByRole('tab', { name: 'Уточнения 2' })).toHaveFocus();
  expect(screen.getByRole('tab', { name: 'Уточнения 2' })).toHaveAttribute('aria-selected', 'true');
  expect(
    screen.getByRole('link', { name: 'Выбрать документы для нового анализа' }),
  ).toHaveAttribute('href', `/documents?run=${fixtureId('selected-run')}`);
});

it('returns from a risk to all clarification decisions after the blocker-only view', async () => {
  show();
  await userEvent.click(await screen.findByRole('button', { name: 'Открыть блокирующие вопросы' }));
  expect(screen.queryByRole('region', { name: 'Предпочтение?' })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('tab', { name: 'Риски 1' }));
  await userEvent.click(screen.getByRole('link', { name: 'Допущение A-01' }));
  expect(screen.getByRole('region', { name: 'Предпочтение?' })).toBeVisible();
});

it('keeps an assumed mandatory conflict in the waiting notice and explains the blocker', async () => {
  server.use(
    http.get(`/api/extractions/${fixtureId('selected-run')}/clarifications`, () =>
      HttpResponse.json({
        ...view,
        questions: [
          {
            ...question,
            status: 'assumed',
            mandatory_conflict: 'Допущение нарушает обязательный срок в 7 дней.',
          },
        ],
      }),
    ),
  );
  show();
  const notice = await screen.findByRole('region', { name: 'Анализ ожидает решения' });
  expect(notice).toHaveTextContent('Блокирующих вопросов: 1');
  await userEvent.click(
    within(notice).getByRole('button', { name: 'Открыть блокирующие вопросы' }),
  );
  expect(screen.getByText('Допущение нарушает обязательный срок в 7 дней.')).toBeVisible();
});

it.each(['running', 'failed'] as const)(
  'reports incomplete clarification coverage above the result (%s)',
  async (status) => {
    server.use(
      http.get(`/api/extractions/${fixtureId('selected-run')}/status`, () =>
        HttpResponse.json({ ...run, status }),
      ),
      http.get(`/api/extractions/${fixtureId('selected-run')}`, () =>
        HttpResponse.json({ ...run, status }),
      ),
      http.get(`/api/extractions/${fixtureId('selected-run')}/clarifications`, () =>
        HttpResponse.json({
          ...view,
          initialized: false,
          questions: [],
          metadata: {
            ...{ conflict_assessment_prompt_version: null, review_start_requests: null },
            context_digest: 'test-context',
            model_profile: clarificationModelProfileFixture,
            contract_version: 'clarification-1',
            prompt_version: 'clarify-4',
            review_prompt_version: 'clarify-review-1',

            coverage: {
              total_fragments: 10,
              reviewed_fragments: 4,
              total_history: 8,
              reviewed_history: 3,
              model_requests: 2,
              complete: false,
              unreviewed_fragment_ids: [fixtureId('fragment')],
              unreviewed_question_ids: [fixtureId('question')],
            },
          },
        }),
      ),
    );
    show();
    const message = await screen.findByText(/проверено 4 из 10 фрагментов, 3 из 8 ответов/);
    if (status === 'failed') {
      expect(message.closest('[role="alert"]')).toBeVisible();
      expect(message).toHaveTextContent('отсутствие вопроса не означает полноту');
      const table = await screen.findByRole('table', { name: 'Кандидаты требований' });
      expect(message.compareDocumentPosition(table) & 4).toBe(4);
    } else {
      expect(message.closest('[role="status"]')).toBeVisible();
      expect(message).not.toHaveTextContent('не завершена');
    }
  },
);

it.each([false, true])(
  'keeps the selected answer history through document selection (new=%s)',
  async (newHistory) => {
    show();
    await screen.findByText('Хранить отчёты');
    await userEvent.click(
      screen.getByRole('link', { name: 'Выбрать документы для нового анализа' }),
    );
    await userEvent.click(
      await screen.findByRole('checkbox', { name: 'Выбрать последнюю версию BRD.md' }),
    );
    if (newHistory)
      await userEvent.click(screen.getByLabelText('Начать с новой историей уточнений'));
    else expect(await screen.findByText(/Используется история выбранного анализа/)).toBeVisible();
    await userEvent.click(await screen.findByRole('button', { name: 'Извлечь требования' }));
    expect(commands).toHaveLength(1);
    expect(commands[0]).toMatchObject({
      answer_history_mode: newHistory ? 'new' : 'reuse',
      answer_history_id: newHistory ? null : fixtureId('selected-history'),
    });
    expect(matching.at(-1)?.get('answer_history_id')).toBe(
      newHistory ? null : fixtureId('selected-history'),
    );
  },
);

it('keeps the conversation heading concise when the subject title is long', () => {
  render(<WorkspaceHeading section="chat" title="Полный длинный предмет обсуждения требования" />);
  expect(screen.getByRole('heading', { name: 'Рабочий чат' })).toBeVisible();
  expect(
    screen.queryByText('Полный длинный предмет обсуждения требования'),
  ).not.toBeInTheDocument();
});
