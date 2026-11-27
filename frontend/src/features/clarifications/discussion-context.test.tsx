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
  file_id: 'file',
  version_id: 'v1',
  sha256: 'abc',
  fragment_id: 'fragment',
  locator: { kind: 'lines', start: 2, end: 3, section: 'Срок' },
  quote: 'Исходное требование: хранить отчёты.',
  status: 'verified',
  reason: null,
};
const requirement = {
  id: 'req',
  category: 'functional',
  original_text: source.quote,
  normalized_text: 'Хранить отчёты 90 дней по решению архитектора.',
  sources: [source],
  status: 'needs_review',
};
const discussion = {
  chat_id: 'chat',
  kind: 'requirement',
  title: 'Обсуждение хранения',
  analysis_id: 'analysis',
  requirement_id: 'req',
  version_id: null,
  fragment_id: null,
  version_ids: ['v1'],
  history_id: 'history',
  backlink: '/requirements?run=analysis&requirement=req',
};
const clarification = {
  run_id: 'analysis',
  history_id: 'history',
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
  http.get('/api/chats/chat/discussion', () => HttpResponse.json(discussion)),
  http.get('/api/extractions/analysis/clarifications', () => HttpResponse.json(clarification)),
  http.get('/api/chats/chat', () =>
    HttpResponse.json({
      chat: {
        id: 'chat',
        task_id: 'task',
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

function show(content = <DiscussionHeader chatId="chat" />) {
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
    '/documents?version=v1&fragment=fragment&run=analysis',
  );
  expect(within(panel).getByText('Блокирующих вопросов: 0')).toBeVisible();
  expect(within(panel).getByText(/SHA-256: abc/)).toBeVisible();
});

it('keeps the subject beside the conversation and preserves the composer when the compact panel collapses', async () => {
  show(<Chat chatId="chat" />);
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
    http.get('/api/chats/chat/discussion', () =>
      HttpResponse.json({
        ...discussion,
        kind: 'source',
        analysis_id: null,
        requirement_id: null,
        version_id: 'v1',
        fragment_id: 'fragment',
        history_id: null,
        backlink: '/documents?version=v1&fragment=fragment',
      }),
    ),
    http.get('/api/document-versions/v1/parsed', () =>
      HttpResponse.json({
        file_id: 'file',
        version_id: 'v1',
        sha256: 'abc',
        parser_version: 'text-v1',
        text: 'Весь документ',
        warnings: [],
        fragments: [
          { fragment_id: 'fragment', text: source.quote, locator: source.locator },
          { fragment_id: 'other', text: 'Соседний фрагмент', locator: source.locator },
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
    '/documents?version=v1&fragment=fragment',
  );
});
