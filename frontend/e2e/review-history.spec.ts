import { expect, test } from '@playwright/test';
import { readClarifications, uploadTextAndAnalyze } from './clarification-helpers';

for (const newHistory of [false, true]) {
  test(`requirements document selection ${newHistory ? 'starts an explicit new history' : 'reuses the selected history'}`, async ({
    page,
  }) => {
    const { run } = await uploadTextAndAnalyze(
      page,
      Buffer.from('Система должна сохранять отчёты.'),
    );
    const before = await readClarifications(page, run);
    await page
      .getByRole('link', { name: 'Выбрать документы для нового анализа', exact: true })
      .click();
    await expect(page).toHaveURL(new RegExp(`/documents\\?run=${run}`));
    await expect(
      page.getByText('Используется история выбранного анализа.', { exact: false }),
    ).toBeVisible();
    if (newHistory)
      await page.getByLabel('Начать с новой историей уточнений', { exact: true }).check();
    const response = page.waitForResponse(
      (candidate) =>
        new URL(candidate.url()).pathname === '/api/extractions' &&
        candidate.request().method() === 'POST',
    );
    await page
      .getByRole('button', {
        name: newHistory ? 'Извлечь требования' : 'Повторить анализ',
        exact: true,
      })
      .click();
    const started = await response;
    expect(started.ok()).toBe(true);
    const command: unknown = started.request().postDataJSON();
    expect(command).toMatchObject({
      answer_history_mode: newHistory ? 'new' : 'reuse',
      answer_history_id: newHistory ? null : before.history_id,
    });
    await expect(page).toHaveURL(/\/requirements\?run=/);
    const nextRun = new URL(page.url()).searchParams.get('run');
    if (!nextRun) throw new Error('Expected the new analysis');
    await expect
      .poll(async () => (await readClarifications(page, nextRun)).history_id)
      .toBe(newHistory ? nextRun : before.history_id);
  });
}

test('an unanswered matching history opens its waiting run until a new history is explicitly selected', async ({
  page,
}) => {
  const { run } = await uploadTextAndAnalyze(
    page,
    Buffer.from('Проверить ввод. [clarification:block]'),
  );
  await page
    .getByRole('link', { name: 'Выбрать документы для нового анализа', exact: true })
    .click();
  await expect(page.getByRole('link', { name: 'Открыть анализ', exact: true })).toHaveAttribute(
    'href',
    `/requirements?run=${run}`,
  );
  await expect(page.getByRole('button', { name: 'Повторить анализ', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Извлечь требования', exact: true })).toHaveCount(
    0,
  );
  await page.getByLabel('Начать с новой историей уточнений', { exact: true }).check();
  await expect(page.getByRole('button', { name: 'Извлечь требования', exact: true })).toBeEnabled();
});
