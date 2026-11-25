import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

async function createChat(page: Page) {
  const previous = page.url();
  await page.getByRole('button', { name: 'Новый чат', exact: true }).click();
  await expect(page).not.toHaveURL(previous);
  await expect(page.getByRole('textbox', { name: 'Сообщение' })).toBeVisible();
  return page.url();
}
async function send(page: Page, text: string) {
  await page.getByRole('textbox', { name: 'Сообщение' }).fill(text);
  await page.getByRole('button', { name: 'Отправить сообщение' }).click();
}

test('two independent chats retain history after reopening', async ({ page }) => {
  await page.goto('/');
  const first = await createChat(page);
  await send(page, 'Первый независимый чат');
  await expect(page.getByText('Ответ завершён', { exact: true })).toBeVisible();
  const second = await createChat(page);
  await expect(page.getByText('Первый независимый чат', { exact: true })).toHaveCount(0);
  await send(page, 'Второй независимый чат');
  await expect(page.getByText('Ответ завершён', { exact: true })).toBeVisible();
  await page.goto(first);
  await expect(page.getByText('Первый независимый чат', { exact: true })).toBeVisible();
  await expect(page.getByText('Второй независимый чат', { exact: true })).toHaveCount(0);
  await page.goto(second);
  await expect(page.getByText('Второй независимый чат', { exact: true })).toBeVisible();
});

test('server cancellation keeps an incomplete answer after reload', async ({ page }) => {
  await page.goto('/');
  await createChat(page);
  await send(page, '[slow] Проверка отмены');
  await expect(page.getByText('Формируется ответ…', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Остановить генерацию' }).click();
  await expect(page.getByText('Генерация отменена. Частичный ответ сохранён.')).toBeVisible();
  await page.reload();
  await expect(page.getByText('Генерация отменена. Частичный ответ сохранён.')).toBeVisible();
});

test('LLM failure is visible and a new request works', async ({ page }) => {
  await page.goto('/');
  await createChat(page);
  await send(page, '[error]');
  await expect(page.getByText('Ответ не завершён. Можно отправить новый запрос.')).toBeVisible();
  await send(page, 'Повтор после ошибки');
  await expect(page.getByText('Ответ завершён', { exact: true })).toBeVisible();
});

test('all themes persist and chat remains accessible', async ({ page }) => {
  await page.goto('/');
  await createChat(page);
  for (const theme of ['light', 'dark', 'system']) {
    await page.getByRole('combobox', { name: 'Тема' }).selectOption(theme);
    await expect(page.getByRole('combobox', { name: 'Тема' })).toHaveValue(theme);
    await page.reload();
    await expect(page.getByRole('combobox', { name: 'Тема' })).toHaveValue(theme);
    const result = await new AxeBuilder({ page }).analyze();
    expect(result.violations).toEqual([]);
  }
  await page.getByRole('textbox', { name: 'Сообщение' }).focus();
  await page.keyboard.type('Сообщение с клавиатуры');
  await page.keyboard.press('Enter');
  await expect(page.getByText('Ответ завершён', { exact: true })).toBeVisible();
});

test('reopening an active stream does not generate a second run', async ({ page }) => {
  await page.goto('/');
  const url = await createChat(page);
  await send(page, '[slow] reconnect');
  await expect(page.getByRole('button', { name: 'Остановить генерацию' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Остановить генерацию' })).toBeVisible();
  await page.getByRole('button', { name: 'Остановить генерацию' }).click();
  await expect(page.getByText('Генерация отменена. Частичный ответ сохранён.')).toBeVisible();
  const response = await page.request.get(`/api/chats/${url.split('/').at(-1) ?? ''}`);
  const data: unknown = await response.json();
  expect(data).toMatchObject({
    messages: [
      expect.objectContaining({ role: 'user' }),
      expect.objectContaining({ role: 'assistant' }),
    ],
    runs: [expect.objectContaining({ status: 'cancelled' })],
  });
});

test('late events stay in their chat and a draft survives switching', async ({ page }) => {
  await page.goto('/');
  const first = await createChat(page);
  await send(page, '[slow] Поздний ответ первого чата');
  await expect(page.getByRole('button', { name: 'Остановить генерацию' })).toBeVisible();
  const second = await createChat(page);
  await page.getByRole('textbox', { name: 'Сообщение' }).fill('Черновик второго чата');
  await expect
    .poll(async () => {
      const response = await page.request.get(`/api/chats/${first.split('/').at(-1) ?? ''}`);
      const data: unknown = await response.json();
      return data;
    })
    .toMatchObject({
      messages: expect.arrayContaining([
        expect.objectContaining({ role: 'assistant', content: expect.stringMatching(/\S/) }),
      ]),
    });
  await expect(page.getByText('[slow] Поздний ответ первого чата', { exact: true })).toHaveCount(0);
  await page.goto(first);
  await page.getByRole('button', { name: 'Остановить генерацию' }).click();
  await expect(page.getByText('Генерация отменена. Частичный ответ сохранён.')).toBeVisible();
  await page.goto(second);
  await expect(page.getByRole('textbox', { name: 'Сообщение' })).toHaveValue(
    'Черновик второго чата',
  );
});

test('a lost start response is retried with the same command', async ({ page }) => {
  await page.goto('/');
  const url = await createChat(page);
  let lost = false;
  await page.route('**/api/chats/*/runs', async (route) => {
    if (lost) {
      await route.continue();
      return;
    }
    lost = true;
    await route.fetch();
    await route.abort('failed');
  });
  await send(page, 'Ответ на потерянную команду');
  await expect(page.getByRole('button', { name: 'Повторить отправку' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('textbox', { name: 'Сообщение' })).toHaveValue(
    'Ответ на потерянную команду',
  );
  await page.getByRole('button', { name: 'Отправить сообщение' }).click();
  await expect(page.getByText('Ответ завершён', { exact: true })).toBeVisible();
  const response = await page.request.get(`/api/chats/${url.split('/').at(-1) ?? ''}`);
  const data: unknown = await response.json();
  expect(data).toMatchObject({ runs: [expect.objectContaining({ status: 'completed' })] });
  await expect(page.getByRole('textbox', { name: 'Сообщение' })).toHaveValue('');
});

test('a network break reconnects to the current server run', async ({ page, context }) => {
  await page.goto('/');
  await createChat(page);
  await send(page, '[slow] offline');
  await expect(page.getByText('Формируется ответ…', { exact: true })).toBeVisible();
  await context.setOffline(true);
  await expect(page.getByText(/Соединение прервано|История недоступна/)).toBeVisible();
  await context.setOffline(false);
  await expect(page.getByRole('button', { name: 'Остановить генерацию' })).toBeVisible();
  await page.getByRole('button', { name: 'Остановить генерацию' }).click();
  await expect(page.getByText('Генерация отменена. Частичный ответ сохранён.')).toBeVisible();
});

test('narrow layout keeps navigation and input usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await createChat(page);
  await expect(page.getByRole('textbox', { name: 'Сообщение' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await send(page, 'Проверка узкого экрана');
  await expect(page.getByText('Ответ завершён', { exact: true })).toBeVisible();
});
