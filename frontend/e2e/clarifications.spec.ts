import { expect, test, type Page } from '@playwright/test';
import { z } from 'zod';
import { send, waitForCompletedResponse, answers } from './chat-helpers';
import {
  fillAnswer,
  readClarifications,
  removeSelectedTestSource,
  restartWithVolumes,
  runStatus,
  uploadAndAnalyze,
  uploadTextAndAnalyze,
} from './clarification-helpers';

test('А–Б: discuss a real incomplete input, restart with volumes, save one answer and retain original evidence', async ({
  page,
  context,
}) => {
  test.setTimeout(120000);
  test.skip(!process.env['SAA_QUALITY_PROJECT'], 'Restart requires the isolated quality runtime');
  const { run, version } = await uploadAndAnalyze(page, 'incomplete');
  await expect(page.getByText('Ожидает ответа архитектора', { exact: true })).toBeVisible();
  const before = await readClarifications(page, run);
  expect(before.questions).toHaveLength(1);
  const question = before.questions[0];
  if (!question) throw new Error('Expected one blocking question');
  expect(question.blocking).toBe(true);
  await page
    .locator(`#requirement-${question.requirement_ids[0]}`)
    .getByRole('button', { name: 'Обсудить', exact: true })
    .click();
  await expect(page).toHaveURL(/\/chats\//);
  const chatPath = new URL(page.url()).pathname;
  await send(page, 'Срок хранения уже указан. Что именно нужно уточнить?');
  await waitForCompletedResponse(page);
  await expect(answers(page).last()).toContainText('Срок хранения уже указан');
  await expect(answers(page).last().getByRole('link', { name: 'R-03', exact: true })).toBeVisible();
  await expect(answers(page).last().getByRole('link', { name: 'R-04', exact: true })).toBeVisible();
  expect((await readClarifications(page, run)).questions[0]?.status).toBe('open');
  await restartWithVolumes(page);
  await page.close();
  const reopened = await context.newPage();
  await reopened.goto('/');
  await reopened.locator(`a[href="${chatPath}"]`).click();
  await expect(answers(reopened).last()).toContainText('Срок хранения уже указан');
  await expect(reopened.getByRole('region', { name: question.text, exact: true })).toBeVisible();
  const card = await fillAnswer(reopened, question);
  await card.getByRole('button', { name: 'Сохранить ответ', exact: true }).click();
  await expect.poll(async () => (await runStatus(reopened, run)).status).toBe('completed');
  await reopened.getByRole('link', { name: 'Вернуться к требованию', exact: true }).click();
  await reopened.getByRole('tab', { name: /^Уточнения / }).click();
  await expect(reopened.getByText('Добавил архитектор', { exact: true })).toBeVisible();
  const after = await readClarifications(reopened, run);
  expect(after.questions).toHaveLength(1);
  expect(after.decisions).toHaveLength(1);
  const requirement = after.requirements.find((item) => item.id === question.requirement_ids[0]);
  expect(requirement?.normalized_text).toContain(
    'Отклонять запрос и показывать допустимый диапазон дат',
  );
  expect(requirement?.original_text).not.toContain(
    'Отклонять запрос и показывать допустимый диапазон дат',
  );
  const source = await reopened.request.get(`/api/document-versions/${version.version_id}/content`);
  expect(await source.text()).not.toContain('Запрос даты вне окна отклоняется');
  await reopened.close();
});

for (const resolution of ['confirm', 'reject'] as const) {
  test(`В: accepted assumption resumes work and ${resolution} updates A-01/A-07`, async ({
    page,
  }) => {
    test.setTimeout(90000);
    const { run } = await uploadAndAnalyze(page, 'incomplete');
    const view = await readClarifications(page, run);
    const question = view.questions[0];
    if (!question) throw new Error('Expected a question');
    const card = await fillAnswer(page, question);
    await card.getByLabel('Принять как допущение', { exact: true }).check();
    await card.getByLabel('Ответственный', { exact: true }).fill('Архитектор');
    await card.getByLabel('Условие проверки', { exact: true }).fill('Подтвердить до реализации');
    await card.getByLabel('Последствия', { exact: true }).fill('Ошибочное отклонение запроса');
    await card.getByLabel('Способ снижения риска', { exact: true }).fill('Согласовать поведение');
    await card.getByRole('button', { name: 'Принять допущение', exact: true }).click();
    await expect.poll(async () => (await runStatus(page, run)).status).toBe('completed');
    await expect(page.getByText('Подлежит верификации', { exact: true })).toBeVisible();
    await page.getByRole('link', { name: 'Риск A-07', exact: true }).click();
    await expect(page.getByRole('region', { name: 'Риски A-07' })).toContainText(
      'Ошибочное отклонение запроса',
    );
    await page.getByRole('tab', { name: /^Уточнения / }).click();
    const accepted = await readClarifications(page, run);
    const requests = (await runStatus(page, run)).requests;
    await page
      .getByRole('combobox', { name: 'Решение по допущению', exact: true })
      .selectOption(resolution);
    await page
      .getByRole('textbox', { name: 'Причина решения', exact: true })
      .fill('Проверено заказчиком');
    await page.getByRole('button', { name: 'Сохранить решение', exact: true }).click();
    await expect
      .poll(async () => (await readClarifications(page, run)).risks[0]?.status)
      .toBe(resolution === 'confirm' ? 'closed' : 'realized');
    if (resolution === 'reject') {
      const revised = await readClarifications(page, run);
      expect(revised.completed_cycles).toEqual(accepted.completed_cycles);
      expect(revised.questions[0]?.revision).toBe(2);
      expect(revised.decisions[0]?.resolution_reason).toBe('Проверено заказчиком');
      const next = revised.questions[0];
      if (!next) throw new Error('Expected a new revision');
      const revisedCard = await fillAnswer(page, next, 'Уточнённое решение после пересмотра');
      await revisedCard.getByRole('button', { name: 'Сохранить ответ', exact: true }).click();
      await expect.poll(async () => (await runStatus(page, run)).status).toBe('completed');
      expect((await runStatus(page, run)).requests).toBe(requests);
      expect((await readClarifications(page, run)).completed_cycles).toHaveLength(2);
    } else {
      await expect(page.getByText('Допущение подтверждено', { exact: true })).toBeVisible();
    }
  });
}

test('Г: complete input does not block; requirement and source discussions preserve the original version after v2', async ({
  page,
}) => {
  test.setTimeout(90000);
  const { run, version } = await uploadAndAnalyze(page, 'complete');
  const view = await readClarifications(page, run);
  expect(view.questions).toHaveLength(0);
  expect((await runStatus(page, run)).status).toBe('completed');
  const requirement = view.requirements.find((item) => item.original_text.includes('R-04'));
  const source = requirement?.sources[0];
  if (!requirement || !source) throw new Error('Expected the R-04 source');
  await page
    .locator(`#requirement-${requirement.id}`)
    .getByRole('button', { name: 'Обсудить', exact: true })
    .click();
  await expect(
    page.getByRole('link', { name: 'Вернуться к требованию', exact: true }),
  ).toBeVisible();
  const requirementChat = new URL(page.url()).pathname;
  await page.goto(`/documents?version=${version.version_id}&fragment=${source.fragment_id}`);
  await page
    .locator('.selected-fragment')
    .getByRole('button', { name: 'Обсудить', exact: true })
    .click();
  await expect(page).toHaveURL(/\/chats\//);
  const sourceChat = new URL(page.url()).pathname;
  expect(sourceChat).not.toBe(requirementChat);
  const bindingResponse = await page.request.get(`/api${sourceChat}/discussion`);
  expect(bindingResponse.ok()).toBe(true);
  const bindingPayload: unknown = await bindingResponse.json();
  expect(z.object({ analysis_id: z.null(), history_id: z.null() }).parse(bindingPayload)).toEqual({
    analysis_id: null,
    history_id: null,
  });
  const updated = await page.request.post('/api/documents', {
    params: {
      operation_id: crypto.randomUUID(),
      filename: 'revision-2.md',
      file_id: version.file_id,
    },
    headers: { 'Content-Type': 'text/markdown' },
    data: '# Новая редакция\nИзменённое требование.',
  });
  expect(updated.ok()).toBe(true);
  await page.getByRole('link', { name: 'Вернуться к источнику', exact: true }).click();
  await expect(page).toHaveURL(
    new RegExp(`version=${version.version_id}&fragment=${source.fragment_id}`),
  );
  await expect(page.locator('.selected-fragment')).toContainText(
    'Запрос даты вне окна отклоняется',
  );
  await expect(page.locator('.selected-fragment')).not.toContainText('Изменённое требование');
});

test('two independent blockers expose the first effective requirement before the second answer', async ({
  page,
}) => {
  const { run } = await uploadTextAndAnalyze(
    page,
    Buffer.from('# Правила\n\nПервое условие. [clarification:two]\n\nВторое условие.'),
  );
  const view = await readClarifications(page, run);
  expect(view.questions).toHaveLength(2);
  const first = view.questions[0];
  const second = view.questions[1];
  if (!first || !second) throw new Error('Expected two questions');
  const card = await fillAnswer(page, first, 'Первое уточнение архитектора');
  await card.getByRole('button', { name: 'Сохранить ответ', exact: true }).click();
  await expect.poll(async () => (await readClarifications(page, run)).decisions.length).toBe(1);
  const partial = await readClarifications(page, run);
  expect(
    partial.requirements.find((item) => item.id === first.requirement_ids[0])?.normalized_text,
  ).toContain('Первое уточнение архитектора');
  expect(partial.questions.find((item) => item.id === second.id)?.status).toBe('open');
  expect((await runStatus(page, run)).status).toBe('waiting_input');
  const remaining = page
    .getByRole('region', { name: second.text, exact: true })
    .filter({ has: page.getByRole('textbox', { name: 'Ответ архитектора', exact: true }) })
    .first();
  await remaining
    .getByRole('textbox', { name: 'Ответ архитектора', exact: true })
    .fill('Второе уточнение');
  await remaining
    .getByRole('textbox', { name: 'Основание ответа', exact: true })
    .fill('Решение архитектора');
  await remaining.getByRole('button', { name: 'Сохранить ответ', exact: true }).click();
  await expect.poll(async () => (await runStatus(page, run)).status).toBe('completed');
});

test('nonblocking question remains visible without pausing the analysis', async ({ page }) => {
  const { run } = await uploadTextAndAnalyze(
    page,
    Buffer.from('# Правила\nУточнить предпочтение. [clarification:nonblocking]'),
  );
  expect((await runStatus(page, run)).status).toBe('completed');
  await page.getByRole('tab', { name: /^Уточнения / }).click();
  await expect(page.getByText('Неблокирующий', { exact: false })).toBeVisible();
  expect((await readClarifications(page, run)).questions[0]?.status).toBe('open');
});

test('one fragment keeps two explicit answer histories separate from a source-only discussion', async ({
  page,
}) => {
  test.setTimeout(90000);
  const { run: firstRun, version } = await uploadTextAndAnalyze(
    page,
    Buffer.from('# Правила\nПроверить ввод. [clarification:block]'),
  );
  const started = await page.request.post('/api/extractions', {
    data: {
      operation_id: crypto.randomUUID(),
      version_ids: [version.version_id],
      answer_history_mode: 'new',
    },
  });
  expect(started.ok()).toBe(true);
  const payload: unknown = await started.json();
  const secondRun = z.object({ id: z.string() }).parse(payload).id;
  const histories = [
    { run: firstRun, answer: 'Решение только истории А' },
    { run: secondRun, answer: 'Решение только истории Б' },
  ];
  let fragment: string | undefined;
  for (const history of histories) {
    await expect
      .poll(async () => (await runStatus(page, history.run)).status)
      .toBe('waiting_input');
    await page.goto(`/requirements?run=${history.run}`);
    const question = (await readClarifications(page, history.run)).questions[0];
    if (!question?.sources[0]) throw new Error('Expected a source-bound question');
    fragment ??= question.sources[0].fragment_id;
    expect(question.sources[0].fragment_id).toBe(fragment);
    const card = await fillAnswer(page, question, history.answer);
    await card.getByRole('button', { name: 'Сохранить ответ', exact: true }).click();
    await expect.poll(async () => (await runStatus(page, history.run)).status).toBe('completed');
  }
  for (const history of [...histories, null]) {
    await verifySourceHistory(page, version.version_id, fragment ?? '', history, histories);
  }
});

type HistoryAnswer = { run: string; answer: string };

async function verifySourceHistory(
  page: Page,
  version: string,
  fragment: string,
  history: HistoryAnswer | null,
  histories: HistoryAnswer[],
) {
  const parameters = new URLSearchParams({ version, fragment });
  if (history) parameters.set('run', history.run);
  await page.goto(`/documents?${parameters.toString()}`);
  await page
    .locator('.selected-fragment')
    .getByRole('button', { name: 'Обсудить', exact: true })
    .click();
  await expect(page).toHaveURL(/\/chats\//);
  const bindingResponse = await page.request.get(`/api${new URL(page.url()).pathname}/discussion`);
  expect(bindingResponse.ok()).toBe(true);
  const bindingPayload: unknown = await bindingResponse.json();
  const binding = z
    .object({ analysis_id: z.string().nullable(), history_id: z.string().nullable() })
    .parse(bindingPayload);
  expect(binding.analysis_id).toBe(history?.run ?? null);
  expect(binding.history_id).toBe(history?.run ?? null);
  const subject = page.getByRole('complementary', { name: 'Предмет и источники обсуждения' });
  for (const candidate of histories) {
    const answer = subject.getByText(candidate.answer, { exact: true });
    if (candidate === history) await expect(answer).toBeVisible();
    else await expect(answer).toHaveCount(0);
  }
}

for (const outcome of ['cancelled', 'failed'] as const) {
  test(`a resumed run can be ${outcome} and retains the recorded answer`, async ({ page }) => {
    test.setTimeout(90000);
    test.skip(!process.env['SAA_QUALITY_PROJECT'], 'Faults require an isolated quality runtime');
    const { run, storageKey } = await uploadTextAndAnalyze(
      page,
      Buffer.from('# Правила\nПроверить ввод. [clarification:block]'),
    );
    const question = (await readClarifications(page, run)).questions[0];
    if (!question) throw new Error('Expected a blocking question');
    const created = await page.request.post('/api/chats', {
      data: { title: `Hold-${crypto.randomUUID()}` },
    });
    const chatPayload: unknown = await created.json();
    const chat = z.object({ id: z.string() }).parse(chatPayload);
    const held = await page.request.post(`/api/chats/${chat.id}/runs`, {
      data: { command_id: crypto.randomUUID(), content: '[slow] Hold the generation slot' },
    });
    const heldPayload: unknown = await held.json();
    const heldRun = z.object({ id: z.string() }).parse(heldPayload);
    await expect
      .poll(async () => {
        const response = await page.request.get(`/api/runs/${heldRun.id}`);
        const value: unknown = await response.json();
        return z.object({ status: z.string() }).parse(value).status;
      })
      .toBe('running');
    const card = await fillAnswer(page, question);
    await card.getByRole('button', { name: 'Сохранить ответ', exact: true }).click();
    await expect.poll(async () => (await readClarifications(page, run)).decisions.length).toBe(1);
    if (outcome === 'failed') removeSelectedTestSource(storageKey);
    else await page.getByRole('button', { name: 'Отменить извлечение', exact: true }).click();
    await page.request.post(`/api/runs/${heldRun.id}/cancel`);
    await expect
      .poll(async () => (await runStatus(page, run)).status, { timeout: 30000 })
      .toBe(outcome);
    await page.reload();
    expect((await readClarifications(page, run)).decisions).toHaveLength(1);
    await expect(page.getByText('Добавил архитектор', { exact: true })).toBeVisible();
  });
}
