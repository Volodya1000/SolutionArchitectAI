import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import {
  LABELS,
  STATUS_TEXT,
  THEMES,
  answers,
  input,
  createChat,
  send,
  waitForCompletedResponse,
  cancelActiveGeneration,
  fetchChatState,
} from './chat-helpers';

test('two independent chats retain history after reopening', async ({ page }) => {
  await page.goto('/');
  const first = await createChat(page);
  await send(page, 'Первый независимый чат');
  await waitForCompletedResponse(page);
  const second = await createChat(page);
  await expect(page.getByText('Первый независимый чат', { exact: true })).toHaveCount(0);
  await send(page, 'Второй независимый чат');
  await waitForCompletedResponse(page);
  await page.goto(first);
  await expect(page.getByText('Первый независимый чат', { exact: true })).toBeVisible();
  await expect(page.getByText('Второй независимый чат', { exact: true })).toHaveCount(0);
  await page.goto(second);
  await expect(page.getByText('Второй независимый чат', { exact: true })).toBeVisible();
});

test('server cancellation keeps an incomplete answer after reload', async ({ page }) => {
  await page.goto('/');
  const chatUrl = await createChat(page);
  await send(page, '[slow] Проверка отмены');
  await expect(page.getByText(STATUS_TEXT.generating, { exact: true })).toBeVisible();
  await cancelActiveGeneration(page);
  await page.reload();
  await expect(answers(page).last().getByText(STATUS_TEXT.cancelledPartial)).toBeVisible();
  await send(page, 'Следующий полный ответ');
  await waitForCompletedResponse(page);
  await page.reload();
  await expect(answers(page)).toHaveCount(2);
  await expect(answers(page).first().getByText(STATUS_TEXT.cancelledPartial)).toBeVisible();
  await expect(answers(page).last().getByText(STATUS_TEXT.cancelledPartial)).toHaveCount(0);
  await expect(
    answers(page).last().getByText(STATUS_TEXT.completed, { exact: true }),
  ).toBeVisible();
  const state = await fetchChatState(page, chatUrl);
  expect(state.runs.map((run) => run.status)).toEqual(['cancelled', 'completed']);
  expect(state.messages.map((message) => [message.role, message.incomplete])).toEqual([
    ['user', false],
    ['assistant', true],
    ['user', false],
    ['assistant', false],
  ]);
});

test('LLM failure is visible and a new request works', async ({ page }) => {
  await page.goto('/');
  const chatUrl = await createChat(page);
  await send(page, '[error]');
  await expect(page.getByText(STATUS_TEXT.llmFailedRetryable)).toBeVisible();
  await send(page, 'Повтор после ошибки');
  await waitForCompletedResponse(page);
  const state = await fetchChatState(page, chatUrl);
  expect(state.runs.map((run) => run.status)).toEqual(['failed', 'completed']);
  expect(state.messages.map((message) => message.role)).toEqual([
    'user',
    'assistant',
    'user',
    'assistant',
  ]);
  expect(
    state.messages.filter((message) => message.role === 'user').map((message) => message.content),
  ).toEqual(['[error]', 'Повтор после ошибки']);
});

test('all themes persist and chat remains accessible', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  await page.goto('/');
  await createChat(page);
  for (const theme of THEMES) {
    await page.getByRole('combobox', { name: LABELS.themeSelect }).selectOption(theme);
    await expect(page.getByRole('combobox', { name: LABELS.themeSelect })).toHaveValue(theme);
    await page.reload();
    await expect(page.getByRole('combobox', { name: LABELS.themeSelect })).toHaveValue(theme);
    const sendButton = page.getByRole('button', { name: LABELS.sendButton });
    await expect(sendButton).toBeDisabled();
    await expect(sendButton).toHaveCSS(
      'background-color',
      theme === 'dark' ? 'rgb(51, 64, 77)' : 'rgb(220, 227, 232)',
    );
    await input(page).fill('   ');
    await expect(sendButton).toBeDisabled();
    await input(page).fill('Вопрос');
    await expect(sendButton).toBeEnabled();
    await expect(sendButton).toHaveCSS('background-color', 'rgb(35, 111, 101)');
    await input(page).clear();
    await expect(sendButton).toBeDisabled();
    const result = await new AxeBuilder({ page }).analyze();
    expect(result.violations).toEqual([]);
  }
  await input(page).focus();
  await page.keyboard.type('Сообщение с клавиатуры');
  await page.keyboard.press('Enter');
  await waitForCompletedResponse(page);
});

test('reopening an active stream does not generate a second run', async ({ page }) => {
  await page.goto('/');
  const url = await createChat(page);
  await send(page, '[slow] reconnect');
  await expect(page.getByRole('button', { name: LABELS.stopButton })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: LABELS.stopButton })).toBeVisible();
  await cancelActiveGeneration(page);
  const data = await fetchChatState(page, url);
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
  await expect(page.getByRole('button', { name: LABELS.stopButton })).toBeVisible();
  const second = await createChat(page);
  await input(page).fill('Черновик второго чата');
  await expect
    .poll(() => fetchChatState(page, first))
    .toMatchObject({
      messages: expect.arrayContaining([
        expect.objectContaining({ role: 'assistant', content: expect.stringMatching(/\S/) }),
      ]),
    });
  await expect(page.getByText('[slow] Поздний ответ первого чата', { exact: true })).toHaveCount(0);
  await page.goto(first);
  await cancelActiveGeneration(page);
  await page.goto(second);
  await expect(input(page)).toHaveValue('Черновик второго чата');
});

test('a lost start response is retried with the same command', async ({ page }) => {
  await page.goto('/');
  const url = await createChat(page);
  let lost = false;
  const commands: (string | null)[] = [];
  await page.route('**/api/chats/*/runs', async (route) => {
    commands.push(route.request().postData());
    if (lost) {
      await route.continue();
      return;
    }
    lost = true;
    // Wait for the server to accept the command, then discard only its response.
    const accepted = await route.fetch();
    expect(accepted.status()).toBe(202);
    await route.abort('failed');
  });
  await send(page, 'Ответ на потерянную команду');
  await expect(page.getByRole('button', { name: LABELS.retrySendButton })).toBeVisible();
  await page.reload();
  await expect(input(page)).toHaveValue('Ответ на потерянную команду');
  await page.getByRole('button', { name: LABELS.sendButton }).click();
  await waitForCompletedResponse(page);
  const data = await fetchChatState(page, url);
  expect(data).toMatchObject({ runs: [expect.objectContaining({ status: 'completed' })] });
  expect(data.messages.map((message) => message.role)).toEqual(['user', 'assistant']);
  expect(commands).toHaveLength(2);
  expect(commands[1]).toBe(commands[0]);
  await expect(input(page)).toHaveValue('');
});

test('a network break reconnects to the current server run', async ({ page, context }) => {
  await page.goto('/');
  await createChat(page);
  await send(page, '[slow] offline');
  await expect(page.getByText(STATUS_TEXT.generating, { exact: true })).toBeVisible();
  const beforeOffline = await answers(page).last().textContent();
  await context.setOffline(true);
  await expect(page.getByText(STATUS_TEXT.networkOrHistoryError)).toBeVisible();
  await context.setOffline(false);
  await expect(page.getByRole('button', { name: LABELS.stopButton })).toBeVisible();
  await expect.poll(() => answers(page).last().textContent()).not.toBe(beforeOffline);
  await expect(page.getByText(STATUS_TEXT.networkOrHistoryError)).toHaveCount(0);
  await cancelActiveGeneration(page);
});

test('a request interrupted before delivery can be retried without losing a new draft', async ({
  page,
}) => {
  await page.goto('/');
  const chatUrl = await createChat(page);
  await page.route('**/api/chats/*/runs', (route) => route.abort('failed'), { times: 1 });
  await send(page, 'Вопрос А');
  await expect(page.getByRole('button', { name: LABELS.retrySendButton })).toBeVisible();
  expect((await fetchChatState(page, chatUrl)).runs).toEqual([]);
  await input(page).fill('Новый вопрос Б');
  await page.getByRole('button', { name: LABELS.retrySendButton }).click();
  await waitForCompletedResponse(page);
  await expect(input(page)).toHaveValue('Новый вопрос Б');
  await page.reload();
  await expect(input(page)).toHaveValue('Новый вопрос Б');
  const state = await fetchChatState(page, chatUrl);
  expect(state.runs).toHaveLength(1);
  expect(state.messages.map((message) => message.role)).toEqual(['user', 'assistant']);
  expect(state.messages[0]?.content).toBe('Вопрос А');
});

test('a temporary stream 503 recovers to a completed answer without reload', async ({ page }) => {
  await page.goto('/');
  const chatUrl = await createChat(page);
  let failures = 0;
  await page.route('**/api/runs/*/events', async (route) => {
    if (failures++ === 0) {
      await route.fulfill({ status: 503, body: 'Temporarily unavailable' });
    } else {
      await route.continue();
    }
  });
  await send(
    page,
    'Проверка восстановления после временного отказа потока. ' + 'Важное требование. '.repeat(80),
  );
  await waitForCompletedResponse(page);
  expect(failures, 'The browser must exercise the injected stream failure').toBeGreaterThan(0);
  await expect(page.getByText(STATUS_TEXT.networkOrHistoryError)).toHaveCount(0);
  const state = await fetchChatState(page, chatUrl);
  expect(state.runs).toHaveLength(1);
  expect(state.runs[0]?.status).toBe('completed');
  await expect(answers(page).last()).toContainText(state.messages[1]?.content ?? 'missing answer');
});

test('narrow layout keeps navigation and input usable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await createChat(page);
  await expect(input(page)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await send(page, 'Проверка узкого экрана');
  await waitForCompletedResponse(page);
});
