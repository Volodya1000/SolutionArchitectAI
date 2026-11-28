import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { matchingExtractions } from './extractions';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterAll(() => server.close());
afterEach(() => server.resetHandlers());

it.each([
  { newHistory: false, historyId: null, expectedMode: 'reuse', expectedHistory: null },
  {
    newHistory: false,
    historyId: '10000000-0000-4000-8000-000000000003',
    expectedMode: 'reuse',
    expectedHistory: '10000000-0000-4000-8000-000000000003',
  },
  {
    newHistory: true,
    historyId: '10000000-0000-4000-8000-000000000003',
    expectedMode: 'new',
    expectedHistory: null,
  },
])(
  'sends the selected versions, trimmed scope and explicit history ($expectedMode / $expectedHistory)',
  async ({ newHistory, historyId, expectedMode, expectedHistory }) => {
    let received: URL | undefined;
    server.use(
      http.get('/api/extractions/matching', ({ request }) => {
        received = new URL(request.url);
        return HttpResponse.json({ active: null, current_completed: null, latest_completed: null });
      }),
    );
    await matchingExtractions(
      new Set(['10000000-0000-4000-8000-000000000002', '10000000-0000-4000-8000-000000000001']),
      '  Данные  ',
      newHistory,
      historyId,
    );
    expect(received?.searchParams.getAll('version_ids')).toEqual([
      '10000000-0000-4000-8000-000000000001',
      '10000000-0000-4000-8000-000000000002',
    ]);
    expect(received?.searchParams.get('analysis_scope')).toBe('Данные');
    expect(received?.searchParams.get('answer_history_mode')).toBe(expectedMode);
    expect(received?.searchParams.get('answer_history_id')).toBe(expectedHistory);
  },
);
