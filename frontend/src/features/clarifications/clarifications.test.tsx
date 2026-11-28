import { fixtureId } from '@/shared/api/test-network-fixtures';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MemoryRouter } from 'react-router';
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest';
import { z } from 'zod';
import { sessionStore } from '../../shared/ui/session-storage';
import { Clarifications, DiscussionHeader } from './index';
import { answerSchema, clarificationSchema, type Decision } from '../../shared/api/clarifications';
import { savedValue } from './saved-command';
import { HumanDecision } from './decision';
import { draftIsCurrent, draftSchema, pinDraft } from './answer-draft';

const question = {
  source_fingerprints: {},
  requirement_fingerprints: {},
  requirement_basis_fingerprints: {},
  previous_sources: [],
  mandatory_conflict: null,

  id: fixtureId('q1'),
  gap_key: 'retention',
  revision: 1,
  text: 'Каков срок?',
  basis: 'Срок отсутствует',
  dependent_decision: 'Выбор хранилища',
  blocking: true,
  requirement_ids: [fixtureId('r1')],
  sources: [],
  status: 'open',
  previous_basis: null,
};
const view = {
  ...{ conflict_assessments: [] },
  metadata: null,
  resume_version: 0,

  run_id: fixtureId('run'),
  history_id: fixtureId('history'),
  initialized: true,
  cycle: 0,
  resume_pending: false,
  questions: [question, { ...question, id: fixtureId('q2'), text: 'Каков объём?' }],
  decisions: [],
  risks: [],
  requirements: [],
  completed_cycles: [],
};
let current = clarificationSchema.parse(view);

it('keeps a serialized draft current when generated schemas reorder source properties', () => {
  const selected = clarificationSchema.parse(view).questions[0]!;
  const sources = [{ version_id: fixtureId('v1'), sha256: 'a'.repeat(64) }];
  const saved = pinDraft(selected, sources);
  const restored = draftSchema.parse(JSON.parse(JSON.stringify(saved)));
  expect(draftIsCurrent(restored, selected, sources)).toBe(true);
  expect(draftIsCurrent(restored, selected, [{ ...sources[0]!, sha256: 'b'.repeat(64) }])).toBe(
    false,
  );
  expect(
    draftIsCurrent(restored, selected, [{ ...sources[0]!, version_id: fixtureId('v2') }]),
  ).toBe(false);
});
const server = setupServer(
  http.get('/api/clarification-operations/:id', () => new HttpResponse(null, { status: 404 })),
  http.get(`/api/extractions/${fixtureId('run')}/clarifications`, () => HttpResponse.json(current)),
);
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterAll(() => server.close());
afterEach(() => {
  server.resetHandlers();
  sessionStore.clear();
  current = clarificationSchema.parse(view);
});
function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Clarifications runId={fixtureId('run')} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}
it('offers factual resolution for an assumed mandatory conflict', async () => {
  current = {
    ...current,
    questions: [
      { ...current.questions[0]!, status: 'assumed', mandatory_conflict: 'Правило нарушено' },
    ],
  };
  show();
  const card = await screen.findByRole('region', { name: question.text });
  expect(within(card).getByRole('button', { name: 'Сохранить ответ' })).toBeEnabled();
  expect(within(card).queryByLabelText('Принять как допущение')).not.toBeInTheDocument();
});

it('retains a draft on a stale revision and refreshes the shared cards', async () => {
  server.use(
    http.post(`/api/extractions/${fixtureId('run')}/questions/${fixtureId('q1')}/answers`, () => {
      current = {
        ...current,
        questions: [
          { ...current.questions[0]!, revision: 2, basis: 'Новое основание' },
          current.questions[1]!,
        ],
      };
      return HttpResponse.json({ code: 'stale_question_revision' }, { status: 409 });
    }),
  );
  show();
  const input = (await screen.findAllByLabelText('Ответ архитектора'))[0]!;
  await userEvent.type(input, 'Хранить 90 дней');
  await userEvent.type(screen.getAllByLabelText('Основание ответа')[0]!, 'Решение команды');
  await userEvent.click(screen.getAllByRole('button', { name: 'Сохранить ответ' })[0]!);
  expect(
    within(await screen.findByRole('region', { name: 'Черновик прежней ревизии' })).getByText(
      'Новое основание',
    ),
  ).toBeVisible();
  expect(input).toHaveValue('Хранить 90 дней');
  expect(screen.getByRole('alert')).toHaveTextContent(/ревизия/i);
});
it('updates the first answer while an independent blocker remains open', async () => {
  server.use(
    http.post(
      `/api/extractions/${fixtureId('run')}/questions/${fixtureId('q1')}/answers`,
      async ({ request }) => {
        const command: unknown = await request.json();
        expect(command).toMatchObject({
          expected_question_revision: 1,
          kind: 'answer',
          text: '90 дней',
        });
        current = {
          ...current,
          questions: [{ ...current.questions[0]!, status: 'answered' }, current.questions[1]!],
        };
        return HttpResponse.json({
          source_versions: [],
          resolved_at: null,
          resolved_by: null,
          resolved_author: null,

          operation_id: fixtureId('op'),
          run_id: fixtureId('run'),
          question_id: fixtureId('q1'),
          question_revision: 1,
          decision_id: fixtureId('d1'),
          kind: 'answer',
          text: '90 дней',
          basis: 'Политика',
          author_id: fixtureId('actor'),
          author: 'Архитектор',
          created_at: '2026-11-27T00:00:00Z',
          requirement_ids: [fixtureId('r1')],
          assumption: null,
          risk_id: null,
          resolution: 'pending',
          resolution_reason: null,
          revision: 1,
        });
      },
    ),
  );
  show();
  await userEvent.type((await screen.findAllByLabelText('Ответ архитектора'))[0]!, '90 дней');
  await userEvent.type(screen.getAllByLabelText('Основание ответа')[0]!, 'Политика');
  await userEvent.click(screen.getAllByRole('button', { name: 'Сохранить ответ' })[0]!);
  await waitFor(() => expect(screen.getByText('Блокирующих вопросов: 1')).toBeVisible());
  expect(screen.getAllByLabelText('Ответ архитектора')).toHaveLength(1);
});

const acceptedAssumption: Decision = {
  source_versions: [],
  resolved_at: null,
  resolved_by: null,
  resolved_author: null,

  operation_id: fixtureId('op'),
  run_id: fixtureId('run'),
  question_id: fixtureId('q1'),
  question_revision: 1,
  decision_id: fixtureId('d1'),
  kind: 'assumption',
  text: '90 дней',
  basis: 'Проверить с владельцем',
  author_id: fixtureId('actor'),
  author: 'Архитектор',
  created_at: '2026-11-27T00:00:00Z',
  requirement_ids: [fixtureId('r1')],
  assumption: {
    responsible: 'Владелец',
    verification_condition: 'До проектирования',
    consequences: 'Переполнение',
    mitigation: 'Квоты',
  },
  risk_id: fixtureId('risk'),
  resolution: 'pending',
  resolution_reason: null,
  revision: 1,
};

it('keeps a legacy resolution actor identifier inside technical disclosure', () => {
  render(
    <MemoryRouter>
      <HumanDecision
        decision={{
          ...acceptedAssumption,
          resolution: 'confirmed',
          resolved_by: fixtureId('legacy-actor-id'),
          resolved_at: '2026-11-27T12:00:00Z',
        }}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText(fixtureId('legacy-actor-id'), { exact: false })).not.toBeVisible();
});

it('shows the immutable question revision attached to a saved decision', () => {
  render(
    <MemoryRouter>
      <HumanDecision
        decision={{
          ...acceptedAssumption,
          resolution: 'confirmed',
          question_revision: 1,
          revision: 3,
        }}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText('Ревизия вопроса')).toBeVisible();
  expect(screen.getAllByRole('definition').map((item) => item.textContent)).toContain('1');
});

it.each(['confirm', 'reject'] as const)(
  'saves an assumption and synchronizes its risk on %s',
  async (resolution) => {
    server.use(
      http.post(
        `/api/extractions/${fixtureId('run')}/questions/${fixtureId('q1')}/answers`,
        async ({ request }) => {
          expect(await request.json()).toMatchObject({
            kind: 'assumption',
            assumption: acceptedAssumption.assumption,
          });
          current = {
            ...current,
            questions: [{ ...current.questions[0]!, status: 'assumed' }],
            decisions: [acceptedAssumption],
            risks: [
              {
                id: fixtureId('risk'),
                decision_id: fixtureId('d1'),
                consequences: 'Переполнение',
                mitigation: 'Квоты',
                status: 'open',
                resolution_reason: null,
              },
            ],
            completed_cycles: [
              {
                requirements: [],
                cycle: 0,
                completed_at: acceptedAssumption.created_at,
                decision_ids: [fixtureId('d1')],
              },
            ],
          };
          return HttpResponse.json(acceptedAssumption);
        },
      ),
      http.post(`/api/assumptions/${fixtureId('d1')}/resolve`, async ({ request }) => {
        expect(await request.json()).toMatchObject({
          resolution,
          expected_revision: 1,
          reason: 'Проверено',
        });
        const decision = {
          ...acceptedAssumption,
          resolution: resolution === 'confirm' ? ('confirmed' as const) : ('rejected' as const),
          resolution_reason: 'Проверено',
          resolved_by: fixtureId('reviewer'),
          resolved_author: 'Проверяющий',
          resolved_at: '2026-11-27T12:00:00Z',
          revision: 2,
        };
        current = {
          ...current,
          decisions: [decision],
          risks: [
            {
              ...current.risks[0]!,
              status: resolution === 'confirm' ? 'closed' : 'realized',
              resolution_reason: 'Проверено',
            },
          ],
        };
        return HttpResponse.json(decision);
      }),
    );
    show();
    await userEvent.type((await screen.findAllByLabelText('Ответ архитектора'))[0]!, '90 дней');
    await userEvent.type(
      screen.getAllByLabelText('Основание ответа')[0]!,
      'Проверить с владельцем',
    );
    await userEvent.click(screen.getAllByLabelText('Принять как допущение')[0]!);
    for (const [label, text] of [
      ['Ответственный', 'Владелец'],
      ['Условие проверки', 'До проектирования'],
      ['Последствия', 'Переполнение'],
      ['Способ снижения риска', 'Квоты'],
    ]) {
      await userEvent.type(screen.getByLabelText(label!), text!);
    }
    await userEvent.click(screen.getByRole('button', { name: 'Принять допущение' }));
    expect(await screen.findByRole('link', { name: 'Риск A-07' })).toHaveAttribute(
      'href',
      `/#risk-${fixtureId('risk')}`,
    );
    expect(screen.getByText('Архитектор', { exact: true })).toBeVisible();
    expect(screen.getAllByText('Подлежит верификации', { exact: true })).toHaveLength(1);
    expect(screen.getByText('Завершённые циклы: 1')).toBeVisible();
    await userEvent.selectOptions(screen.getByLabelText('Решение по допущению'), resolution);
    await userEvent.type(screen.getByLabelText('Причина решения'), 'Проверено');
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить решение' }));
    expect(
      await screen.findByText(resolution === 'confirm' ? 'Закрыт' : 'Реализовался'),
    ).toBeVisible();
    expect(screen.getByText(/Решение: Проверяющий/)).toBeVisible();
    expect(
      screen.getByText(new Date('2026-11-27T12:00:00Z').toLocaleString('ru-RU')),
    ).toHaveAttribute('datetime', '2026-11-27T12:00:00Z');
    expect(
      screen.getByText(
        resolution === 'confirm'
          ? 'Допущение подтверждено'
          : 'Допущение отклонено — требуется пересмотр',
      ),
    ).toBeVisible();
  },
);

it('recovers an uncertain answer using the original payload after the draft is edited', async () => {
  const commands: unknown[] = [];
  server.use(
    http.post(
      `/api/extractions/${fixtureId('run')}/questions/${fixtureId('q1')}/answers`,
      async ({ request }) => {
        commands.push(await request.json());
        return new HttpResponse(null, { status: 503 });
      },
    ),
  );
  show();
  const input = (await screen.findAllByLabelText('Ответ архитектора'))[0]!;
  await userEvent.type(input, '90 дней');
  await userEvent.type(screen.getAllByLabelText('Основание ответа')[0]!, 'Политика');
  await userEvent.click(screen.getAllByRole('button', { name: 'Сохранить ответ' })[0]!);
  await screen.findByRole('alert');
  await userEvent.type(input, ' и архив');
  await userEvent.click(screen.getByRole('button', { name: 'Повторить сохранённый ответ' }));
  await waitFor(() => expect(commands).toHaveLength(2));
  expect(commands[1]).toEqual(commands[0]);
  expect(input).toHaveValue('90 дней и архив');
});

it('keeps the new revision draft when recovering a committed answer to an older revision', async () => {
  current = { ...current, questions: [{ ...current.questions[0]!, revision: 2 }] };
  savedValue(`answer:${fixtureId('run')}:${fixtureId('q1')}`, answerSchema).save({
    operation_id: fixtureId('op'),
    expected_question_revision: 1,
    source_versions: [],
    kind: 'assumption',
    text: '90 дней',
    basis: 'До проверки',
    assumption: acceptedAssumption.assumption,
  });
  server.use(
    http.get(`/api/clarification-operations/${fixtureId('op')}`, () =>
      HttpResponse.json(acceptedAssumption),
    ),
  );
  show();
  const input = (await screen.findAllByLabelText('Ответ архитектора'))[0]!;
  await userEvent.type(input, 'Новое решение после пересмотра');
  await userEvent.type(screen.getByLabelText('Основание ответа'), 'Пересмотр');
  await screen.findByRole('button', { name: 'Сохранить ответ' });
  expect(
    screen.queryByRole('button', { name: 'Повторить сохранённый ответ' }),
  ).not.toBeInTheDocument();
  expect(
    savedValue(
      `draft:${fixtureId('run')}:${fixtureId('q1')}`,
      z.object({ text: z.string() }),
    ).read()?.text,
  ).toBe('Новое решение после пересмотра');
  expect(input).toHaveValue('Новое решение после пересмотра');
  expect(screen.getByText(/Ответ для текущей ревизии ещё не сохранён/)).toBeVisible();
});

it('renders the pinned discussion subject and the same analysis question cards', async () => {
  server.use(
    http.get(`/api/chats/${fixtureId('chat')}/discussion/clarifications`, () =>
      HttpResponse.json(current),
    ),
    http.get(`/api/chats/${fixtureId('chat')}/discussion`, () =>
      HttpResponse.json({
        chat_id: fixtureId('chat'),
        kind: 'requirement',
        title: 'Обсуждение срока',
        analysis_id: fixtureId('run'),
        requirement_id: fixtureId('r1'),
        version_id: null,
        fragment_id: null,
        version_ids: [fixtureId('v1')],
        history_id: fixtureId('history'),
        backlink: `/requirements?run=${fixtureId('run')}&requirement=${fixtureId('r1')}`,
      }),
    ),
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <DiscussionHeader chatId={fixtureId('chat')} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByText('Обсуждение срока')).toBeVisible();
  expect(await screen.findByText('Каков срок?')).toBeVisible();
  expect(screen.getByRole('link', { name: 'Вернуться к требованию' })).toHaveAttribute(
    'href',
    `/requirements?run=${fixtureId('run')}&requirement=${fixtureId('r1')}`,
  );
});
