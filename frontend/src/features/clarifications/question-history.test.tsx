import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { expect, it } from 'vitest';
import { questionSchema } from '../../shared/api/clarifications';
import { QuestionDetails } from './question-details';

it('keeps old and new source wording comparable without binding an old version to the current analysis', async () => {
  const source = {
    file_id: 'file',
    version_id: 'v2',
    sha256: 'new-hash',
    fragment_id: 'fragment-v2',
    locator: { kind: 'lines', start: 1, end: 1, section: 'Срок' },
    quote: 'Хранить отчёты 7 дней, удаление разрешено администратору.',
    status: 'verified',
    reason: null,
  };
  const question = questionSchema.parse({
    id: 'question',
    gap_key: 'retention',
    revision: 2,
    text: 'Каков срок хранения?',
    basis: 'Требуется уточнить срок.',
    previous_basis: 'Требуется уточнить срок.',
    dependent_decision: 'Хранилище',
    blocking: true,
    status: 'open',
    requirement_ids: ['r1'],
    sources: [source],
    previous_sources: [
      {
        ...source,
        version_id: 'v1',
        sha256: 'old-hash',
        fragment_id: 'fragment-v1',
        quote: 'Хранить отчёты 30 дней.',
      },
    ],
  });
  render(
    <MemoryRouter>
      <QuestionDetails question={question} runId="current-run" compactSources={false} />
    </MemoryRouter>,
  );
  expect(screen.getByText('Хранить отчёты 30 дней.')).not.toBeVisible();
  await userEvent.click(screen.getByText('Изменение основания'));
  const oldQuote = screen.getByText('Хранить отчёты 30 дней.');
  expect(oldQuote).toBeVisible();
  expect(screen.getByText(source.quote)).toBeVisible();
  expect(within(oldQuote.closest('article')!).getByRole('link')).toHaveAttribute(
    'href',
    '/documents?version=v1&fragment=fragment-v1',
  );
  expect(
    within(screen.getByText(source.quote).closest('article')!).getByRole('link'),
  ).toHaveAttribute('href', '/documents?version=v2&fragment=fragment-v2&run=current-run');
});
