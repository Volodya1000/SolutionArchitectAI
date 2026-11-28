import { fixtureId } from '@/shared/api/test-network-fixtures';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { scopeKey, type Snapshot } from '../../shared/api/client';
import { useChat } from './use-chat';

const active: Snapshot = {
  chat: {
    id: fixtureId('a'),
    task_id: fixtureId('task'),
    title: 'Чат',
    created_at: '2026-11-26T00:00:00Z',
  },
  messages: [
    {
      id: fixtureId('answer'),
      role: 'assistant',
      content: 'Начало',
      position: 2,
      incomplete: true,
    },
  ],
  runs: [
    {
      config_digest: 'test-config',
      created_at: '2026-01-01T00:00:00Z',

      id: fixtureId('run'),
      chat_id: fixtureId('a'),
      assistant_message_id: fixtureId('answer'),
      status: 'running',
      sequence: 1,
      content: 'Начало',
      incomplete: true,
      error_code: null,
      model: 'fake-chat',
    },
  ],
};
let snapshot = active;
let autoFailStreams = false;
const sources: TestEventSource[] = [];
class TestEventSource {
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor() {
    sources.push(this);
    if (autoFailStreams) queueMicrotask(() => this.onerror?.());
  }
  close() {
    this.closed = true;
  }
}
const server = setupServer(
  http.get(`/api/chats/${fixtureId('a')}`, () => HttpResponse.json(snapshot)),
);
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(() => {
  server.resetHandlers();
  vi.unstubAllGlobals();
  sources.length = 0;
  snapshot = active;
  autoFailStreams = false;
});
afterAll(() => server.close());

function show() {
  vi.stubGlobal('EventSource', TestEventSource);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = renderHook(() => useChat(fixtureId('a')), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
  return { ...view, client };
}

it('opens a new stream after a closed connection with the same active run', async () => {
  const { result } = show();
  await waitFor(() => expect(result.current.run?.id).toBe(fixtureId('run')));
  act(() => sources[0]!.onerror?.());
  await waitFor(() => expect(sources).toHaveLength(2), { timeout: 3000 });
  act(() =>
    sources[1]!.onmessage?.(
      new MessageEvent('message', {
        data: JSON.stringify({
          run_id: fixtureId('run'),
          sequence: 2,
          kind: 'snapshot',
          payload: {
            ...active.runs[0],
            status: 'completed',
            sequence: 2,
            content: 'Полный ответ',
            incomplete: false,
          },
        }),
      }),
    ),
  );
  await waitFor(() => expect(result.current.query.data?.messages[0]?.content).toBe('Полный ответ'));
  expect(result.current.run).toBeUndefined();
  expect(result.current.connectionError).toBe(false);
});

it('clears the warning when history confirms completion without another stream event', async () => {
  const { result } = show();
  await waitFor(() => expect(result.current.run?.id).toBe(fixtureId('run')));
  snapshot = {
    ...active,
    messages: [{ ...active.messages[0]!, content: 'Конец', incomplete: false }],
    runs: [
      { ...active.runs[0]!, status: 'completed', sequence: 2, content: 'Конец', incomplete: false },
    ],
  };
  act(() => sources[0]!.onerror?.());
  await waitFor(() => expect(result.current.run).toBeUndefined());
  expect(result.current.connectionError).toBe(false);
  expect(result.current.query.data?.messages[0]?.content).toBe('Конец');
});

it('recovers malformed stream JSON and closes connections when unmounted', async () => {
  const { result, unmount } = show();
  await waitFor(() => expect(result.current.run?.id).toBe(fixtureId('run')));
  act(() => sources[0]!.onmessage?.(new MessageEvent('message', { data: '{broken' })));
  await waitFor(() => expect(sources).toHaveLength(2), { timeout: 3000 });
  unmount();
  expect(sources.every((source) => source.closed)).toBe(true);
});

it('lets slow history recovery finish while repeated stream connections fail', async () => {
  let reads = 0;
  server.use(
    http.get(`/api/chats/${fixtureId('a')}`, async () => {
      if (++reads === 1) return HttpResponse.json(active);
      await new Promise((resolve) => setTimeout(resolve, 1400));
      return HttpResponse.json({
        ...active,
        messages: [{ ...active.messages[0], content: 'Конец', incomplete: false }],
        runs: [
          {
            ...active.runs[0],
            status: 'completed',
            sequence: 2,
            content: 'Конец',
            incomplete: false,
          },
        ],
      });
    }),
  );
  autoFailStreams = true;
  const { result } = show();
  await waitFor(() => expect(result.current.query.data?.messages[0]?.content).toBe('Конец'), {
    timeout: 4000,
  });
  expect(result.current.connectionError).toBe(false);
});

it('does not carry a failed connection warning into the next run', async () => {
  const view = show();
  await waitFor(() => expect(view.result.current.run?.id).toBe(fixtureId('run')));
  snapshot = { ...active, runs: [{ ...active.runs[0]!, status: 'completed', sequence: 2 }] };
  act(() => sources[0]!.onerror?.());
  await waitFor(() => expect(view.result.current.run).toBeUndefined());
  snapshot = { ...active, runs: [{ ...active.runs[0]!, id: fixtureId('next-run') }] };
  await act(() => view.result.current.query.refetch());
  await waitFor(() => expect(view.result.current.run?.id).toBe(fixtureId('next-run')));
  expect(view.result.current.connectionError).toBe(false);
});

it('keeps newer SSE text and completion when an older HTTP refresh arrives later', async () => {
  const { result, client } = show();
  await waitFor(() => expect(result.current.run?.id).toBe(fixtureId('run')));
  let release = () => {};
  const response = new Promise<void>((resolve) => {
    release = resolve;
  });
  let started = false;
  server.use(
    http.get(`/api/chats/${fixtureId('a')}`, async () => {
      started = true;
      await response;
      return HttpResponse.json(active);
    }),
  );
  let refresh: ReturnType<typeof result.current.query.refetch>;
  act(() => {
    refresh = result.current.query.refetch();
  });
  await waitFor(() => expect(started).toBe(true));
  act(() =>
    sources[0]!.onmessage?.(
      new MessageEvent('message', {
        data: JSON.stringify({
          run_id: fixtureId('run'),
          sequence: 2,
          kind: 'snapshot',
          payload: {
            ...active.runs[0],
            sequence: 2,
            status: 'completed',
            content: 'Новый ответ',
            incomplete: false,
          },
        }),
      }),
    ),
  );
  await waitFor(() => expect(result.current.run).toBeUndefined());
  release();
  await act(async () => {
    await refresh;
  });
  expect(
    client.getQueryData<Snapshot>([...scopeKey, 'chat', fixtureId('a')])?.runs[0]?.sequence,
  ).toBe(2);
  expect(result.current.query.data?.messages[0]?.content).toBe('Новый ответ');
  expect(result.current.query.data?.runs[0]?.sequence).toBe(2);
  expect(result.current.run).toBeUndefined();
});
