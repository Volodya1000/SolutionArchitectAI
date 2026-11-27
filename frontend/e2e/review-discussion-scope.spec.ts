import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { clarificationSchema } from '../src/shared/api/clarifications';
import { readClarifications, uploadTextAndAnalyze } from './clarification-helpers';

test('a source panel uses the server scope and keeps another requirement assumption and risk out', async ({
  page,
}, testInfo) => {
  test.setTimeout(90000);
  const { run, version } = await uploadTextAndAnalyze(
    page,
    Buffer.from('Первое условие. [clarification:two]\n\nВторое условие.'),
  );
  const view = await readClarifications(page, run);
  const [selected, unrelated] = view.questions;
  const source = selected?.sources[0];
  if (!selected || !unrelated || !source) throw new Error('Expected two source-bound questions');
  expect(unrelated.sources[0]?.fragment_id).not.toBe(source.fragment_id);
  await page.getByRole('tab', { name: /^Уточнения / }).click();
  const card = page.locator(`#question-${unrelated.id}`);
  await card
    .getByRole('textbox', { name: 'Ответ архитектора', exact: true })
    .fill('Допущение другого требования');
  await card
    .getByRole('textbox', { name: 'Основание ответа', exact: true })
    .fill('Временное решение');
  await card.getByLabel('Принять как допущение', { exact: true }).check();
  for (const [label, value] of [
    ['Ответственный', 'Архитектор'],
    ['Условие проверки', 'До реализации'],
    ['Последствия', 'Риск другого требования'],
    ['Способ снижения риска', 'Проверка'],
  ])
    await card.getByRole('textbox', { name: label!, exact: true }).fill(value!);
  await card.getByRole('button', { name: 'Принять допущение', exact: true }).click();
  await expect.poll(async () => (await readClarifications(page, run)).decisions.length).toBe(1);
  await page.goto(
    `/documents?version=${version.version_id}&fragment=${source.fragment_id}&run=${run}`,
  );
  await page
    .locator('.selected-fragment')
    .getByRole('button', { name: 'Обсудить', exact: true })
    .click();
  await expect(page).toHaveURL(/\/chats\//);
  const chatPath = new URL(page.url()).pathname;
  const response = await page.request.get(`/api${chatPath}/discussion/clarifications`);
  expect(response.ok()).toBe(true);
  const payload: unknown = await response.json();
  const scoped = clarificationSchema.parse(payload);
  expect(scoped.questions.map((question) => question.id)).toEqual([selected.id]);
  expect(scoped.risks).toHaveLength(0);
  const panel = page.getByRole('complementary', { name: 'Предмет и источники обсуждения' });
  await expect(panel.locator(`#question-${selected.id}`)).toBeVisible();
  await expect(panel.locator(`#question-${unrelated.id}`)).toHaveCount(0);
  await expect(panel.getByText('Допущение другого требования', { exact: true })).toHaveCount(0);
  await expect(panel.getByText('Риск другого требования', { exact: true })).toHaveCount(0);
  await expect(panel.getByRole('textbox', { name: 'Ответ архитектора', exact: true })).toHaveCount(
    1,
  );
  await expect(page.getByRole('heading', { name: 'Рабочий чат', exact: true })).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath('scoped-source-discussion.png'),
    fullPage: true,
  });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.setViewportSize({ width: 440, height: 900 });
  await page.screenshot({
    path: testInfo.outputPath('scoped-source-discussion-mobile.png'),
    fullPage: true,
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});
