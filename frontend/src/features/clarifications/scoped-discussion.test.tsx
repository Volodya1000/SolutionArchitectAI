import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter } from 'react-router';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { DiscussionHeader } from './discussion-header';

const requirement = {
  id: 'r1',
  category: 'functional',
  original_text: 'Правило отчёта',
  normalized_text: 'Выбранное требование',
  sources: [],
  status: 'needs_review',
};
const question = {
  id: 'q1',
  gap_key: 'retention',
  revision: 1,
  text: 'Выбранный вопрос',
  basis: 'Нет срока',
  dependent_decision: 'Хранилище',
  blocking: true,
  status: 'open',
  requirement_ids: ['r1'],
  sources: [],
  previous_basis: null,
};
const scoped = {
  run_id: 'run',
  history_id: 'history',
  initialized: true,
  cycle: 0,
  resume_pending: false,
  requirements: [requirement],
  questions: [question],
  decisions: [],
  risks: [],
  completed_cycles: [],
};
const binding = {
  chat_id: 'chat',
  kind: 'source',
  title: 'Полное название предмета обсуждения',
  analysis_id: 'run',
  requirement_id: null,
  version_id: 'v1',
  fragment_id: 'fragment',
  version_ids: ['v1'],
  history_id: 'history',
  backlink: '/documents?version=v1&fragment=fragment&run=run',
};
let fullAnalysisReads = 0;
const server = setupServer(
  http.get('/api/chats/chat/discussion', () => HttpResponse.json(binding)),
  http.get('/api/chats/chat/discussion/clarifications', () => HttpResponse.json(scoped)),
  http.get('/api/extractions/run/clarifications', () => {
    fullAnalysisReads++;
    return HttpResponse.json({
      ...scoped,
      requirements: [
        requirement,
        { ...requirement, id: 'r2', normalized_text: 'Постороннее требование' },
      ],
      questions: [
        question,
        { ...question, id: 'q2', text: 'Посторонний вопрос', requirement_ids: ['r2'] },
      ],
      risks: [
        {
          id: 'risk2',
          decision_id: 'd2',
          consequences: 'Посторонний риск',
          mitigation: 'Мера',
          status: 'open',
        },
      ],
    });
  }),
  http.get('/api/document-versions/v1/parsed', () =>
    HttpResponse.json({
      file_id: 'f1',
      version_id: 'v1',
      sha256: 'abc',
      parser_version: 'text-v1',
      text: 'Источник',
      warnings: [],
      fragments: [
        {
          fragment_id: 'fragment',
          text: 'Точный исходный текст',
          locator: { kind: 'lines', start: 1, end: 1, section: '' },
        },
      ],
    }),
  ),
);
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterAll(() => server.close());
afterEach(() => {
  server.resetHandlers();
  fullAnalysisReads = 0;
});

function show() {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <DiscussionHeader chatId="chat" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it('renders the server-selected source scope without fetching unrelated analysis forms or risks', async () => {
  show();
  expect(await screen.findByText('Выбранный вопрос')).toBeVisible();
  expect(screen.queryByText('Посторонний вопрос')).not.toBeInTheDocument();
  expect(screen.queryByText('Посторонний риск')).not.toBeInTheDocument();
  expect(screen.getAllByLabelText('Ответ архитектора')).toHaveLength(1);
  expect(fullAnalysisReads).toBe(0);
});

it('renders a scoped legacy requirement without fetching a whole extraction fallback', async () => {
  server.use(
    http.get('/api/chats/chat/discussion', () =>
      HttpResponse.json({ ...binding, kind: 'requirement', requirement_id: 'r1' }),
    ),
    http.get('/api/chats/chat/discussion/clarifications', () =>
      HttpResponse.json({ ...scoped, initialized: false, questions: [] }),
    ),
  );
  show();
  expect(await screen.findByText('Выбранное требование')).toBeVisible();
  expect(fullAnalysisReads).toBe(0);
});

it('shows technical identifiers only inside a disclosure', async () => {
  show();
  await screen.findByText('Точный исходный текст');
  const panel = screen.getByRole('complementary', { name: 'Предмет и источники обсуждения' });
  expect(within(panel).getByText(/SHA-256: abc/)).not.toBeVisible();
});
