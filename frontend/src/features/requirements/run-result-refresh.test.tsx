import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter } from 'react-router';
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest';
import { clarificationSchema } from '../../shared/api/clarifications';
import { extractionSchema, type Extraction } from '../../shared/api/extractions';
import { fixtureId, storedModelProfileFixture } from '../../shared/api/test-network-fixtures';
import { RunResult } from './run-result';
import { Requirements } from './requirements';

const run = extractionSchema.parse({
  id: fixtureId('delayed-run'),
  status: 'running',
  progress: { completed_parts: 1, total_parts: 1 },
  created_at: '2026-11-28T00:00:00Z',
  model: 'fixture',
  model_profile: storedModelProfileFixture,
  version_ids: [],
  pipeline_versions: null,
  current_pipeline_versions: null,
  error_code: null,
  contract_version: 'requirements-1',
  prompt_version: 'extract-4',
  coverage: { complete: true, processed_fragments: 1, total_fragments: 1, warnings: [] },
  requirements: [],
});
const empty = clarificationSchema.parse({
  run_id: run.id,
  history_id: fixtureId('delayed-history'),
  initialized: false,
  questions: [],
  decisions: [],
  risks: [],
  requirements: [],
  completed_cycles: [],
  conflict_assessments: [],
  metadata: null,
});
const ready = clarificationSchema.parse({
  ...empty,
  initialized: true,
  questions: [
    {
      id: fixtureId('delayed-question'),
      gap_key: 'retention',
      revision: 1,
      text: 'Каков срок хранения?',
      basis: 'Срок отсутствует',
      dependent_decision: 'Выбор хранилища',
      blocking: true,
      requirement_ids: [fixtureId('delayed-requirement')],
      previous_sources: [],
      requirement_basis_fingerprints: {},
      requirement_fingerprints: {},
      source_fingerprints: {},
      sources: [],
      status: 'open',
      previous_basis: null,
      mandatory_conflict: null,
    },
  ],
});
const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterAll(() => server.close());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  server.resetHandlers();
});

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = (status: Extraction['status']) => (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/?tab=clarifications']}>
        <RunResult run={{ ...run, status }} />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const result = render(tree('running'));
  return { ...result, status: (status: Extraction['status']) => result.rerender(tree(status)) };
}

it.each(['waiting_input', 'completed', 'failed', 'cancelled'] as const)(
  'refreshes delayed clarification data on %s and then stops requesting the full view',
  async (status) => {
    let reads = 0;
    let persisted = empty;
    server.use(
      http.get(`/api/extractions/${run.id}/clarifications`, () => {
        reads++;
        return HttpResponse.json(persisted);
      }),
    );
    const view = show();
    await screen.findByText('Открытых вопросов нет.');
    expect(reads).toBe(1);
    persisted = ready;
    view.status(status);
    expect(await screen.findByRole('textbox', { name: 'Ответ архитектора' })).toBeVisible();
    await waitFor(() => expect(reads).toBe(2));
    vi.useFakeTimers();
    view.status(status);
    await act(() => vi.advanceTimersByTimeAsync(6000));
    expect(reads).toBe(2);
  },
);

it('does not allow a pre-transition response to overwrite the actionable view', async () => {
  let reads = 0;
  let release: (() => void) | undefined;
  const delayed = new Promise<void>((resolve) => {
    release = resolve;
  });
  server.use(
    http.get(`/api/extractions/${run.id}/clarifications`, async () => {
      reads++;
      if (reads === 1) {
        await delayed;
        return HttpResponse.json(empty);
      }
      return HttpResponse.json(ready);
    }),
  );
  const view = show();
  await waitFor(() => expect(reads).toBe(1));
  view.status('waiting_input');
  try {
    expect(await screen.findByRole('textbox', { name: 'Ответ архитектора' })).toBeVisible();
  } finally {
    await act(async () => {
      release?.();
      await delayed;
    });
  }
  expect(screen.getByRole('textbox', { name: 'Ответ архитектора' })).toBeVisible();
  expect(reads).toBe(2);
});

it('refreshes when the compact status changes while the full result retains its older status', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let reads = 0;
  let persisted = empty;
  let status = run;
  server.use(
    http.get('/api/extractions/history', () =>
      HttpResponse.json({ items: [run], has_more: false }),
    ),
    http.get(`/api/extractions/${run.id}/status`, () => HttpResponse.json(status)),
    http.get(`/api/extractions/${run.id}`, () => HttpResponse.json(run)),
    http.get(`/api/extractions/${run.id}/clarifications`, () => {
      reads++;
      return HttpResponse.json(persisted);
    }),
  );
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/?run=${run.id}&tab=clarifications`]}>
        <Requirements />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await waitFor(() => expect(reads).toBe(1));
  persisted = ready;
  status = { ...run, status: 'waiting_input' };
  await waitFor(
    () => expect(screen.getByRole('textbox', { name: 'Ответ архитектора' })).toBeVisible(),
    { timeout: 3000 },
  );
  expect(await screen.findByRole('textbox', { name: 'Ответ архитектора' })).toBeVisible();
});

it('still refreshes a settled view when another tab announces a clarification change', async () => {
  const channels: { onmessage: ((event: MessageEvent<unknown>) => void) | null }[] = [];
  vi.stubGlobal(
    'BroadcastChannel',
    class {
      onmessage: ((event: MessageEvent<unknown>) => void) | null = null;
      close = vi.fn();
      postMessage = vi.fn();
      constructor() {
        channels.push(this);
      }
    },
  );
  let persisted = empty;
  let reads = 0;
  server.use(
    http.get(`/api/extractions/${run.id}/clarifications`, () => {
      reads++;
      return HttpResponse.json(persisted);
    }),
  );
  const view = show();
  await screen.findByText('Открытых вопросов нет.');
  view.status('completed');
  await waitFor(() => expect(reads).toBe(2));
  persisted = ready;
  act(() => {
    channels[0]!.onmessage?.(new MessageEvent('message', { data: { sender: 'another-tab' } }));
  });
  expect(await screen.findByRole('textbox', { name: 'Ответ архитектора' })).toBeVisible();
  expect(reads).toBe(3);
});
