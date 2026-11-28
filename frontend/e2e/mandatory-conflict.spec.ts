import { expect, test } from '@playwright/test';
import {
  fillAnswer,
  readClarifications,
  runStatus,
  uploadTextAndAnalyze,
} from './clarification-helpers';

test('mandatory conflict survives assumption confirmation and accepts factual resolution in the same run', async ({
  page,
}) => {
  test.setTimeout(90000);
  const { run } = await uploadTextAndAnalyze(
    page,
    Buffer.from(
      [
        '# Обязательное правило [clarification:mandatory-conflict]',
        'Обязательное правило: хранить записи не менее 30 дней.',
        'Требование: удалять записи через 7 дней.',
      ].join('\n\n'),
    ),
  );
  const initial = await readClarifications(page, run);
  expect(initial.questions).toHaveLength(1);
  expect(initial.conflict_assessments[0]?.status).toBe('confirmed');
  expect(initial.conflict_assessments[0]?.sources).toHaveLength(2);
  const question = initial.questions[0];
  if (!question?.mandatory_conflict)
    throw new Error('Expected an independently proven mandatory conflict');
  expect(question.sources).toHaveLength(2);
  expect((await runStatus(page, run)).status).toBe('waiting_input');
  const requests = (await runStatus(page, run)).requests;
  const card = await fillAnswer(page, question, 'Временно принять удаление через 7 дней');
  await expect(card.getByRole('alert')).toContainText(question.mandatory_conflict);
  await card.getByLabel('Принять как допущение', { exact: true }).check();
  await card.getByLabel('Ответственный', { exact: true }).fill('Архитектор');
  await card.getByLabel('Условие проверки', { exact: true }).fill('Проверить обязательный срок');
  await card
    .getByLabel('Последствия', { exact: true })
    .fill('Нарушение обязательного срока хранения');
  await card
    .getByLabel('Способ снижения риска', { exact: true })
    .fill('Получить фактическое урегулирование');
  await card.getByRole('button', { name: 'Принять допущение', exact: true }).click();
  await expect
    .poll(async () => (await readClarifications(page, run)).questions[0]?.status)
    .toBe('assumed');
  await expect(card).toContainText('Допущение не устраняет обязательный конфликт');
  expect((await runStatus(page, run)).status).toBe('waiting_input');
  await card.getByRole('link', { name: 'Риск A-07', exact: true }).click();
  const risks = page.getByRole('region', { name: 'Риски A-07', exact: true });
  await expect(risks).toContainText('Нарушение обязательного срока хранения');
  await expect(risks).toContainText('Открыт');
  await risks.getByRole('link', { name: 'Допущение A-01', exact: true }).click();
  const assumed = page.getByRole('region', { name: question.text, exact: true }).first();
  await assumed
    .getByRole('combobox', { name: 'Решение по допущению', exact: true })
    .selectOption('confirm');
  const reason =
    'Проверка допущения завершена; обязательное противоречие ещё требует фактического решения';
  await assumed.getByRole('textbox', { name: 'Причина решения', exact: true }).fill(reason);
  await assumed.getByRole('button', { name: 'Сохранить решение', exact: true }).click();
  await expect
    .poll(async () => (await readClarifications(page, run)).questions[0]?.revision)
    .toBe(2);
  await expect
    .poll(async () => (await readClarifications(page, run)).risks[0]?.status)
    .toBe('closed');
  expect((await runStatus(page, run)).status).toBe('waiting_input');
  await expect(assumed.getByRole('alert')).toContainText(question.mandatory_conflict);
  await expect(assumed).toContainText(reason);
  await expect(
    assumed.getByRole('textbox', { name: 'Ответ архитектора', exact: true }),
  ).toBeVisible();
  await assumed.getByRole('link', { name: 'Риск A-07', exact: true }).click();
  await expect(risks).toContainText('Закрыт');
  await expect(risks).toContainText(reason);
  await risks.getByRole('link', { name: 'Допущение A-01', exact: true }).click();
  const revised = (await readClarifications(page, run)).questions[0];
  if (!revised) throw new Error('Expected the reopened mandatory conflict');
  const factual = await fillAnswer(
    page,
    revised,
    'Записи хранятся не менее 30 дней; удаление через 7 дней отменено',
  );
  await factual.getByRole('button', { name: 'Сохранить ответ', exact: true }).click();
  await expect.poll(async () => (await runStatus(page, run)).status).toBe('completed');
  expect(new URL(page.url()).searchParams.get('run')).toBe(run);
  expect((await runStatus(page, run)).requests).toBe(requests);
  const completed = await readClarifications(page, run);
  expect(completed.questions[0]?.status).toBe('answered');
  expect(completed.questions[0]?.revision).toBe(2);
  expect(completed.decisions).toHaveLength(2);
  expect(completed.decisions[0]).toMatchObject({
    kind: 'assumption',
    question_revision: 1,
    resolution: 'confirmed',
  });
  expect(completed.decisions[1]).toMatchObject({ kind: 'answer', question_revision: 2 });
  expect(completed.risks).toHaveLength(1);
  expect(completed.risks[0]?.status).toBe('closed');
  await expect(factual.getByText('Допущение подтверждено', { exact: true })).toBeVisible();
  await expect(factual.getByText('Добавил архитектор', { exact: true })).toBeVisible();
  await factual.getByRole('link', { name: 'Риск A-07', exact: true }).click();
  await expect(risks).toContainText('Закрыт');
  await expect(risks).toContainText(reason);
});
