import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { Snapshot } from '../../shared/api/client';
import { useChat } from './use-chat';

const active: Snapshot = {
  chat: { id: 'a', task_id: 'task', title: 'Чат', created_at: '2026-11-26T00:00:00Z' },
  messages: [{ id: 'answer', role: 'assistant', content: 'Начало', position: 2, incomplete: true }],
  runs: [
    {
      id: 'run',
      chat_id: 'a',
      assistant_message_id: 'answer',
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
const sources: TestEventSource[] = [];
class TestEventSource {
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor() {
    sources.push(this);
  }
  close() {
    this.closed = true;
  }
}
const server = setupServer(http.get('/api/chats/a', () => HttpResponse.json(snapshot)));
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(() => {
  server.resetHandlers();
  vi.unstubAllGlobals();
  sources.length = 0;
  snapshot = active;
});
afterAll(() => server.close());

function show() {
  vi.stubGlobal('EventSource', TestEventSource);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderHook(() => useChat('a'), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

it('opens a new stream after a closed connection with the same active run', async () => {
  const { result } = show();
  await waitFor(() => expect(result.current.run?.id).toBe('run'));
  act(() => sources[0]!.onerror?.());
  await waitFor(() => expect(sources).toHaveLength(2), { timeout: 3000 });
  act(() =>
    sources[1]!.onmessage?.(
      new MessageEvent('message', {
        data: JSON.stringify({
          run_id: 'run',
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
  await waitFor(() => expect(result.current.run?.id).toBe('run'));
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
  await waitFor(() => expect(result.current.run?.id).toBe('run'));
  act(() => sources[0]!.onmessage?.(new MessageEvent('message', { data: '{broken' })));
  await waitFor(() => expect(sources).toHaveLength(2), { timeout: 3000 });
  unmount();
  expect(sources.every((source) => source.closed)).toBe(true);
});
