import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

test('immutable BRD versions produce a persisted A-01 registry with exact source navigation', async ({
  page,
}) => {
  const name = `BRD-${crypto.randomUUID()}.md`;
  const original =
    '# Сервис отчётности\n\n## Требования\nСистема должна сохранять отчёты.\nПользователь должен скачивать отчёт в CSV.\n';
  await page.goto('/documents');
  await page
    .getByLabel('Новый документ', { exact: true })
    .setInputFiles({ name, mimeType: 'text/markdown', buffer: Buffer.from(original) });
  await page.getByRole('button', { name: 'Загрузить документ', exact: true }).click();
  await expect(
    page.getByText('Версия сохранена. Ранее загруженные версии доступны в истории.'),
  ).toBeVisible();
  await page.getByRole('button', { name: `История версий ${name}` }).click();
  const versions = page.getByRole('table', { name: `Версии ${name}` });
  const oldLink = versions.getByRole('link').first();
  const oldUrl = await oldLink.getAttribute('href');
  expect(oldUrl).toBeTruthy();
  if (!oldUrl) throw new Error('The saved version must be addressable');
  const versionId = new URL(oldUrl, page.url()).searchParams.get('version');
  expect(versionId).toBeTruthy();
  await page.getByLabel(`Новая редакция ${name}`, { exact: true }).setInputFiles({
    name,
    mimeType: 'text/markdown',
    buffer: Buffer.from('# Новая редакция\nСистема должна архивировать отчёты.\n'),
  });
  await page.getByRole('button', { name: 'Загрузить редакцию', exact: true }).click();
  await expect(versions.getByRole('link')).toHaveCount(2);
  const storedOriginal = await page.request.get(`/api/document-versions/${versionId}/content`);
  expect(storedOriginal.ok()).toBe(true);
  expect(await storedOriginal.text()).toBe(original);
  await versions.getByRole('checkbox', { name: `Анализировать ${name} · ${versionId}` }).check();
  await page.getByText('Уточнить анализ', { exact: true }).click();
  await page
    .getByRole('textbox', { name: 'На что обратить внимание (необязательно)' })
    .fill('Требования сервиса отчётности');
  await page.getByRole('button', { name: 'Извлечь требования', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Требования', level: 1 })).toBeVisible();
  await expect(page.getByText('Извлечение завершено', { exact: true })).toBeVisible({
    timeout: 30000,
  });
  const registry = page.getByRole('table', { name: 'Кандидаты требований' });
  await expect(registry.getByRole('row')).not.toHaveCount(1);
  await expect(page.getByText('Весь текст документа обработан.')).toBeVisible();
  const registryUrl = page.url();
  const evidence = registry.getByRole('link', { name: /Источник/ }).first();
  await expect(evidence).toHaveAttribute('href', new RegExp(`version=${versionId}&fragment=`));
  await evidence.click();
  await expect(page.getByRole('region', { name: `Версия ${versionId}` })).toBeVisible();
  await expect(page.getByRole('region', { name: `Версия ${versionId}` })).toContainText(
    'Система должна сохранять отчёты.',
  );
  await page.goto(registryUrl);
  await expect(page.getByText('Извлечение завершено', { exact: true })).toBeVisible();
  await expect(registry.getByRole('link', { name: /Источник/ }).first()).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test('document workspace remains keyboard accessible in narrow dark layout', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/documents');
  await page.getByRole('combobox', { name: 'Тема', exact: true }).selectOption('dark');
  await expect(page.getByLabel('Новый документ', { exact: true })).toBeVisible();
  await page.getByText('Уточнить анализ', { exact: true }).click();
  await page.getByRole('textbox', { name: 'На что обратить внимание (необязательно)' }).focus();
  await expect(
    page.getByRole('textbox', { name: 'На что обратить внимание (необязательно)' }),
  ).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test('a document can be selected and analyzed with history and optional clarification collapsed', async ({
  page,
}) => {
  const name = `Latest-${crypto.randomUUID()}.txt`;
  await page.goto('/documents');
  const start = page.getByRole('button', { name: 'Извлечь требования', exact: true });
  await expect(start).toBeDisabled();
  await expect(
    page.getByText('Выберите документы для анализа с помощью флажков в списке выше.'),
  ).toBeVisible();
  await page.getByLabel('Новый документ', { exact: true }).setInputFiles({
    name,
    mimeType: 'text/plain',
    buffer: Buffer.from('Система должна сохранять отчёты.'),
  });
  await page.getByRole('button', { name: 'Загрузить документ', exact: true }).click();
  const latest = page.getByRole('checkbox', { name: `Выбрать последнюю версию ${name}` });
  await latest.check();
  await expect(page.getByRole('button', { name: `История версий ${name}` })).toHaveAttribute(
    'aria-expanded',
    'false',
  );
  await expect(page.getByLabel('На что обратить внимание (необязательно)')).not.toBeVisible();
  await expect(start).toBeEnabled();
  await start.click();
  await expect(page.getByText('Извлечение завершено', { exact: true })).toBeVisible({
    timeout: 30000,
  });
  const row = page.getByRole('table', { name: 'Кандидаты требований' }).getByRole('row').nth(1);
  await row.getByText('Цитата из документа', { exact: true }).click();
  await expect(row.locator('blockquote')).toHaveCount(1);
  await expect(row.getByText('Технические сведения', { exact: true })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
