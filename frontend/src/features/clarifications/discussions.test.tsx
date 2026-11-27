import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter } from 'react-router';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { sessionStore } from '../../shared/ui/session-storage';
import { DiscussButton } from './index';

const commands: unknown[] = [];
let fail = false;
const server = setupServer(
  http.post('/api/discussions', async ({ request }) => {
    commands.push(await request.json());
    return fail
      ? new HttpResponse(null, { status: 503 })
      : HttpResponse.json({
          id: 'chat',
          task_id: 'task',
          title: 'Обсуждение',
          created_at: '2026-11-27T00:00:00Z',
        });
  }),
  http.get('/api/discussion-operations/:id', () => new HttpResponse(null, { status: 404 })),
);
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterAll(() => server.close());
afterEach(() => {
  server.resetHandlers();
  sessionStore.clear();
  commands.length = 0;
  fail = false;
});
function show(analysisId: string | null = null) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <DiscussButton
          subject={{
            kind: 'source',
            version_id: 'v1',
            fragment_id: 'fragment',
            analysis_id: analysisId,
          }}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
it('creates separate intentional discussions and replays the original uncertain operation', async () => {
  show();
  await userEvent.click(screen.getByRole('button', { name: 'Обсудить' }));
  await waitFor(() => expect(commands).toHaveLength(1));
  await userEvent.click(screen.getByRole('button', { name: 'Обсудить' }));
  await waitFor(() => expect(commands).toHaveLength(2));
  expect(commands[0]).not.toEqual(commands[1]);
  fail = true;
  await userEvent.click(screen.getByRole('button', { name: 'Обсудить' }));
  await screen.findByRole('alert');
  fail = false;
  await userEvent.click(screen.getByRole('button', { name: 'Повторить обсуждение' }));
  await waitFor(() => expect(commands).toHaveLength(4));
  expect(commands[3]).toEqual(commands[2]);
});

it('recovers a saved discussion operation after reopening the source', async () => {
  fail = true;
  const first = show('analysis-a');
  await userEvent.click(screen.getByRole('button', { name: 'Обсудить' }));
  await screen.findByRole('alert');
  first.unmount();
  fail = false;
  show('analysis-a');
  const retry = await screen.findByRole('button', { name: 'Повторить обсуждение' });
  await waitFor(() => expect(retry).toBeEnabled());
  await userEvent.click(retry);
  await waitFor(() => expect(commands).toHaveLength(2));
  expect(commands[1]).toEqual(commands[0]);
});

it('keeps uncertain operations separate when one source switches between analysis histories', async () => {
  const client = new QueryClient();
  const content = (analysisId: string) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DiscussButton
          subject={{
            kind: 'source',
            version_id: 'v1',
            fragment_id: 'fragment',
            analysis_id: analysisId,
          }}
        />
      </MemoryRouter>
    </QueryClientProvider>
  );
  fail = true;
  const view = render(content('analysis-a'));
  await userEvent.click(screen.getByRole('button', { name: 'Обсудить' }));
  await screen.findByRole('alert');
  view.rerender(content('analysis-b'));
  fail = false;
  await userEvent.click(screen.getByRole('button', { name: 'Обсудить' }));
  await waitFor(() => expect(commands).toHaveLength(2));
  expect(commands[1]).toMatchObject({ subject: { analysis_id: 'analysis-b' } });
  view.rerender(content('analysis-a'));
  expect(screen.getByRole('button', { name: 'Повторить обсуждение' })).toBeInTheDocument();
});
it.each([null, 'analysis-a', 'analysis-b'])(
  'pins the explicit source history %s',
  async (analysisId) => {
    show(analysisId);
    await userEvent.click(screen.getByRole('button', { name: 'Обсудить' }));
    await waitFor(() => expect(commands).toHaveLength(1));
    expect(commands[0]).toMatchObject({
      subject: { version_id: 'v1', fragment_id: 'fragment', analysis_id: analysisId },
    });
  },
);
