import { fixtureId, fixtureHash } from '@/shared/api/test-network-fixtures';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { expect, it } from 'vitest';
import { questionSchema } from '../../shared/api/clarifications';
import { QuestionDetails } from './question-details';

it('keeps old and new source wording comparable without binding an old version to the current analysis', async () => {
  const source = {
    file_id: fixtureId('file'),
    version_id: fixtureId('v2'),
    sha256: fixtureHash('new-hash'),
    fragment_id: fixtureId('fragment-v2'),
    locator: { kind: 'lines', start: 1, end: 1, section: 'Срок' },
    quote: 'Хранить отчёты 7 дней, удаление разрешено администратору.',
    status: 'verified',
    reason: null,
  };
  const question = questionSchema.parse({
    source_fingerprints: {},
    requirement_fingerprints: {},
    requirement_basis_fingerprints: {},
    mandatory_conflict: null,

    id: fixtureId('question'),
    gap_key: 'retention',
    revision: 2,
    text: 'Каков срок хранения?',
    basis: 'Требуется уточнить срок.',
    previous_basis: 'Требуется уточнить срок.',
    dependent_decision: 'Хранилище',
    blocking: true,
    status: 'open',
    requirement_ids: [fixtureId('r1')],
    sources: [source],
    previous_sources: [
      {
        ...source,
        version_id: fixtureId('v1'),
        sha256: fixtureHash('old-hash'),
        fragment_id: fixtureId('fragment-v1'),
        quote: 'Хранить отчёты 30 дней.',
      },
    ],
  });
  render(
    <MemoryRouter>
      <QuestionDetails
        question={question}
        runId={fixtureId('current-run')}
        compactSources={false}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText('Хранить отчёты 30 дней.')).not.toBeVisible();
  await userEvent.click(screen.getByText('Изменение основания'));
  const oldQuote = screen.getByText('Хранить отчёты 30 дней.');
  expect(oldQuote).toBeVisible();
  expect(screen.getByText(source.quote)).toBeVisible();
  const sourceCards = screen.getAllByRole('article');
  const previous = sourceCards.find((card) => within(card).queryByText('Хранить отчёты 30 дней.'));
  const current = sourceCards.find((card) => within(card).queryByText(source.quote));
  if (!previous || !current) throw new Error('Both source quotations must have their own card');
  expect(within(previous).getByRole('link', { name: /Источник/ })).toHaveAttribute(
    'href',
    `/documents?version=${fixtureId('v1')}&fragment=${fixtureId('fragment-v1')}`,
  );
  expect(within(current).getByRole('link', { name: /Источник/ })).toHaveAttribute(
    'href',
    `/documents?version=${fixtureId('v2')}&fragment=${fixtureId('fragment-v2')}&run=${fixtureId('current-run')}`,
  );
});
