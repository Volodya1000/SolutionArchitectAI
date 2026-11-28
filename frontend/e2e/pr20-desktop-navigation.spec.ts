import { expect, test } from '@playwright/test';
import { readClarifications, runStatus, uploadAndAnalyze } from './clarification-helpers';

test.use({ viewport: { width: 1440, height: 1000 } });

test('a requirement opens its question and returns with focus and a separately attributed answer', async ({
  page,
}, testInfo) => {
  await uploadAndAnalyze(page, 'incomplete');
  const row = page
    .getByRole('row')
    .filter({ hasText: 'R-04' })
    .filter({ has: page.getByRole('link', { name: /^Открыть вопрос:/ }) })
    .first();
  await expect(row).toBeAttached();
  await expect(row).not.toBeInViewport();
  await row.getByRole('link', { name: /^Открыть вопрос:/ }).click();
  const question = page.getByRole('region', {
    name: 'Как система реагирует на запрос даты вне окна?',
    exact: true,
  });
  await expect(question).toBeInViewport();
  await page.screenshot({ path: testInfo.outputPath('open-question-desktop.png') });
  await question.getByRole('link', { name: 'Вернуться к выбранному требованию' }).click();
  await expect(row).toBeInViewport();
  await expect(row).toBeFocused();
  await row.getByRole('link', { name: /^Открыть вопрос:/ }).click();
  await question
    .getByLabel('Ответ архитектора', { exact: true })
    .fill('Отклонять запрос и показывать допустимый диапазон дат');
  await question
    .getByLabel('Основание ответа', { exact: true })
    .fill('Решение архитектора после предметного обсуждения');
  await question.getByRole('button', { name: 'Сохранить ответ', exact: true }).click();
  await expect(question.getByText('Добавил архитектор', { exact: true })).toBeVisible();
  await question.getByRole('link', { name: 'Вернуться к выбранному требованию' }).click();
  await expect(row).toBeFocused();
  await expect(row.getByText('Добавленное условие архитектора', { exact: true })).toBeVisible();
  await expect(
    row.getByText('Отклонять запрос и показывать допустимый диапазон дат', { exact: true }),
  ).toBeVisible();
  await expect(row.locator('time')).toHaveAttribute('datetime', /\d{4}-\d{2}-\d{2}T/);
  await expect(
    row.getByText('Основание: Решение архитектора после предметного обсуждения'),
  ).toBeVisible();
  await row.getByText('Цитата из документа', { exact: true }).first().click();
  await expect(row.locator('blockquote').first()).toContainText('R-04');
  await page.screenshot({ path: testInfo.outputPath('answered-requirement-desktop.png') });
});

test('version history and source discussion retain the selected analysis', async ({ page }) => {
  const { run, name, version } = await uploadAndAnalyze(page, 'complete');
  await page
    .getByRole('link', { name: 'Выбрать документы для нового анализа', exact: true })
    .click();
  await page.getByRole('button', { name: `История версий ${name}`, exact: true }).click();
  await page
    .getByRole('table', { name: `Версии ${name}` })
    .getByRole('link')
    .first()
    .click();
  await expect.poll(() => new URL(page.url()).searchParams.get('run')).toBe(run);
  await expect.poll(() => new URL(page.url()).searchParams.get('version')).toBe(version.version_id);
  const subject = page.getByRole('article').filter({ hasText: 'R-04' }).first();
  const command = page.waitForRequest(
    (request) =>
      new URL(request.url()).pathname === '/api/discussions' && request.method() === 'POST',
  );
  await subject.getByRole('button', { name: 'Обсудить', exact: true }).click();
  const payload: unknown = (await command).postDataJSON();
  expect(payload).toMatchObject({
    subject: { kind: 'source', analysis_id: run, version_id: version.version_id },
  });
  await page.getByRole('link', { name: 'Вернуться к источнику', exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get('run')).toBe(run);
});

test('a reused assumption opens its risk and returns inside the selected analysis', async ({
  page,
}) => {
  test.setTimeout(90000);
  const { run: first } = await uploadAndAnalyze(page, 'incomplete');
  const row = page
    .getByRole('row')
    .filter({ hasText: 'R-04' })
    .filter({ has: page.getByRole('link', { name: /^Открыть вопрос:/ }) })
    .first();
  await row.getByRole('link', { name: /^Открыть вопрос:/ }).click();
  const card = page.getByRole('region', {
    name: 'Как система реагирует на запрос даты вне окна?',
    exact: true,
  });
  await card.getByLabel('Ответ архитектора', { exact: true }).fill('Отклонять запрос вне окна');
  await card.getByLabel('Основание ответа', { exact: true }).fill('До проверки владельцем');
  await card.getByLabel('Принять как допущение', { exact: true }).check();
  for (const [label, value] of [
    ['Ответственный', 'Архитектор'],
    ['Условие проверки', 'Согласовать'],
    ['Последствия', 'Отклонение запроса'],
    ['Способ снижения риска', 'Проверить с владельцем'],
  ] as const)
    await card.getByLabel(label, { exact: true }).fill(value);
  await card.getByRole('button', { name: 'Принять допущение', exact: true }).click();
  await expect.poll(async () => (await runStatus(page, first)).status).toBe('completed');
  await page
    .getByRole('link', { name: 'Выбрать документы для нового анализа', exact: true })
    .click();
  await page.getByRole('button', { name: 'Повторить анализ', exact: true }).click();
  await expect(page).toHaveURL(/\/requirements\?run=/);
  const second = new URL(page.url()).searchParams.get('run');
  expect(second).not.toBe(first);
  if (!second) throw new Error('Expected second analysis');
  await expect
    .poll(async () => (await runStatus(page, second)).status, { timeout: 30000 })
    .toBe('completed');
  await page.getByRole('tab', { name: /^Уточнения / }).click();
  await page.getByRole('link', { name: 'Риск A-07', exact: true }).click();
  expect(new URL(page.url()).searchParams.get('run')).toBe(second);
  await expect(page.getByRole('region', { name: 'Риски A-07' })).toBeVisible();
  await page.getByRole('link', { name: 'Допущение A-01', exact: true }).click();
  expect(new URL(page.url()).searchParams.get('run')).toBe(second);
  await expect(page.getByText('Принято допущение', { exact: true })).toBeVisible();
});

test('an explicit history choice is sent without changing the pinned document analysis', async ({
  page,
}) => {
  const { run: first } = await uploadAndAnalyze(page, 'complete');
  const firstHistory = (await readClarifications(page, first)).history_id;
  const { run: second } = await uploadAndAnalyze(page, 'complete');
  await page
    .getByRole('link', { name: 'Выбрать документы для нового анализа', exact: true })
    .click();
  await page.getByLabel('Начать с новой историей уточнений', { exact: true }).uncheck();
  await page.getByRole('combobox', { name: 'История уточнений', exact: true }).selectOption(first);
  expect(new URL(page.url()).searchParams.get('run')).toBe(second);
  const sent = page.waitForRequest(
    (request) =>
      new URL(request.url()).pathname === '/api/extractions' && request.method() === 'POST',
  );
  await page.getByRole('button', { name: /^(Извлечь требования|Повторить анализ)$/ }).click();
  const payload: unknown = (await sent).postDataJSON();
  expect(payload).toMatchObject({ answer_history_mode: 'reuse', answer_history_id: firstHistory });
});
