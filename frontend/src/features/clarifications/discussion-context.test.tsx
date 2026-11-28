import { fixtureId, fixtureHash } from '@/shared/api/test-network-fixtures';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter } from 'react-router';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { Chat } from '../chat';
import { sessionStore } from '../../shared/ui/session-storage';
import { DiscussionHeader } from './index';

const source = {
  file_id: fixtureId('file'),
  version_id: fixtureId('v1'),
  sha256: fixtureHash('abc'),
  fragment_id: fixtureId('fragment'),
  locator: { kind: 'lines', start: 2, end: 3, section: 'Срок' },
  quote: 'Исходное требование: хранить отчёты.',
  status: 'verified',
  reason: null,
};
const requirement = {
  id: fixtureId('req'),
  category: 'functional',
  original_text: source.quote,
  normalized_text: 'Хранить отчёты 90 дней по решению архитектора.',
  sources: [source],
  status: 'needs_review',
};
const discussion = {
  chat_id: fixtureId('chat'),
  kind: 'requirement',
  title: 'Обсуждение хранения',
  analysis_id: fixtureId('analysis'),
  requirement_id: fixtureId('req'),
  version_id: null,
  fragment_id: null,
  version_ids: [fixtureId('v1')],
  history_id: fixtureId('history'),
  backlink: `/requirements?run=${fixtureId('analysis')}&requirement=${fixtureId('req')}`,
};
const clarification = {
  ...{ conflict_assessments: [] },
  metadata: null,
  resume_version: 0,

  run_id: fixtureId('analysis'),
  history_id: fixtureId('history'),
  cycle: 0,
  initialized: true,
  resume_pending: false,
  questions: [],
  decisions: [],
  risks: [],
  requirements: [requirement],
  completed_cycles: [],
};
const server = setupServer(
  http.get(`/api/chats/${fixtureId('chat')}/discussion`, () => HttpResponse.json(discussion)),
  http.get(`/api/chats/${fixtureId('chat')}/discussion/clarifications`, () =>
    HttpResponse.json(clarification),
  ),
  http.get(`/api/chats/${fixtureId('chat')}`, () =>
    HttpResponse.json({
      chat: {
        id: fixtureId('chat'),
        task_id: fixtureId('task'),
        title: discussion.title,
        created_at: '2026-11-27T00:00:00Z',
      },
      messages: [],
      runs: [],
    }),
  ),
);
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterAll(() => server.close());
afterEach(() => {
  server.resetHandlers();
  sessionStore.clear();
});

function show(content = <DiscussionHeader chatId={fixtureId('chat')} />) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>{content}</MemoryRouter>
    </QueryClientProvider>,
  );
}

it('shows the full effective requirement and original pinned quote even without a question', async () => {
  show();
  expect(await screen.findByText(requirement.normalized_text)).toBeVisible();
  const panel = screen.getByRole('complementary', { name: 'Предмет и источники обсуждения' });
  expect(within(panel).getByText(source.quote)).toBeVisible();
  expect(within(panel).getByRole('link', { name: 'Источник · Строки 2–3 · Срок' })).toHaveAttribute(
    'href',
    `/documents?version=${fixtureId('v1')}&fragment=${fixtureId('fragment')}&run=${fixtureId('analysis')}`,
  );
  expect(within(panel).getByText('Блокирующих вопросов: 0')).toBeVisible();
  expect(within(panel).getByText(new RegExp(`SHA-256: ${fixtureHash('abc')}`))).not.toBeVisible();
  await userEvent.click(within(panel).getByText('Технические сведения источника'));
  expect(within(panel).getByText(new RegExp(`SHA-256: ${fixtureHash('abc')}`))).toBeVisible();
});

it('keeps the subject beside the conversation and preserves the composer when the compact panel collapses', async () => {
  show(<Chat chatId={fixtureId('chat')} />);
  await screen.findByText(requirement.normalized_text);
  const input = screen.getByRole('textbox', { name: 'Сообщение' });
  await userEvent.type(input, 'Черновик обсуждения');
  const panel = screen.getByRole('complementary', { name: 'Предмет и источники обсуждения' });
  expect(panel.parentElement).toHaveClass('discussion-workspace');
  expect(input.closest('.thread')?.parentElement).toBe(panel.parentElement);
  await userEvent.click(screen.getByText('Предмет, источники и уточнения'));
  expect(screen.getByText(requirement.normalized_text)).not.toBeVisible();
  expect(screen.getByText(discussion.title)).toBeVisible();
  expect(screen.getByRole('link', { name: 'Вернуться к требованию' })).toBeVisible();
  expect(input).toHaveValue('Черновик обсуждения');
  await userEvent.click(screen.getByText('Предмет, источники и уточнения'));
  expect(screen.getByText(requirement.normalized_text)).toBeVisible();
  expect(input).toHaveValue('Черновик обсуждения');
});

it('shows only the selected immutable fragment in a direct source discussion', async () => {
  server.use(
    http.get(`/api/chats/${fixtureId('chat')}/discussion/clarifications`, () =>
      HttpResponse.json(null),
    ),
    http.get(`/api/chats/${fixtureId('chat')}/discussion`, () =>
      HttpResponse.json({
        ...discussion,
        kind: 'source',
        analysis_id: null,
        requirement_id: null,
        version_id: fixtureId('v1'),
        fragment_id: fixtureId('fragment'),
        history_id: null,
        backlink: `/documents?version=${fixtureId('v1')}&fragment=${fixtureId('fragment')}`,
      }),
    ),
    http.get(`/api/document-versions/${fixtureId('v1')}/parsed`, () =>
      HttpResponse.json({
        file_id: fixtureId('file'),
        version_id: fixtureId('v1'),
        sha256: fixtureHash('abc'),
        parser_version: 'text-v1',
        text: 'Весь документ',
        warnings: [],
        fragments: [
          { fragment_id: fixtureId('fragment'), text: source.quote, locator: source.locator },
          { fragment_id: fixtureId('other'), text: 'Соседний фрагмент', locator: source.locator },
        ],
      }),
    ),
  );
  show();
  expect(await screen.findByText(source.quote)).toBeVisible();
  expect(screen.queryByText('Соседний фрагмент')).not.toBeInTheDocument();
  expect(screen.queryByText('Уточнения A-01')).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Источник · Строки 2–3 · Срок' })).toHaveAttribute(
    'href',
    `/documents?version=${fixtureId('v1')}&fragment=${fixtureId('fragment')}`,
  );
});
