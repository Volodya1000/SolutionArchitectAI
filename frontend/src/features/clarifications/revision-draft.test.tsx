import { fixtureId, fixtureHash } from '@/shared/api/test-network-fixtures';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { type Question } from '../../shared/api/clarifications';
import { sessionStore } from '../../shared/ui/session-storage';
import { AnswerForm } from './answer-form';

const question: Question = {
  source_fingerprints: {},
  requirement_fingerprints: {},
  requirement_basis_fingerprints: {},

  id: fixtureId('q1'),
  gap_key: 'retention',
  revision: 1,
  text: 'Каков срок хранения?',
  basis: 'Первое основание',
  previous_basis: null,
  previous_sources: [],
  mandatory_conflict: null,
  dependent_decision: 'Выбор хранилища',
  blocking: true,
  status: 'open',
  requirement_ids: [fixtureId('r1')],
  sources: [],
};
const versions = [{ version_id: fixtureId('v1'), sha256: fixtureHash('first-hash') }];
const commands: unknown[] = [];
const server = setupServer(
  http.get('/api/clarification-operations/:id', () => new HttpResponse(null, { status: 404 })),
  http.post(
    `/api/extractions/${fixtureId('run')}/questions/${fixtureId('q1')}/answers`,
    async ({ request }) => {
      commands.push(await request.json());
      return new HttpResponse(null, { status: 503 });
    },
  ),
);
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterAll(() => server.close());
afterEach(() => {
  server.resetHandlers();
  sessionStore.clear();
  commands.length = 0;
});

function content(next = question, sources = versions) {
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AnswerForm runId={fixtureId('run')} question={next} sourceVersions={sources} />
    </QueryClientProvider>
  );
}

async function fillAssumption() {
  for (const [label, value] of [
    ['Ответ архитектора', 'Хранить 30 дней'],
    ['Основание ответа', 'Обсуждение команды'],
  ]) {
    await userEvent.type(screen.getByLabelText(label!), value!);
  }
  await userEvent.click(screen.getByLabelText('Принять как допущение'));
  for (const [label, value] of [
    ['Ответственный', 'Владелец данных'],
    ['Условие проверки', 'До проектирования'],
    ['Последствия', 'Потеря отчётов'],
    ['Способ снижения риска', 'Архив'],
  ]) {
    await userEvent.type(screen.getByLabelText(label!), value!);
  }
}

it('restores assumption mode and every field after the form is reopened', async () => {
  const first = render(content());
  await fillAssumption();
  first.unmount();
  render(content());
  expect(screen.getByLabelText('Принять как допущение')).toBeChecked();
  expect(screen.getByLabelText('Ответ архитектора')).toHaveValue('Хранить 30 дней');
  expect(screen.getByLabelText('Основание ответа')).toHaveValue('Обсуждение команды');
  expect(screen.getByLabelText('Ответственный')).toHaveValue('Владелец данных');
  expect(screen.getByLabelText('Условие проверки')).toHaveValue('До проектирования');
  expect(screen.getByLabelText('Последствия')).toHaveValue('Потеря отчётов');
  expect(screen.getByLabelText('Способ снижения риска')).toHaveValue('Архив');
});

it('requires an explicit transfer before submitting an old draft against a new revision', async () => {
  const view = render(content());
  await fillAssumption();
  view.rerender(
    content(
      {
        ...question,
        revision: 2,
        text: 'Каков срок для администратора?',
        basis: 'Новое основание',
      },
      [{ version_id: fixtureId('v2'), sha256: fixtureHash('second-hash') }],
    ),
  );
  expect(screen.getByRole('button', { name: 'Принять допущение' })).toBeDisabled();
  expect(screen.getByText('Каков срок хранения?')).toBeVisible();
  expect(screen.getByText('Каков срок для администратора?')).toBeVisible();
  fireEvent.submit(screen.getByRole('form', { name: /^Ответ на уточнение:/ }));
  expect(commands).toHaveLength(0);
  await userEvent.click(
    screen.getByRole('button', { name: 'Перенести черновик в текущую ревизию' }),
  );
  await userEvent.click(screen.getByRole('button', { name: 'Принять допущение' }));
  await waitFor(() => expect(commands).toHaveLength(1));
  expect(commands[0]).toMatchObject({
    expected_question_revision: 2,
    source_versions: [{ version_id: fixtureId('v2'), sha256: fixtureHash('second-hash') }],
    kind: 'assumption',
    text: 'Хранить 30 дней',
    basis: 'Обсуждение команды',
    assumption: {
      responsible: 'Владелец данных',
      verification_condition: 'До проектирования',
      consequences: 'Потеря отчётов',
      mitigation: 'Архив',
    },
  });
});

it('also requires transfer when pinned sources change without a revision increment', async () => {
  const view = render(content());
  await userEvent.type(screen.getByLabelText('Ответ архитектора'), 'Черновик');
  view.rerender(
    content(question, [{ version_id: fixtureId('v1'), sha256: fixtureHash('replaced-hash') }]),
  );
  expect(screen.getByRole('button', { name: 'Сохранить ответ' })).toBeDisabled();
  expect(
    screen.getByRole('button', { name: 'Перенести черновик в текущую ревизию' }),
  ).toBeVisible();
});
