import { expect, type Page } from '@playwright/test';
import { snapshotSchema, type Snapshot } from '../src/shared/api/client';

export const LABELS = {
  newChat: 'Новый чат',
  messageInput: 'Сообщение',
  sendButton: 'Отправить сообщение',
  stopButton: 'Остановить генерацию',
  retrySendButton: 'Повторить отправку',
  themeSelect: 'Тема',
  assistant: 'Ответ ассистента',
} as const;
export const STATUS_TEXT = {
  completed: 'Ответ завершён',
  generating: 'Формируется ответ…',
  cancelledPartial: 'Генерация отменена. Частичный ответ сохранён.',
  llmFailedRetryable: 'Ответ не завершён. Можно отправить новый запрос.',
  networkOrHistoryError: /Соединение прервано|История недоступна/,
} as const;
export const THEMES = ['light', 'dark', 'system'] as const;
export const input = (page: Page) => page.getByRole('textbox', { name: LABELS.messageInput });
export const answers = (page: Page) => page.getByRole('article', { name: LABELS.assistant });

export async function createChat(page: Page): Promise<string> {
  const previous = page.url();
  await page.getByRole('button', { name: LABELS.newChat, exact: true }).click();
  await expect(page).not.toHaveURL(previous);
  await expect(input(page)).toBeVisible();
  return page.url();
}

export async function send(page: Page, text: string): Promise<void> {
  await input(page).fill(text);
  await page.getByRole('button', { name: LABELS.sendButton }).click();
}

export async function waitForCompletedResponse(page: Page): Promise<void> {
  await expect(
    answers(page).last().getByText(STATUS_TEXT.completed, { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: LABELS.stopButton })).toHaveCount(0);
}

export async function cancelActiveGeneration(page: Page): Promise<void> {
  const stop = page.getByRole('button', { name: LABELS.stopButton });
  await expect(stop).toBeVisible();
  await stop.click();
  await expect(answers(page).last().getByText(STATUS_TEXT.cancelledPartial)).toBeVisible();
}

export async function fetchChatState(page: Page, chatUrl: string): Promise<Snapshot> {
  const match = /^\/chats\/([^/]+)$/.exec(new URL(chatUrl).pathname);
  if (!match?.[1]) throw new Error(`Expected a chat URL: ${chatUrl}`);
  const response = await page.request.get(`/api/chats/${match[1]}`);
  expect(response.ok(), `Read chat history: HTTP ${response.status()}`).toBe(true);
  const payload: unknown = await response.json();
  return snapshotSchema.parse(payload);
}
