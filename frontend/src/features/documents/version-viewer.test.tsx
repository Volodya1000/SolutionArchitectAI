import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter } from 'react-router';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import type { DocumentVersion, ParsedDocument } from '../../shared/api/documents';
import { fixtureHash, fixtureId } from '../../shared/api/test-network-fixtures';
import { VersionViewer } from './version-viewer';

const separator = '| --- | --- |';
const versionId = fixtureId('version');
const parsed: ParsedDocument = {
  file_id: fixtureId('file'),
  version_id: versionId,
  sha256: fixtureHash('source'),
  parser_version: 'documents-v1',
  text: `| ID | Rule |\n${separator}\n| Kafka | Keep 30 days |`,
  fragments: [
    {
      fragment_id: fixtureId('header'),
      text: '| ID | Rule |',
      locator: { kind: 'lines', start: 48, end: 48, section: '', path: '' },
    },
    {
      fragment_id: fixtureId('delimiter'),
      text: separator,
      locator: { kind: 'lines', start: 49, end: 49, section: '', path: '' },
    },
    {
      fragment_id: fixtureId('kafka'),
      text: '| Kafka | Keep 30 days |',
      locator: { kind: 'lines', start: 50, end: 50, section: '', path: '' },
    },
  ],
  warnings: [],
  structure: {
    tables: [{ header_line: 48, delimiter_line: 49, end_line: 50, header_text: '| ID | Rule |' }],
  },
};
const version: DocumentVersion = {
  file_id: fixtureId('file'),
  task_id: fixtureId('task'),
  version_id: versionId,
  sha256: fixtureHash('source'),
  mime_type: 'text/markdown',
  size: 1,
  original_name: 'rules.md',
  uploaded_at: '2026-11-28T12:00:00Z',
  storage_key: `${fixtureId('task')}/${versionId}`,
};
const server = setupServer(
  http.get('/api/document-versions/:id', () => HttpResponse.json(version)),
  http.get('/api/document-versions/:id/parsed', () => HttpResponse.json(parsed)),
);
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterAll(() => server.close());
afterEach(() => server.resetHandlers());

function show(fragmentId: string | null = null) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <VersionViewer versionId={versionId} fragmentId={fragmentId} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it('shows Kafka with its physical line while omitting the technical separator card', async () => {
  show();
  expect(await screen.findByText('| Kafka | Keep 30 days |')).toBeVisible();
  expect(screen.queryByText(separator)).not.toBeInTheDocument();
  const kafka = screen.getByRole('article', { name: 'Строка 50' });
  expect(within(kafka).getByRole('button', { name: 'Обсудить' })).toBeVisible();
});

it('resolves a saved separator fragment link without offering a discussion card', async () => {
  show(fixtureId('delimiter'));
  expect(await screen.findByText(separator)).toBeVisible();
  expect(screen.queryByRole('article', { name: 'Строка 49' })).not.toBeInTheDocument();
  expect(screen.queryByText(/Указанный фрагмент отсутствует/)).not.toBeInTheDocument();
});
