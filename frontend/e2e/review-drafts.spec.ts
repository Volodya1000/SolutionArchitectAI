import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Locator, type Page } from '@playwright/test';
import {
  fillAnswer,
  readClarifications,
  runStatus,
  uploadTextAndAnalyze,
} from './clarification-helpers';

const assumptionFields = [
  ['Ответственный', 'Владелец данных'],
  ['Условие проверки', 'Проверить до реализации'],
  ['Последствия', 'Потеря отчётов'],
  ['Способ снижения риска', 'Архивировать данные'],
] as const;

async function fillAssumption(card: Locator) {
  await card.getByLabel('Принять как допущение', { exact: true }).check();
  for (const [label, value] of assumptionFields)
    await card.getByRole('textbox', { name: label, exact: true }).fill(value);
}

async function newBlockedAnalysis(page: Page) {
  const result = await uploadTextAndAnalyze(
    page,
    Buffer.from('# Правила\nПроверить ввод. [clarification:block]'),
  );
  const question = (await readClarifications(page, result.run)).questions[0];
  if (!question) throw new Error('Expected a blocking question');
  return { ...result, question };
}

test('a draft in one tab cannot silently answer the revision reopened from another tab', async ({
  page,
}, testInfo) => {
  test.setTimeout(90000);
  const { run, question } = await newBlockedAnalysis(page);
  await fillAnswer(page, question, 'Черновик первой ревизии');
  const other = await page.context().newPage();
  await other.goto(`/requirements?run=${run}`);
  const otherCard = await fillAnswer(other, question, 'Решение из второй вкладки');
  await fillAssumption(otherCard);
  await otherCard.getByRole('button', { name: 'Принять допущение', exact: true }).click();
  await expect.poll(async () => (await runStatus(other, run)).status).toBe('completed');
  await otherCard
    .getByRole('combobox', { name: 'Решение по допущению', exact: true })
    .selectOption('reject');
  await otherCard
    .getByRole('textbox', { name: 'Причина решения', exact: true })
    .fill('Требуется пересмотр');
  await otherCard.getByRole('button', { name: 'Сохранить решение', exact: true }).click();
  await expect
    .poll(async () => (await readClarifications(other, run)).questions[0]?.revision)
    .toBe(2);
  const card = page.getByRole('region', { name: question.text, exact: true });
  await expect(card.getByRole('button', { name: 'Сохранить ответ', exact: true })).toBeDisabled();
  await expect(card.getByRole('textbox', { name: 'Ответ архитектора', exact: true })).toHaveValue(
    'Черновик первой ревизии',
  );
  expect((await readClarifications(page, run)).decisions).toHaveLength(1);
  await page.reload();
  await expect(card.getByRole('button', { name: 'Сохранить ответ', exact: true })).toBeDisabled();
  await expect(
    card.getByRole('region', { name: 'Черновик прежней ревизии', exact: true }),
  ).toBeVisible();
  await card
    .getByRole('region', { name: 'Черновик прежней ревизии', exact: true })
    .screenshot({ path: testInfo.outputPath('stale-revision-draft.png') });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await card
    .getByRole('button', { name: 'Перенести черновик в текущую ревизию', exact: true })
    .click();
  await card.getByRole('button', { name: 'Сохранить ответ', exact: true }).click();
  await expect.poll(async () => (await runStatus(page, run)).status).toBe('completed');
  const saved = await readClarifications(page, run);
  expect(saved.decisions).toHaveLength(2);
  expect(saved.decisions.find((decision) => decision.question_revision === 2)?.text).toBe(
    'Черновик первой ревизии',
  );
  await other.close();
});

test('assumption mode and every draft field survive reload and create one assumption and one risk', async ({
  page,
}, testInfo) => {
  test.setTimeout(90000);
  const { run, question } = await newBlockedAnalysis(page);
  const card = await fillAnswer(page, question, 'Принять временный срок');
  await fillAssumption(card);
  await page.getByRole('button', { name: 'Открыть блокирующие вопросы', exact: true }).click();
  await page.reload();
  await expect(card.getByLabel('Принять как допущение', { exact: true })).toBeChecked();
  await expect(card.getByRole('textbox', { name: 'Ответ архитектора', exact: true })).toHaveValue(
    'Принять временный срок',
  );
  await expect(card.getByRole('textbox', { name: 'Основание ответа', exact: true })).toHaveValue(
    'Решение архитектора по результатам обсуждения',
  );
  for (const [label, value] of assumptionFields)
    await expect(card.getByRole('textbox', { name: label, exact: true })).toHaveValue(value);
  await card.getByRole('button', { name: 'Принять допущение', exact: true }).click();
  await expect.poll(async () => (await runStatus(page, run)).status).toBe('completed');
  await page.reload();
  const saved = await readClarifications(page, run);
  expect(saved.decisions.filter((decision) => decision.kind === 'assumption')).toHaveLength(1);
  expect(saved.risks).toHaveLength(1);
  await page.getByRole('tab', { name: 'Риски 1', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Риски A-07' })).toContainText('Потеря отчётов');
  await page
    .getByRole('region', { name: 'Риски A-07' })
    .screenshot({ path: testInfo.outputPath('assumption-risk-tab.png') });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole('link', { name: 'Допущение A-01', exact: true }).click();
  await expect(page.getByText('Принято допущение', { exact: true })).toBeVisible();
});
